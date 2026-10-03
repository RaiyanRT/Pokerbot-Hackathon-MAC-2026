"""
Done by Deepseek V3
A tight-aggressive heuristic bot for no-limit Texas Hold'em. It uses the Chen formula for preflop hand selection, position-aware opening and calling, and a lightweight 7-card evaluator for postflop made-hand and draw strength. Opponent actions are tracked per player id to slightly adjust calling thresholds against aggressive opponents. Bet sizing is pot-relative, and the bot avoids large all-in calls without strong holdings. All decisions are wrapped in safe fallbacks.
"""

import random
from macpoker import Bot


class MyBot(Bot):
    def __init__(self):
        super().__init__()
        self.stats = {}
        self.hand_vpip = set()
        self.hand_pfr = set()

    # ------------------------------------------------------------------
    # Observer hooks
    # ------------------------------------------------------------------
    def on_match_start(self, info):
        try:
            self.stats = {}
            self.hand_vpip = set()
            self.hand_pfr = set()
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            self.hand_vpip = set()
            self.hand_pfr = set()
            players = info.get("players", [])
            for pid in players:
                if pid not in self.stats:
                    self.stats[pid] = {
                        "hands": 0,
                        "vpip": 0,
                        "pfr": 0,
                        "raises": 0,
                        "calls": 0,
                        "folds": 0,
                        "aggressive": 0,
                    }
                self.stats[pid]["hands"] += 1
        except Exception:
            pass

    def on_action(self, event):
        try:
            players = event.get("players")
            if not players:
                return
            seat = event.get("seat")
            if seat is None or seat >= len(players):
                return
            who = players[seat]
            action = event.get("action")
            street = event.get("street")

            if who not in self.stats:
                self.stats[who] = {
                    "hands": 0,
                    "vpip": 0,
                    "pfr": 0,
                    "raises": 0,
                    "calls": 0,
                    "folds": 0,
                    "aggressive": 0,
                }
            s = self.stats[who]

            if action == "call":
                s["calls"] += 1
            elif action in ("raise", "bet"):
                s["raises"] += 1
                s["aggressive"] += 1
            elif action == "fold":
                s["folds"] += 1

            if street == "preflop":
                if action in ("call", "raise", "bet"):
                    if who not in self.hand_vpip:
                        self.hand_vpip.add(who)
                        s["vpip"] += 1
                if action in ("raise", "bet"):
                    if who not in self.hand_pfr:
                        self.hand_pfr.add(who)
                        s["pfr"] += 1
        except Exception:
            pass

    def on_street(self, event):
        pass

    def on_hand_end(self, info):
        pass

    def on_match_end(self, info):
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def rank_val(self, card):
        r = card[0]
        if r == 'A':
            return 14
        if r == 'K':
            return 13
        if r == 'Q':
            return 12
        if r == 'J':
            return 11
        if r == 'T':
            return 10
        return int(r)

    def chen_score(self, hole):
        v1 = self.rank_val(hole[0])
        v2 = self.rank_val(hole[1])
        high = max(v1, v2)
        low = min(v1, v2)

        if high == 14:
            score = 10
        elif high == 13:
            score = 8
        elif high == 12:
            score = 7
        elif high == 11:
            score = 6
        else:
            score = high / 2.0

        if v1 == v2:
            score = max(5, score * 2)
        else:
            if hole[0][1] == hole[1][1]:
                score += 2
            gap = high - low - 1
            if gap == 1:
                score -= 1
            elif gap == 2:
                score -= 2
            elif gap == 3:
                score -= 4
            elif gap >= 4:
                score -= 5
            if gap <= 1 and high < 12:
                score += 1
        return score

    def position_score(self, offset, N):
        if offset == 0:
            return 5
        if offset == 1:
            return 2
        if offset == 2:
            return 3
        if offset == N - 1:
            return 4
        if offset == N - 2:
            return 3
        return 1

    def check_straight(self, ranks):
        unique = sorted(set(ranks), reverse=True)
        if 14 in unique:
            unique.append(1)
        unique = sorted(set(unique), reverse=True)
        for i in range(len(unique) - 4):
            if unique[i] - unique[i + 4] == 4:
                return unique[i]
        return None

    def evaluate(self, cards):
        rank_map = {
            '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
            '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14,
        }
        ranks = [rank_map[c[0]] for c in cards]
        suits = [c[1] for c in cards]

        suit_counts = {}
        for s in suits:
            suit_counts[s] = suit_counts.get(s, 0) + 1

        flush_suit = None
        for s, c in suit_counts.items():
            if c >= 5:
                flush_suit = s
                break

        if flush_suit:
            flush_ranks = sorted(
                [rank_map[c[0]] for c in cards if c[1] == flush_suit],
                reverse=True,
            )
            sf = self.check_straight(flush_ranks)
            if sf:
                return (8, sf)

        counts = {}
        for r in ranks:
            counts[r] = counts.get(r, 0) + 1

        for r, c in counts.items():
            if c == 4:
                kickers = sorted([x for x in ranks if x != r], reverse=True)
                return (7, (r, kickers[0] if kickers else 0))

        threes = sorted([r for r, c in counts.items() if c >= 3], reverse=True)
        pairs = sorted([r for r, c in counts.items() if c >= 2], reverse=True)

        if threes:
            for t in threes:
                for p in pairs:
                    if p != t:
                        return (6, (t, p))

        if flush_suit:
            flush_ranks = sorted(
                [rank_map[c[0]] for c in cards if c[1] == flush_suit],
                reverse=True,
            )
            return (5, tuple(flush_ranks[:5]))

        unique_ranks = sorted(set(ranks), reverse=True)
        st = self.check_straight(unique_ranks)
        if st:
            return (4, st)

        if threes:
            t = threes[0]
            kickers = sorted([x for x in ranks if x != t], reverse=True)
            return (3, (t, tuple(kickers[:2])))

        if len(pairs) >= 2:
            p1, p2 = pairs[0], pairs[1]
            kickers = sorted([x for x in ranks if x != p1 and x != p2], reverse=True)
            return (2, (p1, p2, kickers[0] if kickers else 0))

        if pairs:
            p = pairs[0]
            kickers = sorted([x for x in ranks if x != p], reverse=True)
            return (1, (p, tuple(kickers[:3])))

        return (0, tuple(sorted(ranks, reverse=True)[:5]))

    def has_straight(self, ranks):
        unique = sorted(set(ranks), reverse=True)
        if 14 in unique:
            unique.append(1)
        unique = sorted(set(unique), reverse=True)
        for i in range(len(unique) - 4):
            if unique[i] - unique[i + 4] == 4:
                return True
        return False

    def hand_strength(self, cat, tie, hole, board):
        if cat >= 8:
            return 1.0
        if cat == 7:
            return 0.98
        if cat == 6:
            return 0.95
        if cat == 5:
            return 0.85
        if cat == 4:
            return 0.8
        if cat == 3:
            return 0.7
        if cat == 2:
            return 0.6
        if cat == 1:
            p = tie[0]
            board_ranks = [self.rank_val(c) for c in board]
            if board_ranks:
                if p >= max(board_ranks):
                    return 0.5
                return 0.3
            return 0.4

        strength = 0.1
        hole_ranks = [self.rank_val(c) for c in hole]
        board_ranks = [self.rank_val(c) for c in board]
        if board_ranks and all(r > max(board_ranks) for r in hole_ranks):
            strength += 0.1

        all_cards = hole + board
        suit_counts = {}
        for c in all_cards:
            s = c[1]
            suit_counts[s] = suit_counts.get(s, 0) + 1
        for s, c in suit_counts.items():
            if c == 4 and any(card[1] == s for card in hole):
                strength += 0.15
                break

        ranks = sorted(set(self.rank_val(c) for c in all_cards))
        if len(ranks) >= 4:
            for r in range(2, 15):
                if r not in ranks and self.has_straight(ranks + [r]):
                    strength += 0.1
                    break
        return strength

    def make_raise(self, state, amount):
        if not state.can_raise:
            if state.to_call == 0:
                return state.check()
            return state.call()
        n = max(state.min_raise_to, min(state.max_raise_to, int(amount)))
        return state.raise_to(n)

    def current_aggressor(self, state):
        for entry in reversed(state.history):
            street, seat, kind, amount = entry
            if street == state.street and seat != state.seat and kind in ("raise", "bet"):
                if seat < len(state.players):
                    return state.players[seat]
        return None

    def safe(self, state):
        try:
            if state.to_call == 0:
                return state.check()
            return state.fold()
        except Exception:
            return state.fold()

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------
    def preflop(self, state):
        hole = state.hole
        if len(hole) != 2:
            return self.safe(state)

        chen = self.chen_score(hole)
        N = state.num_players
        offset = (state.seat - state.button) % N
        pos = self.position_score(offset, N)
        to_call = state.to_call
        pot = state.pot

        if to_call == 0:
            if chen >= 8 and state.can_raise:
                return self.make_raise(state, max(state.min_raise_to, 6))
            elif chen >= 6 and pos >= 3 and state.can_raise and random.random() < 0.5:
                return self.make_raise(state, max(state.min_raise_to, 5))
            else:
                return state.check()

        if chen >= 10:
            if state.can_raise:
                raise_to = state.street_bets[state.seat] + to_call + int(pot * 0.8)
                return self.make_raise(state, raise_to)
            return state.call()
        elif chen >= 8:
            if to_call <= 6 or pos >= 3:
                if state.can_raise and random.random() < 0.3:
                    raise_to = state.street_bets[state.seat] + to_call + int(pot * 0.6)
                    return self.make_raise(state, raise_to)
                return state.call()
            return state.fold()
        elif chen >= 6:
            if to_call <= 4:
                return state.call()
            elif pos >= 3:
                return state.call()
            return state.fold()
        elif chen >= 4:
            if to_call <= 2:
                return state.call()
            return state.fold()
        else:
            return state.fold()

    def postflop(self, state):
        board = state.board
        hole = state.hole
        if len(hole) != 2:
            return self.safe(state)

        cat, tie = self.evaluate(hole + board)
        strength = self.hand_strength(cat, tie, hole, board)

        opp = state.players_in_hand - 1
        if opp > 2:
            strength -= 0.1

        to_call = state.to_call
        pot = state.pot
        my_stack = state.my_stack

        if to_call >= my_stack * 0.8:
            if strength > 0.85:
                return state.call()
            return state.fold()

        if to_call >= my_stack * 0.5:
            if strength > 0.7:
                return state.call()
            return state.fold()

        if to_call == 0:
            if strength > 0.65 and state.can_raise:
                bet = int(pot * 0.6)
                return self.make_raise(state, bet)
            elif strength > 0.4 and state.can_raise and random.random() < 0.3:
                bet = int(pot * 0.5)
                return self.make_raise(state, bet)
            else:
                return state.check()

        pot_odds = to_call / (pot + to_call) if pot + to_call > 0 else 0

        aggressor = self.current_aggressor(state)
        if aggressor:
            s = self.stats.get(aggressor, {})
            agg = s.get("raises", 0) / max(1, s.get("calls", 1))
            if agg > 1.5:
                if strength > 0.35 and to_call <= pot * 0.8:
                    return state.call()

        if strength > 0.75 and state.can_raise and to_call < my_stack * 0.5:
            raise_to = state.street_bets[state.seat] + to_call + int(pot * 0.8)
            return self.make_raise(state, raise_to)

        if strength > 0.5:
            if to_call <= pot * 0.6 or strength > 0.7:
                return state.call()
            return state.fold()
        elif strength > 0.3:
            if to_call <= pot * 0.3:
                return state.call()
            return state.fold()
        else:
            if strength > 0.2 and to_call <= pot * 0.25:
                return state.call()
            return state.fold()

    def act(self, state):
        try:
            if state.clock_ms < 5000:
                return self.safe(state)
            if state.street == "preflop":
                return self.preflop(state)
            else:
                return self.postflop(state)
        except Exception:
            return self.safe(state)


bot = MyBot()