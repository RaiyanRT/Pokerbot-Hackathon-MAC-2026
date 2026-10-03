"""
Qwen 3.8 Max -- "Range-MC exploitative grinder".

Strategy: every decision (fold/check/call/raise and its size) is driven by a
time-budgeted Monte-Carlo equity simulation against per-opponent hand ranges,
where each range is estimated from that opponent's play during the current
game -- VPIP, PFR, 3-bet frequency, fold-to-raise/bet rates and aggression,
keyed by player id, blended with Bayesian priors, floored so it can never be
tighter than the frequency they voluntarily pay, and refined by the cards
they reveal at showdown.  Exploits: calling stations get maximum-size value
bets (river overbets included) and are never bluffed; identified auto-folders
get constant small bets and preflop steal-raises with any two cards; all-in
shoves are answered with implied-odds-adjusted prices that credit the dead
money callers behind will add; maniacs get wide value calls because their
modelled range is nearly random.  Position-based open/3-bet/defend thresholds
and multiway-adjusted value/bluff margins handle preflop, and a clock-aware
ladder shrinks the simulation as the time bank drains, finally falling back to
a pure heuristic -- all logic is wrapped in try/except so the bot always
returns a legal action and can never TLE/RTE/PV.
"""

from macpoker import Bot

import random
from time import perf_counter

# ---------------------------------------------------------------- constants
_RANK_IDX = {"2": 0, "3": 1, "4": 2, "5": 3, "6": 4, "7": 5, "8": 6, "9": 7,
             "T": 8, "J": 9, "Q": 10, "K": 11, "A": 12}
_SUIT_IDX = {"s": 0, "h": 1, "d": 2, "c": 3}
_RANKS = "23456789TJQKA"


def _ci(card):
    """'As' -> int 0..51 (rank = c>>2, suit = c&3)."""
    return (_RANK_IDX[card[0]] << 2) | _SUIT_IDX[card[1]]


# Preflop hand-type percentiles (0 = strongest) computed offline by large
# Monte-Carlo rollouts vs random hands (60% heads-up + 40% six-way equity).
PF_PCT = {
  'AA':0.000, 'KK':0.006, 'QQ':0.012, 'JJ':0.018, 'TT':0.024, '99':0.030,
  'AKs':0.036, '88':0.042, 'AQs':0.048, 'AKo':0.054, 'AJs':0.060, 'KQs':0.065,
  'ATs':0.071, 'AQo':0.077, '77':0.083, 'KJs':0.089, 'AJo':0.095, 'ATo':0.101,
  'QJs':0.107, 'A9s':0.113, 'KTs':0.119, '66':0.125, 'KQo':0.131, 'A8s':0.137,
  'KJo':0.143, 'QTs':0.149, 'A7s':0.155, 'K9s':0.161, 'A5s':0.167, 'KTo':0.173,
  'A6s':0.179, 'QJo':0.185, 'A4s':0.190, 'JTs':0.196, 'A9o':0.202, '55':0.208,
  'A8o':0.214, 'Q9s':0.220, 'K8s':0.226, 'K9o':0.232, 'A3s':0.238, 'QTo':0.244,
  'K7s':0.250, 'A2s':0.256, 'A7o':0.262, 'J9s':0.268, 'K6s':0.274, 'Q8s':0.280,
  'A6o':0.286, 'A5o':0.292, 'JTo':0.298, '44':0.304, 'K5s':0.310, 'J8s':0.315,
  'T9s':0.321, 'Q9o':0.327, 'K4s':0.333, 'A3o':0.339, 'A4o':0.345, 'K8o':0.351,
  'Q7s':0.357, 'K7o':0.363, 'K3s':0.369, 'A2o':0.375, 'K2s':0.381, '33':0.387,
  'J7s':0.393, 'Q6s':0.399, 'T8s':0.405, 'K6o':0.411, 'Q5s':0.417, 'Q8o':0.423,
  '98s':0.429, 'Q4s':0.435, 'J9o':0.440, 'K5o':0.446, 'T9o':0.452, 'Q3s':0.458,
  'T7s':0.464, 'J8o':0.470, 'J6s':0.476, 'K4o':0.482, 'Q7o':0.488, '97s':0.494,
  'T8o':0.500, 'K3o':0.506, 'J5s':0.512, 'T6s':0.518, '22':0.524, 'J4s':0.530,
  'J7o':0.536, '87s':0.542, 'Q5o':0.548, 'Q6o':0.554, 'Q2s':0.560, '98o':0.565,
  'J3s':0.571, 'K2o':0.577, 'T7o':0.583, '96s':0.589, 'T5s':0.595, '86s':0.601,
  'Q4o':0.607, '76s':0.613, 'T4s':0.619, 'J2s':0.625, 'J6o':0.631, 'Q3o':0.637,
  '97o':0.643, 'J5o':0.649, 'Q2o':0.655, 'T3s':0.661, '85s':0.667, '95s':0.673,
  '75s':0.679, 'T2s':0.685, '87o':0.690, 'J4o':0.696, 'T6o':0.702, '65s':0.708,
  '94s':0.714, '54s':0.720, '96o':0.726, '93s':0.732, '74s':0.738, 'T5o':0.744,
  '84s':0.750, '86o':0.756, 'J3o':0.762, '76o':0.768, 'J2o':0.774, '64s':0.780,
  '92s':0.786, 'T4o':0.792, '95o':0.798, 'T3o':0.804, '85o':0.810, '53s':0.815,
  '83s':0.821, '82s':0.827, '65o':0.833, '63s':0.839, '75o':0.845, 'T2o':0.851,
  '73s':0.857, '43s':0.863, '94o':0.869, '93o':0.875, '52s':0.881, '54o':0.887,
  '84o':0.893, '42s':0.899, '64o':0.905, '62s':0.911, '74o':0.917, '92o':0.923,
  '72s':0.929, '32s':0.935, '53o':0.940, '83o':0.946, '63o':0.952, '73o':0.958,
  '43o':0.964, '82o':0.970, '52o':0.976, '62o':0.982, '72o':0.988, '42o':0.994,
  '32o':1.000,
}

# numeric lookup PCTL[hi][lo] -> (suited_pct, offsuit_pct); pairs use slot 0
PCTL = [[(1.0, 1.0)] * 13 for _ in range(13)]
for _h in range(13):
    for _l in range(_h + 1):
        _a, _b = _RANKS[_h], _RANKS[_l]
        if _h == _l:
            PCTL[_h][_l] = (PF_PCT[_a + _b], PF_PCT[_a + _b])
        else:
            PCTL[_h][_l] = (PF_PCT[_a + _b + "s"], PF_PCT[_a + _b + "o"])

# STRAIGHT_HI[rank bitmask (13 bits)] -> 0-based index of best straight high
# card (3 means the A-5 wheel), 0 = no straight.
STRAIGHT_HI = [0] * 8192
for _m in range(8192):
    _best = 0
    for _hi in range(12, 3, -1):
        if (_m >> (_hi - 4)) & 0x1F == 0x1F:
            _best = _hi
            break
    if not _best and (_m & 0x100F) == 0x100F:
        _best = 3
    STRAIGHT_HI[_m] = _best

try:
    _BITCOUNT = int.bit_count          # Python 3.10+ (tournament runs 3.12)
except AttributeError:                # pragma: no cover - safety net
    def _BITCOUNT(x):
        return bin(x).count("1")


def evaluate7(cs):
    """Score a 7-card hand (list of ints 0..51). Higher = stronger.

    Encoding: category << 20 | up to five 4-bit tiebreak nibbles.
    Categories: 8 straight-flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    rc = [0] * 13
    sm = [0, 0, 0, 0]
    for c in cs:
        r = c >> 2
        rc[r] += 1
        sm[c & 3] |= 1 << r
    # flush?
    for m in sm:
        if _BITCOUNT(m) >= 5:
            sh = STRAIGHT_HI[m]
            if sh:
                return (8 << 20) | (sh << 16)
            b0 = b1 = b2 = b3 = b4 = 0
            n = 0
            for r in range(12, -1, -1):
                if (m >> r) & 1:
                    if n == 0:
                        b0 = r
                    elif n == 1:
                        b1 = r
                    elif n == 2:
                        b2 = r
                    elif n == 3:
                        b3 = r
                    elif n == 4:
                        b4 = r
                        break
                    n += 1
            return (5 << 20) | (b0 << 16) | (b1 << 12) | (b2 << 8) | (b3 << 4) | b4
    # group ranks
    rm = 0
    quads = -1
    trips = []
    pairs = []
    kick = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n:
            rm |= 1 << r
            if n == 4:
                quads = r
            elif n == 3:
                trips.append(r)
            elif n == 2:
                pairs.append(r)
            else:
                kick.append(r)
    if quads >= 0:
        k = kick[0] if kick else (trips[0] if trips else (pairs[0] if pairs else 0))
        return (7 << 20) | (quads << 16) | (k << 12)
    if trips:
        t = trips[0]
        if pairs:
            return (6 << 20) | (t << 16) | (pairs[0] << 12)
        if len(trips) > 1:
            return (6 << 20) | (t << 16) | (trips[1] << 12)
        sh = STRAIGHT_HI[rm]
        if sh:
            return (4 << 20) | (sh << 16)
        k1 = kick[0]
        k2 = kick[1] if len(kick) > 1 else 0
        return (3 << 20) | (t << 16) | (k1 << 12) | (k2 << 8)
    sh = STRAIGHT_HI[rm]
    if sh:
        return (4 << 20) | (sh << 16)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        k = pairs[2] if len(pairs) > 2 else -1
        if kick and kick[0] > k:
            k = kick[0]
        if k < 0:
            k = 0
        return (2 << 20) | (p1 << 16) | (p2 << 12) | (k << 8)
    if pairs:
        p = pairs[0]
        k1 = kick[0]
        k2 = kick[1] if len(kick) > 1 else 0
        k3 = kick[2] if len(kick) > 2 else 0
        return (1 << 20) | (p << 16) | (k1 << 12) | (k2 << 8) | (k3 << 4)
    k = (kick + [0, 0, 0, 0, 0])[:5]
    return (k[0] << 16) | (k[1] << 12) | (k[2] << 8) | (k[3] << 4) | k[4]


def hole_pct(c1, c2):
    """Preflop percentile (0 = strongest) of a two-card hand (ints)."""
    r1 = c1 >> 2
    r2 = c2 >> 2
    if r1 < r2:
        r1, r2 = r2, r1
    return PCTL[r1][r2][0 if (c1 & 3) == (c2 & 3) else 1]


def _hole_pct_str(cards):
    """Percentile from card strings like ['As','Kd']."""
    a, b = cards[0], cards[1]
    r1 = _RANK_IDX[a[0]]
    r2 = _RANK_IDX[b[0]]
    if r1 < r2:
        r1, r2 = r2, r1
    return PCTL[r1][r2][0 if a[1] == b[1] else 1]


# ---------------------------------------------------------------- opponent model
_PRIOR_N = 18.0


class Opp:
    """Per-player-id statistics for one game."""

    __slots__ = ("n", "vpip", "pfr", "p3b", "ftr_opp", "ftr_fold", "ftb_opp",
                 "ftb_fold", "agg_opp", "agg", "shown", "net")

    def __init__(self):
        self.n = 0
        self.vpip = 0
        self.pfr = 0
        self.p3b = 0      # preflop re-raises (3-bet+)
        self.ftr_opp = 0     # faced a preflop raise
        self.ftr_fold = 0    # ... and folded
        self.ftb_opp = 0     # faced a postflop bet
        self.ftb_fold = 0    # ... and folded
        self.agg_opp = 0     # postflop action opportunities
        self.agg = 0         # postflop bets/raises
        self.shown = []      # percentiles of revealed showdown hands
        self.net = 0

    def vpip_hat(self):
        return (self.vpip + 0.38 * _PRIOR_N) / (self.n + _PRIOR_N)

    def pfr_hat(self):
        return (self.pfr + 0.16 * _PRIOR_N) / (self.n + _PRIOR_N)

    def fold_raise(self):
        return (self.ftr_fold + 0.55 * _PRIOR_N) / (self.ftr_opp + _PRIOR_N)

    def fold_bet(self):
        return (self.ftb_fold + 0.50 * _PRIOR_N) / (self.ftb_opp + _PRIOR_N)

    def agg_rate(self):
        return (self.agg + 0.10 * _PRIOR_N) / (self.agg_opp + _PRIOR_N)

    def shown_avg(self):
        s = self.shown
        return sum(s) / len(s) if s else None


class MyBot(Bot):
    def __init__(self):
        self.rng = random.Random()
        self.opps = {}          # player id -> Opp
        self.me = None          # my player id
        self.num_players = 5
        # per-hand bookkeeping for the observer hooks
        self.pre_raised = False       # a preflop raise has happened this hand
        self.street_bet_made = False  # a postflop bet has happened this street
        self.vpip_seen = set()        # pids that voluntarily paid preflop
        self.pfr_seen = set()
        self.p3b_seen = set()
        # diagnostics
        self.net = 0
        self.decisions = 0
        self.time_used = 0.0
        self.fallbacks = 0

    # ------------------------------------------------------------- helpers
    def _opp(self, pid):
        o = self.opps.get(pid)
        if o is None:
            o = Opp()
            self.opps[pid] = o
        return o

    # ------------------------------------------------------------- hooks
    def on_match_start(self, info):
        try:
            if info:
                self.me = info.get("player")
                n = info.get("num_players")
                if n:
                    self.num_players = int(n)
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            self.pre_raised = False
            self.street_bet_made = False
            self.vpip_seen = set()
            self.pfr_seen = set()
            self.p3b_seen = set()
            players = (info or {}).get("players") or []
            for p in players:
                if p is not None and p != self.me:
                    self._opp(p).n += 1
        except Exception:
            pass

    def on_action(self, event):
        try:
            players = event.get("players")
            seat = event.get("seat")
            if players is None or seat is None:
                return
            pid = players[seat]
            mine = pid == self.me
            kind = event.get("action")
            street = event.get("street")
            o = None if mine else self._opp(pid)
            if street == "preflop":
                if kind in ("raise", "bet", "allin"):
                    if not mine:
                        if pid not in self.vpip_seen:
                            self.vpip_seen.add(pid)
                            o.vpip += 1
                        if pid not in self.pfr_seen:
                            self.pfr_seen.add(pid)
                            o.pfr += 1
                        if self.pre_raised and pid not in self.p3b_seen:
                            self.p3b_seen.add(pid)
                            o.p3b += 1
                    self.pre_raised = True
                elif kind == "call":
                    if not mine:
                        if (event.get("amount") or 0) > 0 \
                                and pid not in self.vpip_seen:
                            self.vpip_seen.add(pid)
                            o.vpip += 1
                        if self.pre_raised:
                            o.ftr_opp += 1
                elif kind == "fold":
                    # folding to a raise OR to the blind = folds to pressure
                    if not mine:
                        o.ftr_opp += 1
                        o.ftr_fold += 1
            else:
                if kind in ("raise", "bet", "allin"):
                    if not mine:
                        o.agg += 1
                        o.agg_opp += 1
                        if self.street_bet_made:
                            o.ftb_opp += 1    # re-raise facing a bet: no fold
                    self.street_bet_made = True
                elif kind == "call":
                    if not mine:
                        o.agg_opp += 1
                        if self.street_bet_made:
                            o.ftb_opp += 1
                elif kind == "fold":
                    if not mine and self.street_bet_made:
                        o.ftb_opp += 1
                        o.ftb_fold += 1
                elif kind == "check":
                    if not mine:
                        o.agg_opp += 1
        except Exception:
            pass

    def on_street(self, event):
        try:
            self.street_bet_made = False
        except Exception:
            pass

    def on_hand_end(self, info):
        try:
            if not info:
                return
            players = info.get("players") or []
            revealed = info.get("revealed") or {}
            for seat_str, cards in revealed.items():
                try:
                    if not cards or len(cards) < 2:
                        continue
                    pid = players[int(seat_str)]
                    if pid == self.me:
                        continue
                    o = self._opp(pid)
                    o.shown.append(_hole_pct_str(cards))
                    if len(o.shown) > 60:
                        o.shown.pop(0)
                except Exception:
                    continue
            deltas = info.get("deltas") or []
            if players and deltas:
                try:
                    s = players.index(self.me)
                    if s < len(deltas):
                        self.net += deltas[s]
                except Exception:
                    pass
        except Exception:
            pass

    def on_match_end(self, info):
        try:
            avg = (self.time_used / self.decisions * 1000.0) if self.decisions else 0.0
            print("net=%d decisions=%d avg_ms=%.1f fallbacks=%d"
                  % (self.net, self.decisions, avg, self.fallbacks))
        except Exception:
            pass

    # ------------------------------------------------------------- safety
    @staticmethod
    def _safe(state):
        """Always-legal fallback: check when possible else fold."""
        try:
            if state.to_call == 0:
                return state.check()
            return state.fold()
        except Exception:
            try:
                return state.fold()
            except Exception:
                return None

    # ------------------------------------------------------------- main entry
    def act(self, state):
        t0 = perf_counter()
        try:
            a = self._act(state, t0)
            self.decisions += 1
            self.time_used += perf_counter() - t0
            if a is None:
                self.fallbacks += 1
                return self._safe(state)
            return a
        except Exception:
            self.fallbacks += 1
            try:
                self.time_used += perf_counter() - t0
            except Exception:
                pass
            return self._safe(state)

    def _act(self, state, t0):
        try:
            clock = int(getattr(state, "clock_ms", 30000))
        except Exception:
            clock = 30000
        if clock < 1500:
            return self._heuristic(state)

        hole = [_ci(c) for c in state.hole]
        board = [_ci(c) for c in state.board]
        pct = hole_pct(hole[0], hole[1])
        street = state.street
        preflop = street == "preflop"
        my_seat = state.seat
        n_total = state.num_players

        # who is still in, and my opponent count
        folded = state.folded
        if not folded:
            folded = [False] * n_total
        act_seats = [s for s in range(n_total)
                     if s != my_seat and not folded[s]]
        n_opp = len(act_seats)
        if n_opp <= 0:
            return self._safe(state)

        # parse this hand's action history (cheap, <= ~40 entries)
        pre_raise_seats = set()
        pre_call_seats = set()
        post_raises = {}
        post_calls = {}
        r_cnt = 0
        last_raiser = None
        try:
            for e in (state.history or []):
                st, seat, kind = e[0], e[1], e[2]
                if st == "preflop":
                    if kind in ("raise", "bet", "allin"):
                        r_cnt += 1
                        pre_raise_seats.add(seat)
                        last_raiser = seat
                    elif kind == "call":
                        pre_call_seats.add(seat)
                else:
                    if kind in ("raise", "bet", "allin"):
                        post_raises[seat] = post_raises.get(seat, 0) + 1
                    elif kind == "call":
                        post_calls[seat] = post_calls.get(seat, 0) + 1
        except Exception:
            pass

        players = state.players
        opps = []  # (seat, pid, Opp-or-None)
        for s in act_seats:
            try:
                pid = players[s]
            except Exception:
                pid = None
            opps.append((s, pid, self.opps.get(pid)))

        # current bet level / aggressor
        try:
            sbets = state.street_bets
            b = max(sbets) if sbets else 0
            agg_seat = None
            if state.to_call > 0:
                for (s, _p, _o) in opps:
                    if sbets[s] == b:
                        agg_seat = s
                        break
        except Exception:
            b = state.to_call + (state.street_bets[my_seat] if state.street_bets else 0)
            agg_seat = None

        # opponent fold tendencies (for sizing / bluffing)
        if preflop:
            folds = [o.fold_raise() for (_s, _p, o) in opps if o]
            agg_o = None
            if agg_seat is not None:
                for (s, _p, o) in opps:
                    if s == agg_seat and o:
                        agg_o = o
        else:
            folds = [o.fold_bet() for (_s, _p, o) in opps if o]
            agg_o = None
            if agg_seat is not None:
                for (s, _p, o) in opps:
                    if s == agg_seat and o:
                        agg_o = o
        fold_avg = sum(folds) / len(folds) if folds else 0.5

        # MC equity (unless the clock forces the heuristic path)
        if clock >= 20000:
            budget = 0.016
        elif clock >= 12000:
            budget = 0.010
        elif clock >= 6000:
            budget = 0.005
        else:
            budget = 0.0025
        ranges = []
        for (s, pid, o) in opps:
            ranges.append(self._estimate_range(o, s, preflop, r_cnt,
                                               pre_raise_seats, pre_call_seats,
                                               post_raises, post_calls,
                                               last_raiser))
        eq = self._mc_equity(hole, board, ranges, t0, budget, n_opp)
        if eq is None:
            return self._heuristic(state)

        pot = state.pot
        to_call = state.to_call
        my_bet = state.street_bets[my_seat] if state.street_bets else 0
        denom = pot + to_call
        needed = (to_call / denom) if denom > 0 else 0.0
        # Implied odds on big bets/all-ins: opponents who still owe chips and
        # essentially never fold will add dead money, improving the price.
        if to_call >= 30 and to_call >= 0.35 * (state.my_stack + to_call):
            try:
                exp_behind = 0.0
                for (s, _pid, o) in opps:
                    try:
                        sbets_s = state.street_bets[s] if state.street_bets else 0
                        owe = b - sbets_s
                        if owe <= 0:
                            continue
                        call_amt = min(owe, state.stacks[s])
                    except Exception:
                        continue
                    if o is not None and o.n >= 6:
                        f = o.fold_raise() if preflop else o.fold_bet()
                        p_call = min(1.0, max(0.0, 1.25 * (1.0 - f)))
                    else:
                        p_call = 0.25
                    exp_behind += p_call * call_amt
                if 0.0 < exp_behind <= to_call * max(1, n_opp - 1):
                    needed = to_call / (denom + exp_behind)
            except Exception:
                pass
        # facing a true all-in? margins shrink: no future streets, and a
        # shover's range is well identified once we have seen it a while.
        allin_facing = False
        try:
            if agg_seat is not None and state.stacks[agg_seat] == 0:
                allin_facing = True
        except Exception:
            pass
        rng = self.rng

        # -------------------------------------------------------- decision
        if to_call == 0:
            if preflop:
                return self._pf_option(state, pct, opps, pre_call_seats, rng)
            # postflop, first to act (or checked to)
            auto_folders = [1 for (_s, _p, o) in opps
                            if o and o.ftb_opp >= 2 and o.fold_bet() >= 0.85]
            if len(auto_folders) == n_opp:
                # everyone left folds to any bet: bet small with anything
                return self._do_bet(state, 0.34, my_bet, pot) or state.check()
            stations = sum(1 for (_s, _p, o) in opps
                           if o and o.n >= 8 and o.fold_bet() <= 0.25)
            v_thresh = 0.55 + 0.06 * (n_opp - 1) - 0.04 * min(stations, 2)
            if eq >= 0.78:
                frac = 0.70 + 0.30 * (1.0 - fold_avg)
                if stations and n_opp == 1:
                    frac = max(frac, 1.15)   # overbet: stations call huge
                return self._do_bet(state, frac, my_bet, pot) or state.check()
            if eq >= v_thresh:
                frac = 0.50 + 0.40 * (1.0 - fold_avg)
                return self._do_bet(state, frac, my_bet, pot) or state.check()
            # bluffing
            if eq < 0.47:
                if n_opp == 1 and fold_avg >= 0.48:
                    freq = min(0.50, 0.8 * (fold_avg - 0.38))
                    if eq >= 0.34:
                        freq *= 0.55   # marginal showdown value: bluff less
                    if rng.random() < freq:
                        return self._do_bet(state, 0.62, my_bet, pot) or state.check()
                elif n_opp >= 2 and fold_avg >= 0.62 and eq < 0.35 \
                        and rng.random() < 0.18:
                    return self._do_bet(state, 0.5, my_bet, pot) or state.check()
            return state.check()

        # ------------------------------------------------- facing a bet
        if preflop:
            return self._pf_facing(state, eq, pct, needed, b, r_cnt, opps,
                                  agg_o, rng, n_opp, pre_call_seats,
                                  allin_facing)

        # postflop facing a bet
        can_raise = state.can_raise
        if can_raise:
            if eq >= 0.72 and eq >= needed + 0.25:
                # trap sometimes vs hyper-aggressive bettors
                if (n_opp == 1 and agg_o and agg_o.agg_opp >= 6
                        and agg_o.agg_rate() > 0.42 and rng.random() < 0.35):
                    return state.call()
                inc = max(state.min_raise_to - my_bet, int(0.72 * (pot + to_call)))
                target = b + inc
                act = self._do_raise(state, target)
                return act or state.call()
            if eq >= needed + (0.008 if allin_facing else 0.03):
                # semi-bluff raise vs folders
                if (n_opp == 1 and agg_o and agg_o.ftb_opp >= 4
                        and agg_o.fold_bet() >= 0.55
                        and eq <= needed + 0.22
                        and rng.random() < 0.28 * (agg_o.fold_bet() - 0.40)):
                    act = self._do_raise(state, b + int(0.8 * (pot + to_call)))
                    if act is not None:
                        return act
                return state.call()
            # pure bluff-raise
            if (n_opp == 1 and agg_o and agg_o.ftb_opp >= 5
                    and agg_o.fold_bet() >= 0.58 and eq >= 0.15
                    and rng.random() < 0.22 * (agg_o.fold_bet() - 0.45)):
                act = self._do_raise(state, b + int(0.85 * (pot + to_call)))
                if act is not None:
                    return act
            return state.fold()
        # cannot raise: call/fold on price
        if eq >= needed + (0.006 if allin_facing else 0.015):
            return state.call()
        return state.fold()

    # ------------------------------------------------------------- preflop
    def _pf_option(self, state, pct, opps, pre_call_seats, rng):
        """Preflop with to_call == 0 (BB option / checked around)."""
        limpers = len(pre_call_seats - {state.seat})
        mn = state.min_raise_to
        if not state.can_raise:
            return state.check()
        th = 0.46 - 0.05 * limpers
        if state.num_players == 2:
            th += 0.25   # heads-up BB iso: raise nearly anything
        # widen vs opponents who fold a lot
        f = [o.fold_raise() for (_s, _p, o) in opps if o]
        if f and sum(f) / len(f) >= 0.68:
            th += 0.18
        auto = [1 for (_s, _p, o) in opps
                if o and o.ftr_opp >= 3 and o.fold_raise() >= 0.85]
        if limpers == 0 and len(auto) == len(opps) and len(opps) > 0:
            th = 0.95   # steal: everyone left folds to a raise
        stations = [1 for (_s, _p, o) in opps
                    if o and o.n >= 8 and o.fold_bet() <= 0.25]
        if pct <= max(0.10, th):
            target = mn + 2 + 2 * limpers + 2 * len(stations)
            act = self._do_bet(state, None, state.street_bets[state.seat],
                               state.pot, fixed=target)
            return act or state.check()
        return state.check()

    def _pf_facing(self, state, eq, pct, needed, b, r_cnt, opps, agg_o, rng,
                   n_opp, pre_call_seats, allin_facing=False):
        to_call = state.to_call
        can_raise = state.can_raise
        my_bet = state.street_bets[state.seat] if state.street_bets else 0
        mn = state.min_raise_to
        if r_cnt == 0:
            # Unraised pot: an open decision (SB complete, or first in).
            n_t = state.num_players
            d = (state.seat - state.button) % n_t
            if d == 0:
                behind = 2 if n_t > 2 else 1
            elif d == 1:
                behind = 1
            elif d == 2:
                behind = 0
            else:
                behind = n_t + 2 - d
            behind = max(0, min(behind, n_opp))
            o_list = [o for (_s, _p, o) in opps if o]
            folders = sum(1 for o in o_list if o.ftr_opp >= 3 and o.fold_raise() >= 0.65)
            stations = sum(1 for o in o_list if o.n >= 8 and o.fold_bet() <= 0.28)
            maniacs = sum(1 for o in o_list if o.n >= 8 and o.pfr_hat() >= 0.55)
            three_bet = sum(1 for o in o_list
                            if o.n >= 12
                            and (o.p3b + 0.05 * 18.0) / (o.n + 18.0) >= 0.075)
            limpers = len(pre_call_seats - {state.seat})
            if to_call <= 1:
                th = 0.45   # SB vs BB
            else:
                th = {0: 0.50, 1: 0.45, 2: 0.40, 3: 0.33}.get(behind, 0.28)
            if n_t == 2:
                th += 0.30   # heads-up: open/complete far wider
            th += 0.05 * min(folders, 2)
            th -= 0.04 * min(stations, 2)
            th -= 0.09 * min(maniacs, 1)
            th -= 0.04 * min(three_bet, 2)
            th -= 0.03 * min(limpers, 3)

            # everyone left folds to any raise: open literally anything
            auto = [1 for o in o_list if o.ftr_opp >= 3 and o.fold_raise() >= 0.85]
            if len(opps) > 0 and len(auto) == len(opps):
                th = 0.97
            if pct <= max(0.08, th) and can_raise:
                target = 6 + 2 * limpers + 2 * min(stations, 2)
                if to_call <= 1 and stations and pct <= 0.25:
                    target = 9    # bigger isolation vs a station
                act = self._do_raise(state, max(mn, target))
                if act is not None:
                    return act
            if eq >= needed + 0.02 or (to_call <= 1 and eq >= 0.32):
                return state.call()
            return state.fold()
        # facing at least one raise
        if can_raise:
            if r_cnt == 1:
                if pct <= 0.045 or eq >= 0.62:
                    target = min(state.max_raise_to, int(round(b * 3.2)) + 2)
                    act = self._do_raise(state, target)
                    if act is not None:
                        return act
                elif (0.24 <= pct <= 0.60 and n_opp <= 2 and agg_o
                      and agg_o.ftr_opp >= 4 and agg_o.fold_raise() >= 0.52
                      and rng.random() < (0.24 if agg_o.fold_raise() >= 0.62
                                          else 0.15)):
                    act = self._do_raise(state, int(round(b * 2.8)) + 2)
                    if act is not None:
                        return act
            else:
                if pct <= 0.018 or eq >= 0.68:
                    act = self._do_raise(state, min(state.max_raise_to,
                                                    int(round(b * 2.8))))
                    if act is not None:
                        return act
            margin = 0.035 if r_cnt == 1 else 0.05
            if allin_facing:
                well_known = agg_o is not None and agg_o.n >= 25
                margin = 0.006 if well_known else 0.015
            if eq >= needed + margin or (to_call <= 2 and eq >= 0.34):
                return state.call()
            return state.fold()
        if eq >= needed + (0.006 if allin_facing else 0.015):
            return state.call()
        return state.fold()

    # ------------------------------------------------------------- sizing
    def _do_bet(self, state, frac, my_bet, pot, fixed=None):
        """Bet when to_call == 0. Returns action or None if impossible."""
        try:
            if not state.can_raise:
                return None
            mn = state.min_raise_to
            mx = state.max_raise_to
            if mx < mn:
                return None
            if fixed is not None:
                target = int(fixed)
            else:
                size = int(round(frac * max(pot, 2)))
                target = my_bet + max(2, size)
            target = max(mn, min(mx, target))
            if target >= mx or mx - target <= 2:
                return state.all_in()
            return state.raise_to(target)
        except Exception:
            return None

    def _do_raise(self, state, target):
        """Raise to `target` (total this street), clamped. None if impossible."""
        try:
            if not state.can_raise:
                return None
            mn = state.min_raise_to
            mx = state.max_raise_to
            if mx < mn:
                return None
            target = int(round(target))
            target = max(mn, min(mx, target))
            if target >= mx or mx - target <= 2:
                return state.all_in()
            return state.raise_to(target)
        except Exception:
            return None

    # ------------------------------------------------------------- ranges
    def _estimate_range(self, o, seat, preflop, r_cnt, pre_raise_seats,
                        pre_call_seats, post_raises, post_calls,
                        last_raiser=None):
        """Estimated percentile width (0..1) of an opponent's current range."""
        try:
            if o is None:
                vp, pf = 0.38, 0.16
                shown_blend = None
            else:
                vp = o.vpip_hat()
                pf = o.pfr_hat()
                sa = o.shown_avg()
                shown_blend = sa if (sa is not None and len(o.shown) >= 4) else None
            # invariant: a player who pays with (nearly) everything cannot
            # have a tight raising range either (random/call bots)
            vp_floor = min(1.0, vp * 0.95) if vp >= 0.55 else 0.0
            if seat in pre_raise_seats:
                r = pf
                # low sample: hedge that an unknown raiser may be looser
                n_seen = o.n if o is not None else 0
                if n_seen < 30:
                    r = r * (1.30 - 0.30 * (n_seen / 30.0)) + 0.02
                # a re-raise (3-bet+) range is much tighter than an open range
                if r_cnt >= 2:
                    if seat == last_raiser:
                        p3 = ((o.p3b + 0.05 * _PRIOR_N) / (o.n + _PRIOR_N)
                              if o is not None else 0.05)
                        r = min(r, max(0.025, min(0.35, p3 * 1.15 + 0.01)))
                    else:
                        r = min(r, r * 0.55 + 0.02)
                r = max(r, vp_floor)
                r = min(1.0, max(0.025, r))
            elif seat in pre_call_seats:
                r = min(1.0, max(0.12, max(vp * 1.15 + 0.05, vp_floor)))
            else:
                # checked through (e.g. BB option) or has not acted yet
                r = min(1.0, max(0.25, vp + 0.40))
            if not preflop:
                nr = post_raises.get(seat, 0)
                nc = post_calls.get(seat, 0)
                if nr:
                    r *= 0.55 ** nr
                if nc:
                    r *= 0.78 ** nc
                r = max(0.02, r)
            if shown_blend is not None:
                n_sh = len(o.shown) if o is not None else 0
                w = 0.5 if n_sh >= 6 else 0.4
                r_sh = min(1.0, max(0.02, shown_blend * 1.6 + 0.08))
                r = (1.0 - w) * r + w * r_sh
            return min(1.0, max(0.02, r))
        except Exception:
            return 0.75

    # ------------------------------------------------------------- equity MC
    def _mc_equity(self, hole, board, ranges, t0, budget, n_opp):
        """Monte-Carlo equity of `hole` + `board` vs opponents sampled from
        their range percentiles. Time-budgeted; returns None if no iteration
        completed."""
        try:
            rng = self.rng
            randrange = rng.randrange
            known = hole + board
            deck = [c for c in range(52) if c not in known]
            nd = len(deck)
            n = len(ranges)
            need_board = 5 - len(board)
            # tight ranges (<0.35) get exact precomputed combo lists;
            # wider ranges use cheap rejection sampling (>=35% acceptance)
            combo_lists = []
            cache = {}
            for r in ranges:
                if r >= 0.35:
                    combo_lists.append(None)
                    continue
                key = round(r, 3)
                cl = cache.get(key)
                if cl is None:
                    cl = []
                    for i in range(nd):
                        ci_ = deck[i]
                        ri = ci_ >> 2
                        si = ci_ & 3
                        for j in range(i + 1, nd):
                            cj = deck[j]
                            rj = cj >> 2
                            if ri >= rj:
                                p = PCTL[ri][rj][0 if si == (cj & 3) else 1]
                            else:
                                p = PCTL[rj][ri][0 if si == (cj & 3) else 1]
                            if p <= r:
                                cl.append((i, j))
                    cache[key] = cl
                combo_lists.append(cl if cl else None)
            it_cap = {1: 1100, 2: 850, 3: 650}.get(n, 520)
            deadline = t0 + budget
            wins = 0.0
            it = 0
            attempts = 0
            ev = evaluate7
            hero_cards = hole
            while it < it_cap and attempts < it_cap * 8:
                attempts += 1
                it += 1
                used = [False] * nd
                opp_hands = []
                ok = True
                for k in range(n):
                    cl = combo_lists[k]
                    got = None
                    if cl:
                        m = len(cl)
                        for _try in range(14):
                            i, j = cl[randrange(m)]
                            if not used[i] and not used[j]:
                                got = (deck[i], deck[j])
                                used[i] = True
                                used[j] = True
                                break
                        if got is None:
                            ok = False
                            break
                    else:
                        rr = ranges[k]
                        best = None
                        best_p = 2.0
                        for _try in range(6):
                            i = randrange(nd)
                            if used[i]:
                                continue
                            j = randrange(nd)
                            if used[j] or j == i:
                                continue
                            if rr >= 0.999:
                                got = (deck[i], deck[j])
                                used[i] = True
                                used[j] = True
                                break
                            c1 = deck[i]
                            c2 = deck[j]
                            r1 = c1 >> 2
                            r2 = c2 >> 2
                            if r1 < r2:
                                r1, r2 = r2, r1
                            p = PCTL[r1][r2][0 if (c1 & 3) == (c2 & 3) else 1]
                            if p < best_p:
                                best_p = p
                                best = (i, j)
                            if p <= rr:
                                got = (c1, c2)
                                used[i] = True
                                used[j] = True
                                break
                        if got is None and best is not None:
                            i, j = best
                            if not used[i] and not used[j]:
                                got = (deck[i], deck[j])
                                used[i] = True
                                used[j] = True
                        if got is None:
                            ok = False
                            break
                    opp_hands.append(got)
                if not ok:
                    it -= 1
                    continue
                if need_board:
                    avail = [deck[i] for i in range(nd) if not used[i]]
                    m = len(avail)
                    if m < need_board:
                        it -= 1
                        continue
                    # partial Fisher-Yates for the runout
                    rb = []
                    for q in range(need_board):
                        z = randrange(m - q)
                        rb.append(avail[z])
                        avail[z] = avail[m - q - 1]
                    full = board + rb
                else:
                    full = board
                hs = ev(hero_cards + full)
                best = -1
                ties = 0
                for (c1, c2) in opp_hands:
                    s = ev([c1, c2] + full)
                    if s > best:
                        best = s
                        ties = 1
                    elif s == best:
                        ties += 1
                if hs > best:
                    wins += 1.0
                elif hs == best:
                    wins += 1.0 / (ties + 1)
                if (it & 15) == 0 and perf_counter() > deadline:
                    break
            if it <= 0:
                return None
            return wins / it
        except Exception:
            return None

    # ------------------------------------------------------------- heuristic
    def _heuristic(self, state):
        """No-MC fast path used when the clock is nearly gone."""
        try:
            to_call = state.to_call
            pot = state.pot
            needed = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0
            if state.street == "preflop":
                pct = _hole_pct_str(state.hole)
                if to_call == 0:
                    if pct <= 0.30 and state.can_raise:
                        return self._do_bet(state, None,
                                            state.street_bets[state.seat], pot,
                                            fixed=state.min_raise_to + 2) \
                            or state.check()
                    return state.check()
                if pct <= 0.05 and state.can_raise:
                    return self._do_raise(state, state.min_raise_to * 2) \
                        or state.call()
                if pct <= 0.42 - needed or needed <= 0.12:
                    return state.call()
                return state.fold()
            hole = [_ci(c) for c in state.hole]
            board = [_ci(c) for c in state.board]
            cat = evaluate7(hole + board) >> 20
            if to_call == 0:
                if cat >= 3 and state.can_raise:
                    return self._do_bet(state, 0.7,
                                        state.street_bets[state.seat], pot) \
                        or state.check()
                if cat == 2 and state.can_raise:
                    return self._do_bet(state, 0.5,
                                        state.street_bets[state.seat], pot) \
                        or state.check()
                return state.check()
            if cat >= 5:
                if state.can_raise:
                    return self._do_raise(
                        state,
                        max(state.street_bets) + int(0.7 * (pot + to_call))) \
                        or state.call()
                return state.call()
            if cat == 3:
                return state.call()
            if cat == 2 and needed <= 0.45:
                return state.call()
            if cat == 1 and needed <= 0.20:
                return state.call()
            if needed <= 0.07:
                return state.call()
            return state.fold()
        except Exception:
            return self._safe(state)