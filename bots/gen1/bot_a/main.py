"""
GPT6 Astra
Adaptive no-limit Hold'em bot for fresh-stack duplicate tournaments.
Position-aware preflop ranges provide a disciplined starting strategy, while
Bayesian style estimates adapt to callers, frequent shovers and frequent folders.
Card-removal-aware simulations compare legal bets against action-conditioned
ranges, including split pots, side pots and the cost of future betting.
Near the end of a game, simulated placement replaces chip margin as the objective;
bounded computation and guarded hooks protect the tournament clock and protocol.
"""

import math
import time
from itertools import combinations

import numpy as np
from macpoker import Bot


def card(text):
    return 4 * "23456789TJQKA".index(text[0]) + "shdc".index(text[1])


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -35, 35)))


class MyBot(Bot):
    def __init__(self):
        self.ready = False
        self.stats = {}
        self.totals = {}
        self.squares = {}
        self.completed = 0
        self.num_hands = 100
        self.stack = 200
        self.bb = 2
        self.errors = 0
        self.hand_key = None
        self.cache = {}
        self.seen = set()
        self.raised = set()
        self.event_bets = []
        self.event_street = "preflop"
        self.mean_ms = 12.0

    def _stat(self, player):
        if player not in self.stats:
            self.stats[player] = dict(
                log=np.log([.84, .04, .04, .04, .04]),
                hands=0, vpip=0, pfr=0, faced=0, folds=0,
                calls=0, raises=0, post=0, postraises=0)
        return self.stats[player]

    def _profile(self, player):
        d = self._stat(player)
        p = np.exp(d["log"] - max(d["log"]))
        p /= p.sum()
        # Keep a small uncertainty component even after a strong classification.
        p = .96 * p + .04 * np.array([.84, .04, .04, .04, .04])
        loose = (d["vpip"] + 2.5) / (d["hands"] + 8)
        aggr = (d["pfr"] + 1.6) / (d["hands"] + 8)
        return p, loose, aggr

    def on_match_start(self, info):
        try:
            self.__init__()
            self.stack = int(info["stack"])
            self.bb = int(info["blinds"][1])
            self.num_hands = int(info["num_hands"])
        except Exception:
            self.errors += 1

    def on_hand_start(self, info):
        try:
            self.hand_key = info["hand"]
            self.cache = {}
            self.seen = set()
            self.raised = set()
            self.event_street = "preflop"
            n = len(info["players"])
            self.event_bets = [0] * n
            button = info["button"]
            self.event_bets[button if n == 2 else (button + 1) % n] = self.bb // 2
            self.event_bets[(button + (1 if n == 2 else 2)) % n] = self.bb
            for p in info["players"]:
                self._stat(p)["hands"] += 1
        except Exception:
            self.errors += 1

    def on_street(self, event):
        try:
            self.event_street = event["street"]
            self.event_bets = [0] * len(event["players"])
        except Exception:
            self.errors += 1

    def on_action(self, event):
        try:
            seat = event["seat"]
            player = event["players"][seat]
            d = self._stat(player)
            kind, amount = event["action"], event["amount"]
            pre = event["street"] == "preflop"
            if event["street"] != self.event_street:
                self.event_bets = [0] * len(event["players"])
                self.event_street = event["street"]
            facing = max(self.event_bets, default=0) > self.event_bets[seat]
            if pre and kind in ("raise", "call") and player not in self.seen:
                d["vpip"] += 1
                self.seen.add(player)
            if pre and kind == "raise" and player not in self.raised:
                d["pfr"] += 1
                self.raised.add(player)
            if facing:
                d["faced"] += 1
                d["folds"] += kind == "fold"
            d["calls"] += kind == "call"
            d["raises"] += kind == "raise"
            if not pre:
                d["post"] += 1
                d["postraises"] += kind == "raise"
            if kind == "raise":
                probs = [.16 if facing else .38, .002, .98, .002, .30]
                if pre and amount >= self.stack * .65:
                    probs = [.025, .001, .98, .001, .09]
                elif pre:
                    probs[2] = .008
                self.event_bets[seat] = amount
            elif kind == "call":
                probs = [.36 if pre else .46, .997, .015, .002, .40]
                self.event_bets[seat] += amount
            elif kind == "fold":
                probs = [.48 if pre else .38, .001, .005, .998, .30]
            else:
                probs = [.62, .998, .01, .998, .70]
            d["log"] += .65 * np.log(probs)
            # A style can change; old evidence must not lock the model forever.
            d["log"] = np.maximum(d["log"] - max(d["log"]), -14)
        except Exception:
            self.errors += 1

    def on_hand_end(self, info):
        try:
            for p, delta in zip(info["players"], info["deltas"]):
                self.totals[p] = self.totals.get(p, 0) + delta
                self.squares[p] = self.squares.get(p, 0) + delta * delta
            self.completed += 1
            self.cache = {}
        except Exception:
            self.errors += 1

    def _init_tables(self):
        self.rng = np.random.default_rng()
        self.combos = np.array(list(combinations(range(52), 2)), dtype=np.int32)
        self.bits = np.left_shift(np.uint64(1), np.arange(52, dtype=np.uint64))
        self.combo_bits = self.bits[self.combos[:, 0]] | self.bits[self.combos[:, 1]]
        masks = np.arange(8192, dtype=np.int32)
        self.high = np.zeros(8192, dtype=np.int32)
        self.top = np.zeros(8192, dtype=np.int32)
        self.count = np.zeros(8192, dtype=np.int32)
        self.straight = np.zeros(8192, dtype=np.int32)
        for r in range(12, -1, -1):
            present = (masks & (1 << r)) != 0
            self.high = np.where(present & (self.high == 0), r + 2, self.high)
            self.top |= np.where(present & (self.count < 5),
                                 (r + 2) << (4 * np.maximum(4 - self.count, 0)), 0)
            self.count += present
        self.straight[(masks & 4111) == 4111] = 5
        for r in range(4, 13):
            pattern = 31 << (r - 4)
            self.straight[(masks & pattern) == pattern] = r + 2
        a, b = self.combos[:, 0] // 4 + 2, self.combos[:, 1] // 4 + 2
        hi, lo = np.maximum(a, b), np.minimum(a, b)
        suited = self.combos[:, 0] % 4 == self.combos[:, 1] % 4
        gap = hi - lo
        raw = (.30 + .023 * hi + .012 * lo + .035 * suited
               - .009 * np.maximum(gap - 1, 0)
               + .012 * (gap == 1) + .012 * ((hi == 14) & (lo <= 5) & suited))
        # Pairs retain set value; premium pairs must outrank suited broadways.
        raw += .035 * suited * (gap <= 2) * (hi <= 10)
        raw = np.where(a == b, .64 + .020 * (hi - 2), raw)
        ordered = np.sort(raw)
        self.pct = 1 - (np.searchsorted(ordered, raw, side="left")
                        + np.searchsorted(ordered, raw, side="right")) / (2 * len(raw))
        self.lookup = np.full((52, 52), -1, dtype=np.int32)
        idx = np.arange(len(raw))
        self.lookup[self.combos[:, 0], self.combos[:, 1]] = idx
        self.lookup[self.combos[:, 1], self.combos[:, 0]] = idx
        self.ready = True

    def _evaluate(self, cards):
        """Exact best-five ordering of batches of five, six or seven cards."""
        ranks, suits = cards // 4, cards % 4
        rb = 1 << ranks
        sm = [np.bitwise_or.reduce(np.where(suits == s, rb, 0), axis=1) for s in range(4)]
        a, b, c, d = sm
        mask = a | b | c | d
        pairs = (a & b) | (a & c) | (a & d) | (b & c) | (b & d) | (c & d)
        trips = (a & b & c) | (a & b & d) | (a & c & d) | (b & c & d)
        quads = a & b & c & d
        p, t, q = self.high[pairs], self.high[trips], self.high[quads]
        pbit = np.where(p > 0, 1 << np.maximum(p - 2, 0), 0)
        tbit = np.where(t > 0, 1 << np.maximum(t - 2, 0), 0)
        qbit = np.where(q > 0, 1 << np.maximum(q - 2, 0), 0)
        p2 = self.high[pairs & ~pbit]
        p2bit = np.where(p2 > 0, 1 << np.maximum(p2 - 2, 0), 0)
        value = self.top[mask].copy()
        value = np.where(p > 0, (1 << 20) | (p << 16) | ((self.top[mask & ~pbit] >> 4) & 0xFFF0), value)
        value = np.where(p2 > 0, (2 << 20) | (p << 16) | (p2 << 12)
                         | (self.high[mask & ~pbit & ~p2bit] << 8), value)
        value = np.where(t > 0, (3 << 20) | (t << 16) | ((self.top[mask & ~tbit] >> 4) & 0xFF00), value)
        straight = self.straight[mask]
        value = np.where(straight > 0, (4 << 20) | (straight << 16), value)
        sf = np.zeros(len(cards), dtype=np.int32)
        for suitmask in sm:
            value = np.where(self.count[suitmask] >= 5, (5 << 20) | self.top[suitmask], value)
            sf = np.maximum(sf, self.straight[suitmask])
        fullpair = self.high[pairs & ~tbit]
        value = np.where((t > 0) & (fullpair > 0), (6 << 20) | (t << 16) | (fullpair << 12), value)
        value = np.where(q > 0, (7 << 20) | (q << 16) | (self.high[mask & ~qbit] << 12), value)
        return np.where(sf > 0, (8 << 20) | (sf << 16), value)

    def _features(self, board, valid):
        key = tuple(board)
        if key in self.cache:
            return self.cache[key]
        m = len(self.combos)
        allcards = np.concatenate((self.combos, np.tile(board, (m, 1))), axis=1)
        values = self._evaluate(allcards)
        ordered = np.sort(values[valid])
        quality = (np.searchsorted(ordered, values, "left")
                   + np.searchsorted(ordered, values, "right")) / (2 * len(ordered))
        draw = np.zeros(m)
        if len(board) < 5:
            ranks = allcards // 4
            mask = np.bitwise_or.reduce(1 << ranks, axis=1)
            boardmask = 0
            for x in board:
                boardmask |= 1 << (x // 4)
            for suit in range(4):
                count = (allcards % 4 == suit).sum(axis=1)
                uses = (self.combos % 4 == suit).any(axis=1)
                draw = np.maximum(draw, np.where((count == 4) & uses, .34 if len(board) == 3 else .19, 0))
            for pattern in [4111] + [31 << r for r in range(9)]:
                four = self.count[mask & pattern] == 4
                uses = (mask & pattern) != (boardmask & pattern)
                draw = np.maximum(draw, np.where(four & uses, .25 if len(board) == 3 else .14, 0))
            draw = np.where(values >> 20 >= 4, 0, draw)
        self.cache[key] = quality, draw
        return quality, draw

    def _opening(self, seat, button, n):
        pos = (seat - button) % n
        if n == 2:
            return .72 if pos == 0 else .48
        if pos == 0:
            return .46
        if pos == 1:
            return .36
        if pos == 2:
            return .30
        return max(.13, .29 - .035 * (n - pos - 1))

    def _ranges(self, s, opponents, known, board):
        valid = (self.combo_bits & known) == 0
        weights = []
        current = self._features(board, valid) if board else (1 - self.pct, np.zeros(len(self.pct)))
        for seat in opponents:
            profile, loose, aggr = self._profile(s.players[seat])
            regular, station, maniac, folder, random = profile
            own = [h for h in s.history if h[1] == seat]
            width = 1.0
            raises = 0
            for street, who, kind, amount in s.history:
                if street != "preflop":
                    continue
                if kind == "raise":
                    raises += 1
                if who != seat:
                    continue
                if kind == "raise":
                    base = self._opening(seat, s.button, s.num_players)
                    width = min(.65, max(.06, .6 * base + .4 * aggr))
                    if raises >= 2:
                        width = min(width, .065 if raises == 2 else .025)
                    if amount >= 20 * self.bb:
                        width = min(width, .035)
                    elif amount >= 6 * self.bb:
                        width *= .65
                elif kind == "call":
                    width = min(width, max(.12, loose) if raises else max(.30, loose))
                    if raises >= 2:
                        width = min(width, .10)
            base = (.0003 + sigmoid((width - self.pct) / .018)) * valid
            broad = min(.99, station + maniac + .8 * random)
            # Mix normalized distributions: a 5% random-hand component must
            # remain 5% even when the regular player's range is very narrow.
            w = (1 - broad) * base / base.sum() + broad * valid / valid.sum()
            for street in ("flop", "turn", "river"):
                length = {"flop": 3, "turn": 4, "river": 5}[street]
                if len(board) < length:
                    break
                q, draw = self._features(board[:length], valid)
                aggression = 0
                for hstreet, who, kind, amount in s.history:
                    if hstreet != street:
                        continue
                    if kind == "raise":
                        aggression += 1
                    if who != seat:
                        continue
                    if kind == "raise":
                        threshold = .68 + .10 * (aggression > 1) + .07 * (amount > s.pot * .65)
                        likelihood = .035 + .80 * sigmoid((q - threshold) / .075) + .55 * draw
                        likelihood = ((1 - maniac - random) * likelihood + maniac + random * .60)
                    elif kind == "call":
                        likelihood = .06 + .88 * sigmoid((q - .48) / .12) + .65 * draw
                        likelihood = (1 - station - maniac - random) * likelihood + station + maniac + random * .65
                    elif kind == "check":
                        likelihood = .95 - .38 * sigmoid((q - .88) / .06)
                        likelihood = (1 - station - folder) * likelihood + station + folder
                    else:
                        continue
                    w *= np.maximum(likelihood, .015) ** .8
            w *= valid
            total = w.sum()
            weights.append(w / total if total > 0 else valid / valid.sum())
        return weights, current

    def _worlds(self, s, opponents, hole, board, samples, deadline):
        known = np.uint64(0)
        for x in hole + board:
            known |= self.bits[x]
        weights, features = self._ranges(s, opponents, known, board)
        cdfs = [np.cumsum(w) for w in weights]
        accepted = []
        count = 0
        for _ in range(12):
            size = max(128, (samples - count) * 2)
            ids = np.column_stack([np.minimum(np.searchsorted(cdf, self.rng.random(size)), 1325) for cdf in cdfs])
            used = np.full(size, known, dtype=np.uint64)
            valid = np.ones(size, dtype=bool)
            for j in range(len(opponents)):
                bits = self.combo_bits[ids[:, j]]
                valid &= (bits & used) == 0
                used |= bits
            accepted.append(ids[valid])
            count += int(valid.sum())
            if count >= samples or (count >= 80 and time.perf_counter() > deadline):
                break
        ids = np.concatenate(accepted)[:samples]
        if len(ids) < 16:
            raise ValueError("Insufficient compatible range samples")
        size, n = ids.shape
        used = np.full(size, known, dtype=np.uint64)
        for j in range(n):
            used |= self.combo_bits[ids[:, j]]
        boards = np.empty((size, 5), dtype=np.int32)
        if board:
            boards[:, :len(board)] = board
        for j in range(len(board), 5):
            cards = self.rng.integers(0, 52, size=size)
            bad = (self.bits[cards] & used) != 0
            for _ in range(64):
                if not bad.any():
                    break
                cards[bad] = self.rng.integers(0, 52, size=int(bad.sum()))
                bad = (self.bits[cards] & used) != 0
            if bad.any():
                raise ValueError("Runout sampling limit reached")
            boards[:, j] = cards
            used |= self.bits[cards]
        cards = np.empty((size, n + 1, 7), dtype=np.int32)
        cards[:, 0, :2] = hole
        cards[:, 1:, :2] = self.combos[ids]
        cards[:, :, 2:] = boards[:, None, :]
        ranks = self._evaluate(cards.reshape(-1, 7)).reshape(size, n + 1)
        return ranks, ids, features

    def _payout(self, ranks, contributions, live, order=None):
        """Layer side pots; folded chips remain in the pot but cannot win."""
        size, n = contributions.shape
        levels = np.sort(contributions, axis=1)
        payout = np.zeros((size, n))
        if order is None:
            order = np.arange(n)
        previous = np.zeros(size)
        for j in range(n):
            level = levels[:, j]
            eligible = live & (contributions >= level[:, None])
            # A unique unmatched contribution is returned even after folding.
            contributors = contributions >= level[:, None]
            eligible = np.where((contributors.sum(axis=1) == 1)[:, None], contributors, eligible)
            best = np.max(np.where(eligible, ranks, -1), axis=1)
            winners = eligible & (ranks == best[:, None])
            amount = (level - previous) * contributors.sum(axis=1)
            divisor = np.maximum(1, winners.sum(axis=1))
            share = np.floor(amount / divisor)
            odd = amount - share * divisor
            payout += winners * share[:, None]
            ordered = winners[:, order]
            extras = ordered & (np.cumsum(ordered, axis=1) <= odd[:, None])
            payout[:, order] += extras
            previous = level
        return payout

    def _continue(self, s, seat, ids, features, target):
        price = min(s.stacks[seat], max(0, target - s.street_bets[seat]))
        if price == 0 or s.stacks[seat] == 0:
            return np.ones(len(ids))
        p, loose, aggr = self._profile(s.players[seat])
        regular, station, maniac, folder, random = p
        ratio = price / max(1, s.pot + target - s.street_bets[s.seat] + price)
        if not s.board:
            width = self._opening(seat, s.button, s.num_players) * .70
            width *= min(1.4, (3 * self.bb / max(price, self.bb)) ** .65)
            own_raises = [h[3] for h in s.history if h[0] == "preflop" and h[1] == seat and h[2] == "raise"]
            width = max(.032, width)
            if own_raises and max(own_raises) >= 6 * self.bb:
                width = max(.055, width)
            base = .015 + .97 * sigmoid((width - self.pct[ids]) / .016)
        else:
            quality, draw = features
            threshold = .47 + .58 * ratio + .035 * max(0, s.players_in_hand - 2)
            base = .02 + .94 * sigmoid((quality[ids] + .7 * draw[ids] - threshold) / .085)
        # Frequent folders/callers/shovers are behaviour models, never identities.
        return np.clip(regular * base + station * .995 + maniac * .98
                       + folder * .004 + random * .56, .002, .999)

    def _search(self, s, opponents, hole, board, deadline):
        samples = 640 if not board else 768
        if s.clock_ms < 5000 or self.mean_ms > 25:
            samples = 320
        ranks, ids, features = self._worlds(s, opponents, hole, board, samples, deadline)
        size = len(ranks)
        seats = [s.seat] + opponents
        # Include folded seats to account for their dead money in every pot.
        rest = [i for i in range(s.num_players) if i not in seats]
        seats += rest
        payout_order = np.argsort([(i - s.button - 1) % s.num_players for i in seats])
        ranks = np.column_stack((ranks, np.full((size, len(rest)), -1)))
        base_contrib = np.array([self.stack - s.stacks[i] for i in seats], dtype=float)
        live = np.zeros((size, len(seats)), dtype=bool)
        live[:, :1 + len(opponents)] = True
        mybet = s.street_bets[s.seat]
        call = min(s.to_call, s.my_stack)
        targets = [mybet + call]
        can_raise = s.can_raise and s.min_raise_to <= s.max_raise_to
        if can_raise:
            pot_after_call = s.pot + call
            sizes = (.40, .75, 1.15)
            for fraction in sizes:
                target = int(round(mybet + call + fraction * pot_after_call))
                targets.append(max(s.min_raise_to, min(s.max_raise_to, target)))
            premium = not board and self.pct[self.lookup[hole[0], hole[1]]] < .04
            if s.max_raise_to - mybet <= 2.5 * pot_after_call or premium:
                targets.append(s.max_raise_to)
            elif all(self._profile(s.players[o])[0][1] > .70 for o in opponents):
                targets.append(s.max_raise_to)
        targets = sorted(set(targets))
        uniforms = self.rng.random((size, len(opponents)))
        remaining = max(0, self.num_hands - self.completed - 1)
        placement = remaining <= 6 and self.completed > 0
        scores = np.array([self.totals.get(s.players[i], 0) for i in seats])
        std = np.array([math.sqrt((self.squares.get(s.players[i], 0) + 36000)
                                  / (self.completed + 10)) for i in seats])
        sigma = np.maximum(4.0, np.sqrt(remaining * (std[0] ** 2 + std[1:] ** 2)))
        in_position = (s.seat - s.button - 1) % s.num_players == max(
            (i - s.button - 1) % s.num_players for i in [s.seat] + opponents)

        def objective(payout, contrib, cost, continuing, raised):
            gain = payout[:, 0] - cost
            if placement:
                delta = payout - contrib
                difference = scores[0] + delta[:, 0, None] - scores[None, 1:] - delta[:, 1:]
                if remaining == 0:
                    return float(((difference > 0) + .5 * (difference == 0)).mean(axis=0).sum())
                return float(sigmoid(1.7 * difference / sigma).mean(axis=0).sum())
            value = float(gain.mean())
            if len(board) < 5 and cost < s.my_stack and continuing:
                eq = float((payout[:, 0] > 0).mean())
                realization = (.96 if in_position else .91) - .025 * max(0, len(opponents) - 1)
                realization = min(1.0, realization + .05 * eq)
                value -= (1 - realization) * float(payout[:, 0].mean())
            if raised:
                # Guard against errors in a one-step response model and reraises.
                value -= .018 * cost + .35 * float(gain.std()) / math.sqrt(size)
            return value

        best_target = targets[0]
        best = -float("inf")
        if call:
            folded = live.copy()
            folded[:, 0] = False
            contrib = np.tile(base_contrib, (size, 1))
            payout = self._payout(ranks, contrib, folded, payout_order)
            best = objective(payout, contrib, 0, False, False) if placement else 0.0
            best_target = None
        for target in targets:
            raised = target > mybet + call
            if raised and time.perf_counter() > deadline:
                break
            cost = target - mybet
            contrib = np.tile(base_contrib, (size, 1))
            contrib[:, 0] += cost
            active = live.copy()
            for j, seat in enumerate(opponents):
                price = min(s.stacks[seat], max(0, target - s.street_bets[seat]))
                if raised:
                    active[:, j + 1] = uniforms[:, j] < self._continue(s, seat, ids[:, j], features, target)
                elif price and not board and s.street_bets[seat] < max(s.street_bets):
                    active[:, j + 1] = uniforms[:, j] < self._continue(s, seat, ids[:, j], features, target)
                contrib[:, j + 1] += price * active[:, j + 1]
            payout = self._payout(ranks, contrib, active, payout_order)
            continuing = any(s.stacks[o] > max(0, target - s.street_bets[o]) for o in opponents)
            value = objective(payout, contrib, cost, continuing, raised)
            if value > best + (0.002 if placement else .08):
                best, best_target = value, target
        if best_target is None:
            return s.fold()
        if best_target <= mybet + call:
            return s.call() if call else s.check()
        return self._raise(s, best_target)

    def _raise(self, s, amount):
        if s.can_raise and s.min_raise_to <= s.max_raise_to:
            return s.raise_to(int(max(s.min_raise_to, min(s.max_raise_to, round(amount)))))
        return s.check() if s.to_call == 0 else s.call()

    def _fast(self, s):
        ranks = sorted(("23456789TJQKA".index(c[0]) + 2 for c in s.hole), reverse=True)
        if not s.board:
            premium = ranks[0] == ranks[1] and ranks[0] >= 12
            if premium:
                return self._raise(s, s.max_raise_to)
            if s.to_call == 0:
                return s.check()
            if ranks[0] >= 13 and ranks[1] >= 11 and s.to_call <= 3 * self.bb:
                return s.call()
            return s.fold()
        if s.to_call == 0:
            return s.check()
        if self.ready:
            value = int(self._evaluate(np.array([[card(c) for c in s.hole + s.board]]))[0])
            if value >> 20 >= 6 or (value >> 20 >= 3 and s.to_call <= .4 * s.pot):
                return s.call()
        return s.fold()

    def _decide(self, s, start):
        if s.clock_ms < 1200:
            return self._fast(s)
        if not self.ready:
            self._init_tables()
        if self.hand_key != s.hand:
            self.hand_key = s.hand
            self.cache = {}
        hole, board = [card(c) for c in s.hole], [card(c) for c in s.board]
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        if not opponents:
            return s.check() if s.to_call == 0 else s.call()
        if not board:
            pct = float(self.pct[self.lookup[hole[0], hole[1]]])
            highbet = max(s.street_bets)
            if highbet <= self.bb:
                width = self._opening(s.seat, s.button, s.num_players)
                profiles = [self._profile(s.players[o])[0] for o in opponents]
                folds = sum(p[3] for p in profiles) / len(profiles)
                maniac = max(p[2] for p in profiles)
                limpers = sum(h[0] == "preflop" and h[2] == "call" for h in s.history)
                width = min(.90, width + .35 * folds)
                if maniac > .65:
                    # Do not spend an open-raise on a hand that cannot face a shove.
                    width = min(width, .30)
                if pct < width:
                    size = self.bb * (2.5 + limpers + .5 * ((s.seat - s.button) % s.num_players == 1))
                    return self._raise(s, size)
                if s.to_call == 0:
                    return s.check()
                pair = hole[0] // 4 == hole[1] // 4
                suited = hole[0] % 4 == hole[1] % 4
                if limpers >= 2 and maniac < .25 and (pair or (suited and pct < .55)):
                    return s.call()
                return s.fold()
            # Avoid simulations for clearly dominated hands facing real aggression.
            broad = max(self._profile(s.players[o])[0][2] + self._profile(s.players[o])[0][4] for o in opponents)
            if pct > .65 and s.to_call > self.bb and broad < .35:
                return s.fold()
            if broad < .35:
                # Guard the one-step model against implausible deep-stack
                # bluff wars; already committed chips are not a reason to call.
                if highbet >= 20 * self.bb and pct > .06 and s.to_call > .20 * s.pot:
                    return s.fold()
                if highbet >= 6 * self.bb and pct > .20 and s.to_call > 3 * self.bb:
                    return s.fold()
        budget = .024 if s.clock_ms > 5000 else .010
        return self._search(s, opponents, hole, board, start + budget)

    def act(self, state):
        start = time.perf_counter()
        try:
            result = self._decide(state, start)
            self.mean_ms = .95 * self.mean_ms + .05 * (time.perf_counter() - start) * 1000
            return result
        except Exception:
            self.errors += 1
            return state.check() if state.to_call == 0 else state.fold()
