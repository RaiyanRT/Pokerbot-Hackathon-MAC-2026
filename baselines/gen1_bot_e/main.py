"""
GLM 5.3 Flagship
Duplicate-deal no-limit hold'em tournament bot (100 hands/game, fresh 200-chip
stacks and 1/2 blinds every hand, scored on net chips then placement points).

Strategy: a robust tight-aggressive core driven by hand equity. Preflop it
plays Chen-score thresholds with position awareness (wider on the button and
steal seats, 3-betting premiums), and switches to Monte-Carlo equity against
random ranges when facing big raises or shoves from loose opponents. Postflop
it uses a self-contained 5-7 card evaluator plus a time-budgeted, chunked,
cached Monte-Carlo equity simulation versus random opponent holdings: it bets
for value when equity clears an opponent-adjusted threshold, semi-bluffs
selectively (more vs tight folders, never vs calling stations), raises strong
hands for value, and calls when range-discounted equity beats pot odds.
Per-game anonymous opponent statistics (VPIP, preflop raise rate, postflop
aggression/folds/calls, all-ins, showdown strength) gathered in the observer
hooks tune every threshold, and a late-game standings check tips between
protecting a lead and chasing the player above. Every path is exception-
guarded with a safe legal fallback, and the simulation budget shrinks as the
chess clock runs down.
"""

import math
import random
import time

from macpoker import Bot

_RANKS = "23456789TJQKA"
_SUITS = "shdc"
_AGGR = ("bet", "raise", "allin", "all_in")
_STRAIGHT = None  # lazily built 13-bit rank-mask -> straight high card table


def _init_tables():
    global _STRAIGHT
    if _STRAIGHT is not None:
        return
    t = [-1] * 8192
    for m in range(8192):
        h = -1
        for hi in range(12, 3, -1):
            if (m >> (hi - 4)) & 31 == 31:
                h = hi
                break
        if h < 0 and (m & 0x100F) == 0x100F:  # wheel A-2-3-4-5
            h = 3
        t[m] = h
    _STRAIGHT = t


def _cards(lst):
    """Convert card strings like 'As' to ints (rank*4+suit); None on failure."""
    out = []
    try:
        for cs in lst:
            out.append(_RANKS.index(cs[0]) * 4 + _SUITS.index(cs[1]))
        return out
    except Exception:
        return None


def _g(obj, key, default=None):
    try:
        v = obj[key]
        if v is not None:
            return v
    except Exception:
        pass
    try:
        return getattr(obj, key, default)
    except Exception:
        return default


def _keyget(d, k):
    """Fetch seat-keyed value from a players map that may use int/str keys."""
    try:
        if isinstance(d, (list, tuple)):
            if isinstance(k, int) and 0 <= k < len(d):
                return d[k]
            return None
    except Exception:
        pass
    try:
        v = d.get(k)
        if v is not None:
            return v
    except Exception:
        pass
    try:
        v = d.get(int(k))
        if v is not None:
            return v
    except Exception:
        pass
    try:
        v = d.get(str(k))
        if v is not None:
            return v
    except Exception:
        pass
    return None


def _row(r):
    """Normalise a history row to (street, seat, kind, amount) or None."""
    try:
        if isinstance(r, (list, tuple)):
            if len(r) >= 3:
                return (r[0], r[1], r[2], r[3] if len(r) > 3 else None)
            return None
        if isinstance(r, dict):
            kind = r.get("action", r.get("kind"))
            return (r.get("street"), r.get("seat"), kind, r.get("amount"))
    except Exception:
        return None
    return None


_CHEN = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0, 8: 5.0}


def _chen(c1, c2):
    """Chen preflop hand score (integer)."""
    try:
        r1 = c1 >> 2
        r2 = c2 >> 2
        if r2 > r1:
            r1, r2 = r2, r1
        if r1 == r2:
            return int(math.ceil(max(5.0, 2.0 * _CHEN.get(r1, (r1 + 2) / 2.0))))
        s = _CHEN.get(r1, (r1 + 2) / 2.0)
        if (c1 & 3) == (c2 & 3):
            s += 2.0
        gap = r1 - r2 - 1
        if gap == 0:
            if r1 < 10:
                s += 1.0
        elif gap == 1:
            s -= 1.0
        elif gap == 2:
            s -= 2.0
        elif gap == 3:
            s -= 4.0
        else:
            s -= 5.0
        return int(math.ceil(s))
    except Exception:
        return 5


def _evaluate(cards):
    """5-7 card hand value: category in the top bits, kickers packed below."""
    rc = [0] * 13
    sc = [0] * 4
    srm = [0] * 4
    rm = 0
    for c in cards:
        r = c >> 2
        s = c & 3
        rc[r] += 1
        sc[s] += 1
        b = 1 << r
        rm |= b
        srm[s] |= b
    for s in range(4):
        if sc[s] >= 5:
            fm = srm[s]
            sh = _STRAIGHT[fm]
            if sh >= 0:
                return (8 << 20) | (sh << 16)  # straight flush
            acc = 0
            k = 0
            for r in range(12, -1, -1):
                if (fm >> r) & 1:
                    acc = (acc << 4) | r
                    k += 1
                    if k == 5:
                        break
            return (5 << 20) | acc  # flush
    quads = -1
    trips = []
    pairs = []
    singles = []
    for r in range(12, -1, -1):
        cnt = rc[r]
        if cnt == 4:
            quads = r
        elif cnt == 3:
            trips.append(r)
        elif cnt == 2:
            pairs.append(r)
        elif cnt == 1:
            singles.append(r)
    if quads >= 0:
        ks = trips + pairs + singles
        kick = max(ks) if ks else 0
        return (7 << 20) | (quads << 16) | (kick << 12)
    if trips and (pairs or len(trips) > 1):
        pr = pairs[0] if pairs else trips[1]
        return (6 << 20) | (trips[0] << 16) | (pr << 12)
    sh = _STRAIGHT[rm]
    if sh >= 0:
        return (4 << 20) | (sh << 16)
    if trips:
        ks = sorted(pairs + singles, reverse=True)
        k1 = ks[0] if ks else 0
        k2 = ks[1] if len(ks) > 1 else 0
        return (3 << 20) | (trips[0] << 12) | (k1 << 8) | (k2 << 4)
    if len(pairs) >= 2:
        ks = pairs[2:] + singles
        kick = max(ks) if ks else 0
        return (2 << 20) | (pairs[0] << 12) | (pairs[1] << 8) | (kick << 4)
    if len(pairs) == 1:
        k = singles[:3]
        while len(k) < 3:
            k.append(0)
        return (1 << 20) | (pairs[0] << 12) | (k[0] << 8) | (k[1] << 4) | k[2]
    acc = 0
    for r in singles[:5]:
        acc = (acc << 4) | r
    return acc


class MyBot(Bot):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._stats = {}    # player id -> counters (persists for the game)
        self._totals = {}   # player id -> cumulative net chips this game
        self._eq = {}       # (hole, board, opps) -> monte-carlo equity cache
        self._nh = 100
        self._me = None

    # ---------------- observer hooks ----------------

    def on_match_start(self, info):
        try:
            _init_tables()
            try:
                v = _g(info, "num_hands", None)
                if v:
                    self._nh = max(10, int(v))
            except Exception:
                self._nh = 100
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            players = _g(info, "players", None)
            if isinstance(players, dict):
                for pid in players.values():
                    self._stat(pid)["dealt"] += 1
            elif isinstance(players, (list, tuple)):
                for pid in players:
                    if pid is not None:
                        self._stat(pid)["dealt"] += 1
        except Exception:
            pass

    def on_action(self, event):
        try:
            players = _g(event, "players", None)
            if not players:
                return
            seat = _g(event, "seat", None)
            if seat is None:
                return
            pid = _keyget(players, seat)
            if pid is None:
                return
            act = _g(event, "action", None)
            street = _g(event, "street", "")
            amt = _g(event, "amount", None)
            st = self._stat(pid)
            if street == "preflop":
                if act == "call":
                    if not (isinstance(amt, (int, float)) and amt <= 0.5):
                        st["vpip"] += 1
                elif act in _AGGR:
                    # skip blind posts that look like tiny preflop "bets"
                    if act == "bet" and isinstance(amt, (int, float)) and amt <= 2.5:
                        return
                    st["vpip"] += 1
                    st["pfr"] += 1
                    if act in ("allin", "all_in"):
                        st["allin"] += 1
            else:
                if act in _AGGR:
                    st["post"] += 1
                    st["agg"] += 1
                    if act in ("allin", "all_in"):
                        st["allin"] += 1
                elif act == "call":
                    st["post"] += 1
                    st["call"] += 1
                elif act == "check":
                    st["post"] += 1
                elif act == "fold":
                    st["post"] += 1
                    st["fold"] += 1
        except Exception:
            pass

    def on_street(self, event):
        try:
            pass
        except Exception:
            pass

    def on_hand_end(self, info):
        try:
            players = _g(info, "players", None)
            deltas = _g(info, "deltas", None)
            items = []
            if isinstance(deltas, dict):
                items = list(deltas.items())
            elif isinstance(deltas, (list, tuple)):
                items = list(enumerate(deltas))
            for s, d in items:
                if not isinstance(d, (int, float)):
                    continue
                pid = _keyget(players, s) if players else None
                if pid is None:
                    continue
                self._totals[pid] = self._totals.get(pid, 0) + d
            rev = _g(info, "revealed", None)
            if isinstance(rev, dict) and players:
                for s, cards in rev.items():
                    try:
                        pid = _keyget(players, s)
                        if pid is None or not cards or len(cards) < 2:
                            continue
                        cc = _cards(cards)
                        if not cc or len(cc) < 2:
                            continue
                        st = self._stat(pid)
                        st["sd"] += 1
                        st["sdchen"] += _chen(cc[0], cc[1])
                    except Exception:
                        pass
        except Exception:
            pass

    def on_match_end(self, info):
        try:
            pass
        except Exception:
            pass

    # ---------------- main entry ----------------

    def act(self, state):
        r = None
        try:
            try:
                cm = int(state.clock_ms)
            except Exception:
                cm = 1000000
            if cm < 1500:  # clock nearly gone: instant safe action
                try:
                    if int(state.to_call) == 0:
                        return state.check()
                except Exception:
                    pass
                try:
                    return state.fold()
                except Exception:
                    pass
            r = self._act(state)
        except Exception:
            r = None
        if r is None:
            try:
                if int(state.to_call) == 0:
                    return state.check()
            except Exception:
                pass
            try:
                return state.fold()
            except Exception:
                pass
            try:
                return state.call()
            except Exception:
                pass
        return r

    def _act(self, state):
        _init_tables()
        try:
            self._me = state.player
        except Exception:
            pass
        n = int(state.num_players)
        tc = int(state.to_call)
        pot = int(state.pot)
        seat = int(state.seat)
        try:
            my_bet = int(state.street_bets[seat])
        except Exception:
            my_bet = 0
        stack_b = int(state.my_stack)
        hole = _cards(state.hole)
        if not hole or len(hole) != 2:
            return state.check() if tc == 0 else state.fold()
        street = state.street
        try:
            nb = len(state.board)
        except Exception:
            nb = 0
        if street == "preflop" or nb < 3:
            return self._preflop(state, hole, tc, pot, seat, my_bet, stack_b, n)
        return self._postflop(state, hole, tc, pot, seat, stack_b, street)

    # ---------------- preflop ----------------

    def _preflop(self, state, hole, tc, pot, seat, my_bet, stack_b, n):
        C = _chen(hole[0], hole[1])
        try:
            pos = (seat - int(state.button)) % n
        except Exception:
            pos = 0
        high = tc + my_bet  # current highest preflop bet
        n_r = self._pf_raise_count(state)
        limpers = self._pf_limp_count(state)
        eg = self._endgame(state)
        cost = min(tc, stack_b)
        req = cost / float(pot + cost) if (pot + cost) > 0 else 1.0
        if high > 2:
            prof = self._profile(self._last_aggressor_id(state))
            big = (tc >= 40) or (cost >= stack_b) or (tc >= stack_b * 0.45)
            if big:
                return self._call_big_pf(state, hole, C, tc, pot, stack_b, n_r, req, prof)
            loose_r = prof is not None and (prof["pfr"] > 0.5 or prof["vpip"] > 0.6)
            t3 = 10 if loose_r else 12
            if n_r <= 1:
                if C >= t3:
                    try:
                        can_r = bool(state.can_raise)
                        hi = int(state.max_raise_to)
                    except Exception:
                        can_r, hi = False, 0
                    if can_r and 3 * high <= hi:
                        a = self._mk_raise(state, 3 * high)
                        if a is not None:
                            return a
                    if C >= 15 and can_r:
                        a = self._mk_raise(state, hi)
                        if a is not None:
                            return a
                    return state.call()
                d = 1.5 if loose_r else 0.0
                if eg > 0:
                    d -= 0.5
                if eg < 0:
                    d += 1.0
                if tc <= 6 and C >= 6.5 - d:
                    return state.call()
                if tc <= 10 and C >= 7.5 - d:
                    return state.call()
                if tc <= 20 and C >= 9.0 - d:
                    return state.call()
                if tc <= 40 and C >= 10.5 - d:
                    return state.call()
                if req <= 0.10 and C >= 5.5 - d:
                    return state.call()
                return state.fold()
            # two or more raises
            try:
                can_r = bool(state.can_raise)
                hi = int(state.max_raise_to)
            except Exception:
                can_r, hi = False, 0
            if C >= 14 and can_r and 2.5 * high <= hi:
                a = self._mk_raise(state, int(2.5 * high))
                if a is not None:
                    return a
            if C >= 16 and can_r:
                a = self._mk_raise(state, hi)
                if a is not None:
                    return a
            if C >= 11:
                return state.call()
            if loose_r and C >= 9 and tc <= 20:
                return state.call()
            return state.fold()
        # ---- unraised pot ----
        t = 9.0
        if pos == 0:
            t = 7.0
        elif pos == n - 1:
            t = 7.5 if n <= 5 else 8.0
        elif pos in (1, 2):
            t = 8.5
        if limpers == 0 and pos in (0, 1, n - 1):
            t -= 1.0
        if eg > 0:
            t -= 0.5
        if eg < 0:
            t += 1.5
        try:
            can_r = bool(state.can_raise)
        except Exception:
            can_r = False
        if C >= t and can_r and stack_b > 6:
            size = 6 + 2 * min(limpers, 4)
            if limpers >= 2:
                size = 7 + 2 * min(limpers, 4)
            a = self._mk_raise(state, size)
            if a is not None:
                return a
            if C >= 11:
                try:
                    a = self._mk_raise(state, int(state.max_raise_to))
                    if a is not None:
                        return a
                except Exception:
                    pass
            return state.call() if tc > 0 else state.check()
        if tc == 0:
            return state.check()
        if tc <= 1:
            if C >= 4.5:
                return state.call()
            return state.fold()
        if tc <= 2:
            if limpers >= 1 and ((pos == 0 and C >= 5.0) or C >= 6.5):
                return state.call()
            if limpers >= 2 and C >= 5.0:
                return state.call()
            if eg > 0 and C >= 6.0:
                return state.call()
            return state.fold()
        return state.fold()

    def _call_big_pf(self, state, hole, C, tc, pot, stack_b, n_r, req, prof):
        # premium: shove over a big bet that isn't all-in
        try:
            if C >= 15 and tc < stack_b and bool(state.can_raise):
                a = self._mk_raise(state, int(state.max_raise_to))
                if a is not None:
                    return a
        except Exception:
            pass
        known_loose = prof is not None and (
            prof["allin"] >= 2 or prof["vpip"] > 0.45 or prof["pfr"] > 0.35)
        if not known_loose:
            # unknown or tight shover: conservative Chen cutoffs
            cut = 10 if (n_r <= 1 and req <= 0.52) else 12
            if C >= cut and req <= 0.56:
                return state.call()
            return state.fold()
        # loose/maniaic: random-range Monte Carlo is the right model
        try:
            cm = int(state.clock_ms)
        except Exception:
            cm = 1000000
        try:
            opps = max(1, min(5, int(state.players_in_hand) - 1))
        except Exception:
            opps = 1
        key = (min(hole), max(hole))
        if cm > 6000:
            E = self._equity(key, (), opps, 22, 520)
        elif cm > 3000:
            E = self._equity(key, (), opps, 10, 220)
        else:
            E = 0.40 + 0.022 * C
            if opps > 1:
                E = 0.5 + (E - 0.5) / (1.0 + 0.55 * (opps - 1))
        if E >= req + 0.02:
            return state.call()
        return state.fold()

    # ---------------- postflop ----------------

    def _postflop(self, state, hole, tc, pot, seat, stack_b, street):
        board = _cards(state.board)
        if not board or len(board) < 3:
            return state.check() if tc == 0 else state.fold()
        try:
            opps = max(1, min(5, int(state.players_in_hand) - 1))
        except Exception:
            opps = 1
        ids = self._inhand_opp_ids(state)
        profiles = []
        for pid in ids:
            p = self._profile(pid)
            if p:
                profiles.append(p)
        try:
            cm = int(state.clock_ms)
        except Exception:
            cm = 1000000
        if cm > 20000:
            budget, cap = 45, 900
        elif cm > 8000:
            budget, cap = 28, 550
        elif cm > 3000:
            budget, cap = 12, 240
        else:
            budget, cap = 0, 0
        if budget > 0:
            E = self._equity((min(hole), max(hole)), tuple(board), opps, budget, cap)
        else:
            E = self._quick_equity(hole, board, opps)
        E = min(1.0, max(0.0, E))
        eg = self._endgame(state)
        if tc == 0:
            # ---- we may check or bet ----
            if stack_b <= 0 or not state.can_raise:
                return state.check()
            vt = 0.60 + 0.035 * (opps - 1)
            if street == "river":
                vt -= 0.02
            loose = any((p["vpip"] > 0.5 or p["call"] > 0.45 or p["sdweak"]) for p in profiles)
            tight = bool(profiles) and all((p["fold"] > 0.40 or p["vpip"] < 0.30) for p in profiles)
            if loose:
                vt -= 0.04
            if tight:
                vt += 0.02
            if eg < 0:
                vt += 0.03
            elif eg > 0:
                vt -= 0.02
            if E >= vt:
                frac = 0.48 + 0.40 * min(1.0, (E - vt) / 0.20)
                if opps >= 3:
                    frac += 0.10
                frac *= 0.92 + 0.16 * random.random()
                a = self._mk_raise(state, int(round(pot * frac)))
                if a is not None:
                    return a
                return state.check()
            # selective bluff / semi-bluff
            freq = 0.14
            if tight:
                freq = 0.32
            if loose:
                freq = 0.03
            try:
                if seat == int(state.button):
                    freq += 0.06
            except Exception:
                pass
            if street == "flop" and self._i_raised_pf(state):
                freq += 0.10
            if eg < 0:
                freq *= 0.3
            elif eg > 0:
                freq += 0.06
            min_e = 0.34 if street != "river" else 0.44
            if opps <= 2 and E >= min_e and random.random() < freq:
                a = self._mk_raise(state, int(round(pot * 0.55)))
                if a is not None:
                    return a
            return state.check()
        # ---- facing a bet ----
        cost = min(tc, stack_b)
        pot_after = pot + cost
        req = cost / float(pot_after) if pot_after > 0 else 1.0
        prof = self._profile(self._last_aggressor_id(state))
        if prof is None and profiles:
            prof = profiles[0]
        bet_frac = cost / float(max(1, pot - cost))
        disc = 0.03 + 0.09 * min(1.0, bet_frac)
        if prof is not None:
            if prof["vpip"] > 0.5 or prof["agg"] > 0.45 or prof["allin"] >= 2 or prof["sdweak"]:
                disc *= 0.45   # loose/aggressive: random model is close
            elif prof["vpip"] < 0.25 or prof["agg"] < 0.10:
                disc *= 1.5    # tight/passive: their bets mean strength
        if opps >= 3:
            disc += 0.03
        if street == "river":
            disc += 0.02
        if self._street_aggr_count(state) >= 2:
            disc += 0.05
        if eg < 0:
            disc += 0.02
        E_eff = E - disc
        my_rs = self._my_raises_street(state)
        try:
            can_r = bool(state.can_raise)
            hi = int(state.max_raise_to)
        except Exception:
            can_r, hi = False, 0
        if E_eff >= req + 0.14 and can_r and cost < stack_b and my_rs < 2:
            # vs a maniac we've already raised once: just call and let them spew
            if prof is not None and prof["agg"] > 0.45 and E_eff < 0.85 and my_rs >= 1:
                return state.call()
            target = int(round((pot - cost) + 3 * cost))
            if target <= hi or E_eff >= 0.82:
                a = self._mk_raise(state, target)
                if a is not None:
                    return a
            return state.call()
        margin = 0.025 + (0.02 if street == "river" else 0.0)
        if prof is not None and (prof["agg"] > 0.45 or prof["vpip"] > 0.55):
            margin = 0.0
        if eg > 0:
            margin -= 0.01
        if E_eff >= req + margin:
            return state.call()
        if req <= 0.13 and E_eff >= req - 0.03 and street != "river":
            return state.call()
        if tc <= 2 and req <= 0.25:
            return state.call()
        return state.fold()

    # ---------------- equity ----------------

    def _equity(self, hole_t, board_t, opps, budget_ms, max_iters):
        key = (hole_t, board_t, opps)
        v = self._eq.get(key)
        if v is not None:
            return v
        e = 0.5
        try:
            used = set(hole_t)
            used.update(board_t)
            deck = [c for c in range(52) if c not in used]
            need = 2 * opps + (5 - len(board_t))
            if (need <= 0 or need > len(deck) or len(board_t) > 5
                    or len(hole_t) != 2):
                return 0.5
            hole = list(hole_t)
            board = list(board_t)
            sample = random.sample
            ev = _evaluate
            wins = 0.0
            it = 0
            deadline = time.perf_counter() + budget_ms / 1000.0
            while it < max_iters:
                for _ in range(40):
                    drawn = sample(deck, need)
                    bo = board + drawn[2 * opps:]
                    my = ev(hole + bo)
                    best = True
                    tied = 1
                    for o in range(opps):
                        ov = ev([drawn[2 * o], drawn[2 * o + 1]] + bo)
                        if ov > my:
                            best = False
                            break
                        if ov == my:
                            tied += 1
                    if best:
                        wins += 1.0 / tied
                    it += 1
                if time.perf_counter() >= deadline:
                    break
            if it > 0:
                e = wins / it
        except Exception:
            e = 0.5
        if len(self._eq) > 2500:
            self._eq.clear()
        self._eq[key] = e
        return e

    def _quick_equity(self, hole, board, opps):
        """Cheap made-hand-only estimate for low-clock situations."""
        try:
            v = _evaluate(hole + board)
            cat = v >> 20
            if cat >= 8:
                e = 0.97
            elif cat == 7:
                e = 0.94
            elif cat == 6:
                e = 0.90
            elif cat == 5:
                e = 0.85
            elif cat == 4:
                e = 0.80
            elif cat == 3:
                e = 0.72
            elif cat == 2:
                e = 0.60
            elif cat == 1:
                pr = (v >> 12) & 15
                e = 0.28 + 0.02 * pr
                if len(board) == 5:
                    e += 0.04
            else:
                e = 0.20
            if opps > 1:
                e = 0.5 + (e - 0.5) / (1.0 + 0.55 * (opps - 1))
            return e
        except Exception:
            return 0.4

    # ---------------- history parsing ----------------

    def _rows(self, state):
        try:
            return list(state.history)
        except Exception:
            return []

    def _pf_raise_count(self, state):
        c = 0
        for r in self._rows(state):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st == "preflop" and kind in _AGGR:
                if kind == "bet" and isinstance(amt, (int, float)) and amt <= 2.5:
                    continue
                c += 1
        return c

    def _pf_limp_count(self, state):
        c = 0
        for r in self._rows(state):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st == "preflop" and kind == "call":
                if isinstance(amt, (int, float)) and amt <= 0.5:
                    continue
                c += 1
        return c

    def _my_raises_street(self, state):
        c = 0
        for r in self._rows(state):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st == state.street and kind in _AGGR:
                try:
                    if int(seat) == int(state.seat):
                        c += 1
                except Exception:
                    pass
        return c

    def _street_aggr_count(self, state):
        c = 0
        for r in self._rows(state):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st == state.street and kind in _AGGR:
                if st == "preflop" and kind == "bet" and isinstance(amt, (int, float)) and amt <= 2.5:
                    continue
                c += 1
        return c

    def _i_raised_pf(self, state):
        for r in self._rows(state):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st == "preflop" and kind in _AGGR:
                if kind == "bet" and isinstance(amt, (int, float)) and amt <= 2.5:
                    continue
                try:
                    if int(seat) == int(state.seat):
                        return True
                except Exception:
                    pass
        return False

    def _last_aggressor_id(self, state):
        for r in reversed(self._rows(state)):
            p = _row(r)
            if p is None:
                continue
            st, seat, kind, amt = p
            if st != state.street or kind not in _AGGR:
                continue
            if st == "preflop" and kind == "bet" and isinstance(amt, (int, float)) and amt <= 2.5:
                continue
            try:
                if int(seat) == int(state.seat):
                    return None
                return state.players[int(seat)]
            except Exception:
                return None
        return None

    # ---------------- opponents / meta ----------------

    def _inhand_opp_ids(self, state):
        ids = []
        try:
            fl = state.folded
            pl = state.players
            for s in range(int(state.num_players)):
                if s == int(state.seat):
                    continue
                if not fl[s]:
                    pid = pl[s]
                    if pid is not None:
                        ids.append(pid)
        except Exception:
            pass
        return ids

    def _stat(self, pid):
        st = self._stats.get(pid)
        if st is None:
            st = {"dealt": 0, "vpip": 0, "pfr": 0, "post": 0, "agg": 0,
                  "fold": 0, "call": 0, "allin": 0, "sd": 0, "sdchen": 0.0}
            self._stats[pid] = st
        return st

    def _lookup(self, d, pid):
        if pid is None:
            return None
        try:
            v = d.get(pid)
            if v is not None:
                return v
        except Exception:
            pass
        try:
            v = d.get(int(pid))
            if v is not None:
                return v
        except Exception:
            pass
        try:
            v = d.get(str(pid))
            if v is not None:
                return v
        except Exception:
            pass
        return None

    def _profile(self, pid):
        try:
            st = self._lookup(self._stats, pid)
            if not st or st["dealt"] < 8:
                return None
            dealt = float(st["dealt"])
            post = st["post"]
            p = {
                "vpip": st["vpip"] / dealt,
                "pfr": st["pfr"] / dealt,
                "agg": (st["agg"] / post) if post >= 6 else 0.25,
                "fold": (st["fold"] / post) if post >= 6 else 0.25,
                "call": (st["call"] / post) if post >= 6 else 0.30,
                "allin": st["allin"],
                "sdweak": False,
            }
            if st["sd"] >= 3:
                p["sdweak"] = (st["sdchen"] / st["sd"]) < 6.0
            return p
        except Exception:
            return None

    def _endgame(self, state):
        """-1 protect a big lead, +1 chase a close player above, 0 neutral."""
        try:
            if int(state.hand) < self._nh - 8:
                return 0
            me = state.player
            my = self._lookup(self._totals, me)
            if my is None:
                return 0
            vals = []
            for k, v in self._totals.items():
                try:
                    if int(k) == int(me):
                        continue
                except Exception:
                    if k == me:
                        continue
                vals.append(v)
            if not vals:
                return 0
            best = max(vals)
            rank = 1 + sum(1 for v in vals if v > my)
            if rank == 1 and (my - best) >= 40:
                return -1
            if rank >= 2 and (best - my) <= 60:
                return 1
            return 0
        except Exception:
            return 0

    def _mk_raise(self, state, target):
        """Legal clamped raise, or None if we cannot raise."""
        try:
            if not state.can_raise:
                return None
            lo = int(state.min_raise_to)
            hi = int(state.max_raise_to)
            if hi < lo:
                return None
            t = int(round(float(target)))
            if t < lo:
                t = lo
            if t > hi:
                t = hi
            return state.raise_to(t)
        except Exception:
            return None


bot = MyBot()