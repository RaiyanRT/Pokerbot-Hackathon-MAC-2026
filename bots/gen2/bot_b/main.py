"""Cartographer: a range-mapping, expected-value poker bot.

Unopened pots preflop use a position chart that widens or tightens with how
often the players still to act have folded to raises this game; every other
decision weights each live opponent's range from their actions this hand and
their tendencies this game (tracked by player id, corrected at showdowns),
then Monte Carlo samples their hands and the run-out. Tendencies are read
fast: preflop fold and raise rates are pooled across spots, a player who
plays most hands is not credited with a tight raising range, and a postflop
bet bigger than that player's usual size is read as coming from a stronger
range. Each legal option (fold, check, call, several bet or raise sizes,
all-in) is scored in expected chips, with every opponent folding the weakest
part of their range at the rate they have shown for that bet size, and in the
last half of a game the same samples are also scored in expected finishing
place, overriding chip EV only for a clear gain in game points. All logic
sits inside try/except with a check/fold fallback, a per-decision time budget
and a cheap rule-based mode for when the clock runs low.
"""

import math
import random
import time
from bisect import bisect_left
from itertools import accumulate

from macpoker import Bot

# --------------------------------------------------------------------------
# Cards and hand evaluation. A card is rank * 4 + suit (rank 0 = deuce).
# --------------------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "cdhs"
_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41)
CPRIME = [_PRIMES[c >> 2] for c in range(52)]


def parse_card(s):
    return RANKS.index(s[0].upper()) * 4 + SUITS.index(s[1].lower())


def _build_straights():
    table = [-1] * 8192
    for m in range(8192):
        for top in range(12, 3, -1):
            w = 0x1F << (top - 4)
            if m & w == w:
                table[m] = top
                break
        else:
            if m & 0x100F == 0x100F:  # wheel A-2-3-4-5
                table[m] = 3
    return table


STRAIGHT = _build_straights()
_MEMO = {}  # prime product of ranks -> non-flush hand value
_OUTS = {}  # rank mask -> mask of ranks that would complete a straight


def _rank_value(ranks):
    """Best non-flush value of 5-7 ranks as an int (category << 20 | kickers)."""
    cnt = [0] * 13
    mask = 0
    for r in ranks:
        cnt[r] += 1
        mask |= 1 << r
    quads, trips, pairs = [], [], []
    for r in range(12, -1, -1):
        c = cnt[r]
        if c >= 2:
            if c == 4:
                quads.append(r)
            elif c == 3:
                trips.append(r)
            else:
                pairs.append(r)
    if quads:
        q = quads[0]
        k = max(r for r in ranks if r != q)
        return 0x700000 | q << 16 | k << 12
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
        return 0x600000 | t << 16 | p << 12
    st = STRAIGHT[mask]
    if st >= 0:
        return 0x400000 | st << 16
    if trips:
        t = trips[0]
        ks = sorted((r for r in ranks if r != t), reverse=True)
        return 0x300000 | t << 16 | ks[0] << 12 | ks[1] << 8
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        k = max(r for r in ranks if r != p1 and r != p2)
        return 0x200000 | p1 << 16 | p2 << 12 | k << 8
    if pairs:
        p = pairs[0]
        ks = sorted((r for r in ranks if r != p), reverse=True)
        return 0x100000 | p << 16 | ks[0] << 12 | ks[1] << 8 | ks[2] << 4
    ks = sorted(ranks, reverse=True)
    return ks[0] << 16 | ks[1] << 12 | ks[2] << 8 | ks[3] << 4 | ks[4]


def _flush_value(rs):
    m = 0
    for r in rs:
        m |= 1 << r
    st = STRAIGHT[m]
    if st >= 0:
        return 0x800000 | st << 16
    rs = sorted(rs, reverse=True)
    return 0x500000 | rs[0] << 16 | rs[1] << 12 | rs[2] << 8 | rs[3] << 4 | rs[4]


def hand_value(cards):
    """Value of the best 5-card hand from 5-7 cards; higher is better."""
    key = 1
    for c in cards:
        key *= CPRIME[c]
    v = _MEMO.get(key)
    if v is None:
        v = _rank_value([c >> 2 for c in cards])
        _MEMO[key] = v
    sc = [0, 0, 0, 0]
    for c in cards:
        sc[c & 3] += 1
    for s in range(4):
        if sc[s] >= 5:
            fv = _flush_value([c >> 2 for c in cards if c & 3 == s])
            if fv > v:
                v = fv
            break
    return v


def _hv(key, br, fs, fcnt, frk, a, b):
    """Fast value of hole (a, b) on a board given as precomputed parts."""
    k = key * CPRIME[a] * CPRIME[b]
    v = _MEMO.get(k)
    if v is None:
        v = _rank_value(br + [a >> 2, b >> 2])
        _MEMO[k] = v
    if fs >= 0:
        sa = (a & 3) == fs
        sb = (b & 3) == fs
        if fcnt + sa + sb >= 5:
            fr = list(frk)
            if sa:
                fr.append(a >> 2)
            if sb:
                fr.append(b >> 2)
            fv = _flush_value(fr)
            if fv > v:
                v = fv
    return v


def _board_parts(board):
    key = 1
    sc = [0, 0, 0, 0]
    for c in board:
        key *= CPRIME[c]
        sc[c & 3] += 1
    fs = -1
    for s in range(4):
        if sc[s] >= 3:
            fs = s
            break
    frk = [c >> 2 for c in board if c & 3 == fs] if fs >= 0 else None
    return key, [c >> 2 for c in board], fs, (sc[fs] if fs >= 0 else 0), frk


def _outs(mask):
    r = _OUTS.get(mask)
    if r is None:
        r = 0
        for k in range(13):
            if not (mask >> k) & 1 and STRAIGHT[mask | (1 << k)] >= 0:
                r |= 1 << k
        _OUTS[mask] = r
    return r


def _popcount(x):
    return bin(x).count("1")


# --------------------------------------------------------------------------
# Preflop hand classes, strongest first. Generated offline by Monte Carlo:
# rank by a blend of equity against one random hand and against three.
# --------------------------------------------------------------------------
ORDER = (
    "AA KK QQ JJ TT 99 AKs AQs 88 AJs AKo ATs KQs AQo 77 AJo KJs KTs ATo A9s "
    "A8s KQo QJs 66 KJo QTs A7s A9o K9s A5s KTo A6s QJo A8o JTs A4s Q9s 55 K8s "
    "A3s QTo K7s A7o A2s A5o J9s K9o K6s Q8s JTo A6o A4o T9s K5s Q9o J8s Q7s 44 "
    "K8o K4s A3o T8s K7o K3s J9o Q6s A2o K6o T9o Q8o 98s J7s K2s Q5s J8o Q4s T7s "
    "33 K5o 97s K4o Q7o 87s Q3s T8o J6s T6s Q2s J5s Q6o K3o 98o 96s K2o J7o J4s "
    "86s T7o T5s 22 Q5o J3s 76s Q4o J2s 97o T4s 87o 95s 85s Q3o 75s J6o T3s T6o "
    "J5o 65s T2s J4o 96o Q2o 94s 86o 64s 54s 76o 74s 84s 93s J3o T5o 92s J2o T4o "
    "53s 95o 83s 85o 63s 73s 75o 65o T3o 43s 82s T2o 94o 52s 54o 93o 64o 72s 74o "
    "84o 42s 62s 92o 32s 83o 63o 53o 73o 82o 43o 52o 42o 72o 62o 32o"
).split()
_CLASS_IDX = {name: i for i, name in enumerate(ORDER)}
Q = [0.0] * len(ORDER)  # fraction of all combos at least this strong (0 = best)
CLASS_COMBOS = [0] * len(ORDER)
_acc = 0
for _i, _name in enumerate(ORDER):
    _n = 6 if len(_name) == 2 else (4 if _name[2] == "s" else 12)
    CLASS_COMBOS[_i] = _n
    Q[_i] = (_acc + _n / 2.0) / 1326.0
    _acc += _n
CLS = [0] * 2704
for _a in range(52):
    for _b in range(52):
        if _a != _b:
            _hi, _lo = max(_a >> 2, _b >> 2), min(_a >> 2, _b >> 2)
            if _hi == _lo:
                _name = RANKS[_hi] * 2
            else:
                _name = RANKS[_hi] + RANKS[_lo] + ("s" if (_a & 3) == (_b & 3) else "o")
            CLS[_a * 52 + _b] = _CLASS_IDX[_name]


def hole_q(hole):
    return Q[CLS[hole[0] * 52 + hole[1]]]


def _sig(x):
    if x > 30.0:
        return 1.0
    if x < -30.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


# --------------------------------------------------------------------------
# Opponent statistics (one per player id, reset every game).
# --------------------------------------------------------------------------
def _est(hits, n, prior, k):
    return (hits + prior * k) / (n + k)


# (fold, raise) priors when facing a preflop raise, keyed (tier, invested)
# then [big]: tier 1 = one raise, 2 = a 3-bet, 3 = a 4-bet or more; invested
# means the player already put chips in voluntarily this hand.
PF_PRIOR = {
    (1, False): ((0.58, 0.09), (0.80, 0.04)),
    (1, True): ((0.45, 0.10), (0.70, 0.04)),
    (2, True): ((0.38, 0.18), (0.60, 0.05)),
    (2, False): ((0.92, 0.03), (0.95, 0.02)),
    (3, True): ((0.30, 0.25), (0.35, 0.05)),
    (3, False): ((0.96, 0.02), (0.97, 0.01)),
}
# Postflop fold prior shift per bet-size bucket (<0.45, <0.85, <1.6, >=1.6 pot).
POST_FOLD_SHIFT = (-0.10, -0.03, 0.06, 0.12)
POST_FOLD_BASE = 0.42  # prior share of hands folded to a postflop bet
POST_RAISE_BASE = 0.10  # prior share of hands raising a postflop bet
BLUFF_PRIOR = 0.15  # prior share of postflop bets made with weak hands
# Pseudo-count for a player's preflop fold/raise tendency, which scales the
# prior of every preflop spot so a player who never (or always) folds to
# raises is read after a few hands instead of spot by spot. Large = off.
POOL_K = 3.0
# A player who voluntarily plays at least this share of hands is not raising
# from a tight range; their raising range is widened to their playing range.
VPIP_FLOOR = 0.55
# Exponent of the bet-size tell: a postflop bet bigger than that player's own
# average size is read as coming from a tighter range (smaller: wider). 0 = off.
SIZE_TELL = 0.5


def size_bucket(r):
    if r < 0.45:
        return 0
    if r < 0.85:
        return 1
    if r < 1.6:
        return 2
    return 3


class OppStats:
    def __init__(self):
        self.hands = 0
        self.vpip = 0
        self.open_opp = 0
        self.open_n = 0
        # facing a preflop raise: (tier, invested) -> [big] -> [opps, folds, raises]
        self.pf = {key: [[0, 0, 0], [0, 0, 0]] for key in PF_PRIOR}
        self.bet_opp = 0
        self.bet_n = 0
        self.sz_sum = 0.0  # postflop bet/raise sizes (fraction of pot)
        self.sz_n = 0
        self.face = [[0, 0, 0] for _ in range(4)]
        self.pre_chk = 0
        self.pre_bad = 0
        self.post_chk = 0
        self.post_bad = 0

    def vpip_r(self):
        return _est(self.vpip, self.hands, 0.30, 8)

    def open_r(self):
        return _est(self.open_n, self.open_opp, 0.22, 8)

    def _pf(self, L, big, invested):
        key = (1 if L <= 1 else (2 if L == 2 else 3), bool(invested))
        return self.pf[key][big], PF_PRIOR[key][big]

    def pre_tendency(self):
        """(fold, raise) rates relative to the priors, pooled over every
        preflop spot this player faced a raise in."""
        of = ef = orr = er = 0.0
        for key, cells in self.pf.items():
            for big in (0, 1):
                a = cells[big]
                if a[0]:
                    pf, pr = PF_PRIOR[key][big]
                    of += a[1]
                    ef += a[0] * pf
                    orr += a[2]
                    er += a[0] * pr
        return (of + POOL_K) / (ef + POOL_K), (orr + POOL_K) / (er + POOL_K)

    def pre_fold(self, L, big, invested):
        a, pr = self._pf(L, big, invested)
        prior = min(0.99, pr[0] * self.pre_tendency()[0])
        return _est(a[1], a[0], prior, 6)

    def pre_raise(self, L, big, invested):
        a, pr = self._pf(L, big, invested)
        prior = min(0.95, pr[1] * self.pre_tendency()[1])
        return _est(a[2], a[0], prior, 6)

    def size_factor(self, sz):
        """Multiplier on this player's betting frequency for a bet of size
        `sz` (fraction of the pot), from their own average bet size."""
        if sz <= 0 or SIZE_TELL <= 0:
            return 1.0
        avg = (self.sz_sum + 0.6 * 3) / (self.sz_n + 3)
        return min(1.5, max(0.5, (avg / min(sz, 3.0)) ** SIZE_TELL))

    def bet_r(self):
        return _est(self.bet_n, self.bet_opp, 0.38, 8)

    def post_fold(self, b):
        tot = self.face[0][0] + self.face[1][0] + self.face[2][0] + self.face[3][0]
        fl = self.face[0][1] + self.face[1][1] + self.face[2][1] + self.face[3][1]
        prior = min(0.95, max(0.02, _est(fl, tot, POST_FOLD_BASE, 6) + POST_FOLD_SHIFT[b]))
        a = self.face[b]
        return _est(a[1], a[0], prior, 5)

    def post_raise(self, b):
        tot = self.face[0][0] + self.face[1][0] + self.face[2][0] + self.face[3][0]
        rs = self.face[0][2] + self.face[1][2] + self.face[2][2] + self.face[3][2]
        prior = _est(rs, tot, POST_RAISE_BASE, 6)
        a = self.face[b]
        return _est(a[2], a[0], prior, 5)

    def eps_pre(self):
        return _est(self.pre_bad, self.pre_chk, 0.06, 8)

    def eps_post(self):
        return _est(self.post_bad, self.post_chk, BLUFF_PRIOR, 8)


# --------------------------------------------------------------------------
# Hand replay: rebuild betting context for every action of a hand.
# --------------------------------------------------------------------------
def replay(history, n, button, sb, bb):
    """Return (records, final) where each record is
    (street, seat, kind, amount, raises_before, to_call, last_raise_size,
    last_raise_to, voluntarily_in_preflop_before, own_raise_size)."""
    if n == 2:
        sbs, bbs = button % n, (button + 1) % n
    else:
        sbs, bbs = (button + 1) % n, (button + 2) % n
    bets = [0] * n
    bets[sbs] += sb
    bets[bbs] += bb
    pot = sb + bb
    cur = bb
    street = "preflop"
    L = 0
    last_size = 0.0
    last_to = bb
    vol = [False] * n
    recs = []
    for h in history:
        st, seat, kind, amt = h[0], int(h[1]), h[2], int(h[3])
        if st != street:
            street = st
            bets = [0] * n
            cur = 0
            L = 0
            last_size = 0.0
            last_to = 0
        tc = cur - bets[seat]
        if tc < 0:
            tc = 0
        sz = (amt - cur) / max(1.0, float(pot + tc)) if kind == "raise" else 0.0
        recs.append((st, seat, kind, amt, L, tc, last_size, last_to, vol[seat], sz))
        if kind == "call":
            bets[seat] += amt
            pot += amt
            if st == "preflop":
                vol[seat] = True
        elif kind == "raise":
            last_size = (amt - cur) / max(1.0, float(pot + tc))
            pot += amt - bets[seat]
            bets[seat] = amt
            if amt > cur:
                cur = amt
            L += 1
            last_to = amt
            if st == "preflop":
                vol[seat] = True
    return recs, (street, L, last_size, last_to, vol)


def _is_air(hole, board):
    """True when the hole cards add nothing to the board (no pair, no
    straight/flush, and before the river no real draw)."""
    hr = [c >> 2 for c in hole]
    br = [c >> 2 for c in board]
    if hr[0] == hr[1] or hr[0] in br or hr[1] in br:
        return False
    cards = hole + board
    if (hand_value(cards) >> 20) >= 4:
        return False
    if len(board) < 5:
        sc = [0, 0, 0, 0]
        for c in cards:
            sc[c & 3] += 1
        for c in hole:
            if sc[c & 3] >= 4:
                return False
        bm = 0
        for r in br:
            bm |= 1 << r
        m = bm | (1 << hr[0]) | (1 << hr[1])
        if _popcount(_outs(m) & ~_outs(bm)) >= 2:
            return False
    return True


class _Table:
    """All unknown two-card combos for one decision, with their strength
    percentile `pp` (0 weakest, 1 strongest) on the current board."""

    __slots__ = ("CA", "CB", "CL", "PP", "ORD", "PPS", "V", "myv", "unk")


def _pre_table(hole):
    t = _Table()
    unk = [c for c in range(52) if c not in hole]
    CA, CB, CL = [], [], []
    for i in range(len(unk)):
        a = unk[i]
        for j in range(i + 1, len(unk)):
            b = unk[j]
            CA.append(a)
            CB.append(b)
            CL.append(CLS[a * 52 + b])
    t.CA, t.CB, t.CL = CA, CB, CL
    t.PP = [1.0 - Q[c] for c in CL]
    t.ORD = sorted(range(len(CL)), key=t.PP.__getitem__)
    t.PPS = [t.PP[j] for j in t.ORD]
    t.V = None
    t.myv = 0
    t.unk = unk
    return t


def _post_table(hole, board):
    t = _Table()
    known = set(hole) | set(board)
    unk = [c for c in range(52) if c not in known]
    key, br, fs, fcnt, frk = _board_parts(board)
    CA, CB, CL, V = [], [], [], []
    for i in range(len(unk)):
        a = unk[i]
        for j in range(i + 1, len(unk)):
            b = unk[j]
            CA.append(a)
            CB.append(b)
            CL.append(CLS[a * 52 + b])
            V.append(_hv(key, br, fs, fcnt, frk, a, b))
    M = len(V)
    order = sorted(range(M), key=V.__getitem__)
    PP = [0.0] * M
    i = 0
    while i < M:
        j = i
        v = V[order[i]]
        while j + 1 < M and V[order[j + 1]] == v:
            j += 1
        p = ((i + j) / 2.0 + 0.5) / M
        for k in range(i, j + 1):
            PP[order[k]] = p
        i = j + 1
    nb = len(board)
    if nb < 5:
        bmask = 0
        bsc = [0, 0, 0, 0]
        for c in board:
            bmask |= 1 << (c >> 2)
            bsc[c & 3] += 1
        bouts = _outs(bmask)
        if nb == 3:
            d_combo, d_fd, d_oe, d_gs = 0.80, 0.62, 0.56, 0.36
        else:
            d_combo, d_fd, d_oe, d_gs = 0.66, 0.50, 0.46, 0.28
        for k in range(M):
            if V[k] >= 0x400000:
                continue
            a = CA[k]
            b = CB[k]
            sa = a & 3
            sb = b & 3
            if sa == sb:
                fd = bsc[sa] + 2 == 4
            else:
                fd = bsc[sa] + 1 == 4 or bsc[sb] + 1 == 4
            o = _outs(bmask | (1 << (a >> 2)) | (1 << (b >> 2))) & ~bouts
            so = _popcount(o) if o else 0
            if fd and so >= 2:
                dv = d_combo
            elif fd and so == 1:
                dv = (d_combo + d_fd) / 2.0
            elif fd:
                dv = d_fd
            elif so >= 2:
                dv = d_oe
            elif so == 1:
                dv = d_gs
            else:
                continue
            p = PP[k]
            PP[k] = dv + 0.02 * p if p < dv else min(0.999, p + 0.06)
    t.CA, t.CB, t.CL, t.PP, t.V = CA, CB, CL, PP, V
    t.ORD = sorted(range(M), key=PP.__getitem__)
    t.PPS = [PP[j] for j in t.ORD]
    t.myv = _hv(key, br, fs, fcnt, frk, hole[0], hole[1])
    t.unk = unk
    return t


class _Opp:
    __slots__ = ("seat", "st", "W", "cw", "acc", "eps", "inv")


# Equity realisation factors, (out of position, in position).
R_PASSIVE = {"preflop": (0.78, 0.88), "flop": (0.88, 0.95), "turn": (0.93, 0.97), "river": (0.96, 1.0)}
R_AGGR = {"preflop": (0.76, 0.90), "flop": (0.94, 0.98), "turn": (0.97, 0.99), "river": (1.0, 1.0)}
# Opening thresholds (fraction of hands) by number of players still to act.
OPEN_BASE = {1: 0.48, 2: 0.38, 3: 0.28, 4: 0.21, 5: 0.16, 6: 0.14, 7: 0.13, 8: 0.12}
TRIALS = {"preflop": 640, "flop": 960, "turn": 960, "river": 1800}
UTIL_MARGIN = 0.05  # game points needed to override the chip-EV choice
BET_FRACS = (0.33, 0.6, 0.9, 1.4)  # bet sizes as a fraction of the pot
RAISE_FRACS = (0.6, 1.0)  # raise sizes as a fraction of the pot after calling
SIZE_PENALTY = 0.07  # chips of EV charged per chip bet, against model error


class Cartographer(Bot):
    def __init__(self):
        self.stats = {}
        self.pid = None
        self.sb = 1
        self.bb = 2
        self.stack = 200
        self.num_hands = 100
        self.hand_no = None
        self.button = 0
        self.events = []
        self.hand_players = None
        self.last_clock = 30000
        self._pre_cache = None
        self._post_cache = None
        self.totals = {}  # player id -> net chips so far this game
        self.hands_done = 0
        self.sq_sum = 0.0
        self.sq_n = 0

    # ------------------------------------------------------------ observers
    def on_match_start(self, info):
        try:
            if info.get("player") is not None:
                self.pid = info.get("player")
            bl = info.get("blinds") or [1, 2]
            self.sb, self.bb = int(bl[0]), int(bl[1])
            self.num_hands = int(info.get("num_hands", 100))
            self.stack = int(info.get("stack", 200))
        except Exception:
            pass

    def on_hand_start(self, info):
        try:
            self.hand_no = info.get("hand")
            self.events = []
            self.button = info.get("button", 0) or 0
            if info.get("players") is not None:
                self.hand_players = list(info.get("players"))
        except Exception:
            pass

    def on_action(self, event):
        try:
            if event.get("hand") != self.hand_no:
                self.hand_no = event.get("hand")
                self.events = []
            self.events.append(
                (event["street"], int(event["seat"]), event["action"], int(event.get("amount", 0) or 0))
            )
            if event.get("players") is not None:
                self.hand_players = list(event.get("players"))
        except Exception:
            pass

    def on_street(self, event):
        try:
            if event.get("players") is not None:
                self.hand_players = list(event.get("players"))
        except Exception:
            pass

    def on_hand_end(self, info):
        try:
            players = info.get("players") or self.hand_players
            if players:
                players = list(players)
                n = len(players)
                deltas = info.get("deltas") or []
                for s in range(min(n, len(deltas))):
                    d = int(deltas[s])
                    self.totals[players[s]] = self.totals.get(players[s], 0) + d
                    self.sq_sum += d * d
                    self.sq_n += 1
                self.hands_done += 1
                recs, _ = replay(self.events, n, self.button, self.sb, self.bb)
                self._update_stats(recs, players, n)
                if self.last_clock > 4000:
                    self._showdown_learn(recs, players, info)
        except Exception:
            pass
        self.events = []

    def _opp(self, pid):
        o = self.stats.get(pid)
        if o is None:
            o = self.stats[pid] = OppStats()
        return o

    def _big(self, L, to):
        return 1 if to >= (10 if L <= 1 else 30) * self.bb else 0

    def _update_stats(self, recs, players, n):
        vp = [False] * n
        open_seen = [False] * n
        for st, seat, kind, amt, L, tc, ls, lt, inv, sz in recs:
            if seat >= n:
                continue
            pid = players[seat]
            if pid == self.pid:
                continue
            o = self._opp(pid)
            if st == "preflop":
                if kind in ("call", "raise"):
                    vp[seat] = True
                if L == 0:
                    if not open_seen[seat]:
                        open_seen[seat] = True
                        o.open_opp += 1
                        if kind == "raise":
                            o.open_n += 1
                else:
                    a, _ = o._pf(L, self._big(L, lt), inv)
                    a[0] += 1
                    if kind == "fold":
                        a[1] += 1
                    elif kind == "raise":
                        a[2] += 1
            elif tc > 0:
                a = o.face[size_bucket(ls)]
                a[0] += 1
                if kind == "fold":
                    a[1] += 1
                elif kind == "raise":
                    a[2] += 1
            else:
                o.bet_opp += 1
                if kind == "raise":
                    o.bet_n += 1
            if st != "preflop" and kind == "raise":
                o.sz_sum += min(sz, 3.0)
                o.sz_n += 1
        for s in range(n):
            pid = players[s]
            if pid == self.pid:
                continue
            o = self._opp(pid)
            o.hands += 1
            if vp[s]:
                o.vpip += 1

    def _showdown_learn(self, recs, players, info):
        revealed = info.get("revealed") or {}
        board = [parse_card(c) for c in (info.get("board") or [])]
        for key, cards in revealed.items():
            s = int(key)
            if s >= len(players) or players[s] == self.pid or not cards or len(cards) != 2:
                continue
            o = self._opp(players[s])
            hole = [parse_card(c) for c in cards]
            q = hole_q(hole)
            for st, seat, kind, amt, L, tc, ls, lt, inv, _sz in recs:
                if st != "preflop" or seat != s:
                    continue
                if kind == "raise":
                    r = o.open_r() if L == 0 else o.pre_raise(L, self._big(L, lt), inv)
                    o.pre_chk += 1
                    if q > r * 1.5 + 0.06:
                        o.pre_bad += 1
                    break
                if kind == "call" and L >= 1:
                    cont = 1.0 - o.pre_fold(L, self._big(L, lt), inv)
                    o.pre_chk += 1
                    if q > cont * 1.4 + 0.08:
                        o.pre_bad += 1
                    break
            seen = set()
            for st, seat, kind, amt, L, tc, ls, lt, inv, _sz in recs:
                if st == "preflop" or seat != s or kind != "raise" or st in seen:
                    continue
                seen.add(st)
                nb = 3 if st == "flop" else (4 if st == "turn" else 5)
                if len(board) < nb:
                    continue
                o.post_chk += 1
                if _is_air(hole, board[:nb]):
                    o.post_bad += 1

    # ------------------------------------------------------------ acting
    def act(self, state):
        t0 = time.perf_counter()
        try:
            self.last_clock = state.clock_ms
            if self.pid is None:
                self.pid = state.player
            action = self._decide(state, t0)
            if action is not None:
                return action
        except Exception:
            pass
        return self._safe(state)

    @staticmethod
    def _safe(state):
        return state.check() if state.to_call == 0 else state.fold()

    @staticmethod
    def _raise(state, amount):
        if not state.can_raise:
            return state.call() if state.to_call > 0 else state.check()
        hi = state.max_raise_to
        amount = int(amount)
        if amount >= hi:
            return state.raise_to(hi)
        return state.raise_to(max(state.min_raise_to, amount))

    def _decide(self, state, t0):
        n = state.num_players
        hole = [parse_card(c) for c in state.hole]
        board = [parse_card(c) for c in state.board]
        clock = state.clock_ms
        hands_left = max(1, self.num_hands - state.hand)
        per_hand = (clock - 2000.0) / hands_left + 100.0
        if clock < 2500 or per_hand < 20:
            return self._fast(state, hole, board)
        budget = min(0.07, max(0.004, per_hand * 0.3 / 1000.0))
        deadline = t0 + budget
        recs, fin = replay(state.history, n, state.button, self.sb, self.bb)
        street = state.street
        if fin[0] == street:
            L, last_size, last_to = fin[1], fin[2], fin[3]
        else:
            L, last_size, last_to = 0, 0.0, 0
        vol = fin[4]
        pre_acts = [[] for _ in range(n)]
        post_acts = [[] for _ in range(n)]
        for st, seat, kind, amt, rl, tc, ls, lt, inv, sz in recs:
            if seat >= n:
                continue
            if st == "preflop":
                pre_acts[seat].append((kind, rl, self._big(rl, lt), inv))
            else:
                post_acts[seat].append((st, kind, tc > 0, size_bucket(ls) if tc > 0 else 0, sz))
        me = state.seat
        opp_seats = [s for s in range(n) if s != me and not state.folded[s]]
        if not opp_seats:
            return state.check() if state.to_call == 0 else state.call()
        if street == "preflop":
            q = hole_q(hole)
            if L == 0:
                return self._unopened(state, q, recs)
            key = (hole[0], hole[1])
            if self._pre_cache is None or self._pre_cache[0] != key:
                self._pre_cache = (key, _pre_table(hole))
            T = self._pre_cache[1]
        else:
            key = (hole[0], hole[1], tuple(board))
            if self._post_cache is None or self._post_cache[0] != key:
                self._post_cache = (key, _post_table(hole, board))
            T = self._post_cache[1]
        opps = []
        for s in opp_seats:
            o = _Opp()
            o.seat = s
            o.st = self._opp(state.player_at(s))
            o.inv = vol[s]
            W = self._pre_weights(o.st, pre_acts[s], T)
            if street != "preflop":
                W = self._post_narrow(W, T, o.st, post_acts[s], street)
                o.eps = o.st.eps_post()
            else:
                o.eps = o.st.eps_pre()
            tot = sum(W)
            if not tot > 0:
                W = [1.0] * len(W)
            o.W = W
            o.cw = list(accumulate(W))
            o.acc = list(accumulate([W[j] for j in T.ORD]))
            opps.append(o)
        trials = TRIALS[street]
        if street != "river" and len(opps) >= 3:
            trials = int(trials * 0.7)
        if street == "preflop" and q > 0.6:
            trials = 400
        rows = self._simulate(T, hole, board, opps, trials, deadline)
        if len(rows) < 40:
            return self._fast(state, hole, board)
        return self._choose(state, street, T, opps, rows, L, last_size, last_to)

    # ------------------------------------------------------------ preflop chart
    def _unopened(self, state, q, recs):
        n = state.num_players
        me = state.seat
        b = state.button
        if n == 2:
            order = [b % n, (b + 1) % n]
        else:
            order = [(b + 3 + i) % n for i in range(n)]
        idx = order.index(me)
        behind = [s for s in order[idx + 1:] if not state.folded[s]]
        limpers = sum(1 for r in recs if r[0] == "preflop" and r[2] == "call")
        bb_seat = (b + 1) % n if n == 2 else (b + 2) % n
        sb_seat = b % n if n == 2 else (b + 1) % n
        to_call = state.to_call
        bb = self.bb
        if limpers == 0 and to_call > 0:
            k = max(1, len(behind))
            thr = OPEN_BASE.get(k, 0.10)
            if n == 2:
                thr = 0.62
            folds = [self._opp(state.player_at(s)).pre_fold(1, 0, False) for s in behind]
            avg_f = sum(folds) / len(folds) if folds else 0.6
            thr *= min(1.3, max(0.8, 1.0 + 0.8 * (avg_f - 0.6)))
            p_steal = 1.0
            for f in folds:
                p_steal *= f
            size = int(2.5 * bb) if (me != sb_seat or n == 2) else 3 * bb
            A = size - state.street_bets[me]
            steal_ev = p_steal * state.pot - (1.0 - p_steal) * A * (0.25 + 0.55 * q)
            if q <= thr or steal_ev > 0.15 * bb:
                return self._raise(state, size)
            return state.fold()
        # limped pot (or big blind with the option)
        late = len(behind) <= 2
        iso_thr = 0.10 + (0.03 if late else 0.0)
        if q <= iso_thr and state.can_raise:
            size = bb * (3 + limpers) + (bb if me in (sb_seat, bb_seat) else 0)
            return self._raise(state, size)
        if to_call == 0:
            return state.check()
        if me == sb_seat and to_call <= bb and q <= 0.55:
            return state.call()
        if to_call <= bb and q <= 0.22 + 0.02 * limpers:
            return state.call()
        return state.fold()

    # ------------------------------------------------------------ ranges
    def _pre_weights(self, o, acts, T):
        rtop = 1.0
        cap = 0.0
        capw = 0.0
        vp = o.vpip_r()
        for kind, L, big, inv in acts:
            if kind == "raise":
                fr = o.open_r() if L == 0 else o.pre_raise(L, big, inv)
                rtop = max(0.025, rtop * fr)
                if vp >= VPIP_FLOOR:
                    rtop = max(rtop, 0.95 * vp)
                capw = 0.0
            elif kind == "call":
                if L == 0:
                    rtop = min(rtop, max(0.10, o.vpip_r()))
                    cap = o.open_r() * 0.7
                    capw = 0.55
                else:
                    fr = o.pre_raise(L, big, inv)
                    ff = o.pre_fold(L, big, inv)
                    cap = rtop * fr
                    capw = 0.6
                    rtop = max(0.04, rtop * (1.0 - ff))
            elif kind == "check":
                cap = o.open_r() * 0.6
                capw = 0.5
        eps = o.eps_pre()
        full = rtop >= 0.995
        wd = 0.02 + 0.12 * rtop
        wc = 0.02 + 0.12 * cap
        nq = len(Q)
        raw = [1.0] * nq
        mass = 0.0
        for k in range(nq):
            qk = Q[k]
            w = 1.0 if full else _sig((rtop - qk) / wd)
            if capw > 0.0:
                w *= 1.0 - capw * _sig((cap - qk) / wc)
            raw[k] = w
            mass += w * CLASS_COMBOS[k]
        # mixture: (1 - eps) of the weight from the modelled range, eps uniform
        scale = (1.0 - eps) * 1326.0 / max(mass, 1e-9)
        cwts = [eps + scale * w for w in raw]
        return [cwts[c] for c in T.CL]

    def _post_narrow(self, W, T, o, acts, cur_street):
        PP = T.PP
        ORD = T.ORD
        PPS = T.PPS
        M = len(W)
        eps = o.eps_post()
        for st, kind, facing, b, sz in acts:
            if kind not in ("raise", "call", "check"):
                continue
            acc = list(accumulate([W[j] for j in ORD]))
            tot = acc[-1]
            if not tot > 0:
                break

            def qt(f):
                if f <= 0.0:
                    return -1.0
                if f >= 1.0:
                    return 2.0
                j = bisect_left(acc, f * tot)
                return PPS[min(j, M - 1)]

            if kind == "raise" or kind == "call":
                if kind == "raise":
                    a = o.post_raise(b) if facing else o.bet_r()
                    a = min(1.0, a * o.size_factor(sz))
                    t = qt(1.0 - a)
                    inr = [_sig((PP[k] - t) / 0.07) for k in range(M)]
                    beta = eps  # share of bets that are bluffs from the bottom
                else:
                    tl = qt(o.post_fold(b))
                    th = qt(1.0 - o.post_raise(b))
                    inr = [
                        _sig((PP[k] - tl) / 0.07) * (1.0 - 0.45 * _sig((PP[k] - th) / 0.07))
                        for k in range(M)
                    ]
                    beta = 0.08  # share of calls made with hands below the line
                s_in = 0.0
                s_out = 0.0
                for k in range(M):
                    s_in += W[k] * inr[k]
                    s_out += W[k] * (1.0 - inr[k])
                a_in = (1.0 - beta) * tot / max(s_in, 1e-9)
                a_out = beta * tot / max(s_out, 1e-9)
                fac = [a_in * inr[k] + a_out * (1.0 - inr[k]) for k in range(M)]
            else:
                th = qt(1.0 - 0.6 * o.bet_r())
                fac = [1.0 - 0.45 * _sig((PP[k] - th) / 0.07) for k in range(M)]
            if st == cur_street:
                W = [W[k] * fac[k] for k in range(M)]
            else:
                W = [W[k] * fac[k] ** 0.55 for k in range(M)]
        return W

    # ------------------------------------------------------------ simulation
    def _simulate(self, T, hole, board, opps, trials, deadline):
        CA, CB, PP = T.CA, T.CB, T.PP
        M = len(CA)
        nopp = len(opps)
        need = 5 - len(board)
        unk = T.unk
        nu = len(unk)
        rnd = random.random
        K = min(int(trials * 1.4) + 24, 1200)  # refilled lazily when used up
        pop = range(M)
        pools = [random.choices(pop, cum_weights=o.cw, k=K) for o in opps]
        ptr = [0] * nopp
        rows = []
        key0 = 1
        for c in board:
            key0 *= CPRIME[c]
        br0 = [c >> 2 for c in board]
        ma, mb = hole[0], hole[1]
        V = T.V
        myv = T.myv
        fails = 0
        perf = time.perf_counter
        for t in range(trials):
            if (t & 31) == 31 and t >= 63 and perf() > deadline:
                break
            used = []
            picks = []
            ok = True
            for i in range(nopp):
                pool = pools[i]
                p = ptr[i]
                tries = 0
                while True:
                    if p >= K:
                        pool = pools[i] = random.choices(pop, cum_weights=opps[i].cw, k=K)
                        p = 0
                    j = pool[p]
                    p += 1
                    a = CA[j]
                    b = CB[j]
                    if a not in used and b not in used:
                        break
                    tries += 1
                    if tries > 40:
                        ok = False
                        break
                ptr[i] = p
                if not ok:
                    break
                used.append(a)
                used.append(b)
                picks.append(j)
            if not ok:
                fails += 1
                if fails > trials:
                    break
                continue
            row = []
            if need == 0:
                for j in picks:
                    ov = V[j]
                    row.append((PP[j], 1.0 if myv > ov else (0.5 if myv == ov else 0.0), rnd(), rnd()))
            else:
                run = []
                while len(run) < need:
                    c = unk[int(rnd() * nu)]
                    if c not in used and c not in run:
                        run.append(c)
                full = board + run
                key = key0
                for c in run:
                    key *= CPRIME[c]
                br = br0 + [c >> 2 for c in run]
                sc = [0, 0, 0, 0]
                for c in full:
                    sc[c & 3] += 1
                fs = -1
                for s in range(4):
                    if sc[s] >= 3:
                        fs = s
                        break
                if fs >= 0:
                    fcnt = sc[fs]
                    frk = [c >> 2 for c in full if c & 3 == fs]
                else:
                    fcnt = 0
                    frk = None
                mv = _hv(key, br, fs, fcnt, frk, ma, mb)
                for j in picks:
                    ov = _hv(key, br, fs, fcnt, frk, CA[j], CB[j])
                    row.append((PP[j], 1.0 if mv > ov else (0.5 if mv == ov else 0.0), rnd(), rnd()))
            rows.append(row)
        return rows

    # ------------------------------------------------------------ decision
    def _options(self, state, street, L, ip, opps):
        me = state.seat
        sbets = state.street_bets
        my_bet = sbets[me]
        my_stack = state.my_stack
        to_call = state.to_call
        P = state.pot
        cur = max(sbets)
        opts = []
        if to_call > 0:
            opts.append(("fold", my_bet, 0))
            opts.append(("call", cur, min(to_call, my_stack)))
        else:
            opts.append(("check", my_bet, 0))
        if state.can_raise and my_stack > to_call:
            lo, hi = state.min_raise_to, state.max_raise_to
            levels = []
            if street == "preflop":
                callers = sum(1 for o in opps if sbets[o.seat] == cur) - 1
                if L <= 1:
                    mult = 3.0 if ip else 3.6
                else:
                    mult = 2.3
                levels.append(cur * mult + max(0, callers) * cur)
            elif to_call == 0:
                for f in BET_FRACS:
                    levels.append(my_bet + f * P)
            else:
                for f in RAISE_FRACS:
                    levels.append(cur + f * (P + to_call))
            levels.append(hi)
            seen = set()
            for lvl in levels:
                lvl = int(round(lvl))
                lvl = max(lo, min(hi, lvl))
                if lvl - my_bet >= 0.8 * my_stack:
                    lvl = hi
                if lvl in seen or lvl <= cur:
                    continue
                seen.add(lvl)
                opts.append(("raise", lvl, lvl - my_bet))
        return opts

    def _fold_p(self, o, kind, lvl, street, L, cur, P, to_call, last_size, last_to, committed):
        st = o.st
        if street == "preflop":
            if kind == "raise":
                Lr = L + 1
                big = self._big(Lr, lvl)
            else:
                Lr = L
                big = self._big(L, last_to)
            if Lr <= 0:
                return 0.0
            f = st.pre_fold(Lr, big, o.inv)
        else:
            if kind == "raise":
                size = (lvl - cur) / max(1.0, float(P + to_call))
            else:
                size = last_size
            f = st.post_fold(size_bucket(size))
            if size > 1.6:
                # big overbets fold out more of a range that folds at all
                f = min(0.97, f * (1.0 + 0.1 * min(5.0, size - 1.6)))
        # players with a large share of their stack already in fold less
        frac = committed / float(max(1, self.stack))
        if frac >= 0.4:
            f *= 0.5
        elif frac >= 0.2:
            f *= 0.75
        return f

    def _choose(self, state, street, T, opps, rows, L, last_size, last_to):
        scored = self._score(state, street, T, opps, rows, L, last_size, last_to)
        if not scored:
            return None
        best, _ev, best_u = max(scored, key=lambda x: x[1])
        if best_u is not None:
            # late in a game, deviate from chip EV only for a clear gain in
            # expected finishing position (game points)
            alt, _aev, alt_u = max(scored, key=lambda x: x[2])
            if alt_u - best_u > UTIL_MARGIN:
                best = alt
        to_call = state.to_call
        kind = best[0]
        if street == "preflop" and kind == "fold" and hole_q_from(state) <= 0.012:
            kind = "call"
        if kind == "fold":
            return state.fold() if to_call > 0 else state.check()
        if kind == "check":
            return state.check()
        if kind == "call":
            return state.call() if to_call > 0 else state.check()
        return self._raise(state, best[1])

    def _score(self, state, street, T, opps, rows, L, last_size, last_to):
        """Expected chip gain of every legal option over the simulated rows."""
        n = state.num_players
        me = state.seat
        sbets = state.street_bets
        stacks = state.stacks
        my_bet = sbets[me]
        my_stack = state.my_stack
        to_call = state.to_call
        P = state.pot
        cur = max(sbets)
        cap = my_bet + my_stack
        Peff = P
        for s in range(n):
            if s != me and sbets[s] > cap:
                Peff -= sbets[s] - cap
        live = [s for s in range(n) if not state.folded[s]]
        ip = max(live, key=lambda s: (s - 1) % n) == me
        opp_max = max(stacks[o.seat] + sbets[o.seat] for o in opps)
        nopp = len(opps)
        PPS = T.PPS
        M = len(PPS)
        options = self._options(state, street, L, ip, opps)
        scored = []
        nrows = float(len(rows))
        # weak hands realise less of their equity, strong ones a little more
        share = 0.0
        for row in rows:
            ties = 0
            for _pp, c, _u1, _u2 in row:
                if c == 0.0:
                    break
                if c == 0.5:
                    ties += 1
            else:
                share += 1.0 / (1 + ties)
        rel = share / nrows * (nopp + 1)
        rmul = min(1.08, max(0.7, 0.85 + 0.15 * rel))
        util = self._utility(state, opps)
        u0 = util(0.0) if util is not None else None
        uev = None
        for opt in options:
            kind, lvl, A = opt
            if kind == "fold":
                ev = 0.0
            else:
                resp = [None] * nopp
                for i, o in enumerate(opps):
                    s = o.seat
                    if stacks[s] <= 0:
                        continue
                    if kind == "raise" or (kind == "call" and sbets[s] < cur):
                        target = lvl if kind == "raise" else cur
                        committed = self.stack - stacks[s]
                        f = self._fold_p(o, kind, lvl, street, L, cur, P, to_call, last_size, last_to, committed)
                        if f <= 0.0:
                            t = -1.0
                        elif f >= 1.0:
                            t = 2.0
                        else:
                            j = bisect_left(o.acc, f * o.acc[-1])
                            t = PPS[min(j, M - 1)]
                        resp[i] = (t, f, o.eps, min(target - sbets[s], stacks[s]))
                if A >= my_stack or lvl >= opp_max:
                    R = 1.0
                elif kind == "raise":
                    R = R_AGGR[street][1 if ip else 0]
                    if street != "river":
                        R *= rmul
                else:
                    R = R_PASSIVE[street][1 if ip else 0]
                    if kind == "call" and street == "river":
                        R = 1.0
                    else:
                        R *= rmul
                    R = max(0.6, R - 0.03 * (nopp - 1))
                tot = 0.0
                utot = 0.0
                for row in rows:
                    win = True
                    ties = 0
                    extra = 0
                    anyin = False
                    for i in range(nopp):
                        pp, c, u1, u2 = row[i]
                        r = resp[i]
                        if r is not None:
                            if u1 < r[2]:
                                if u2 < r[1]:
                                    continue
                            elif pp < r[0]:
                                continue
                            extra += r[3]
                        anyin = True
                        if c == 0.0:
                            win = False
                        elif c == 0.5:
                            ties += 1
                    if not anyin:
                        gain = Peff
                    elif win:
                        gain = R * (Peff + A + extra) / (1 + ties) - A
                    else:
                        gain = -A
                    tot += gain
                    if util is not None:
                        utot += util(gain)
                ev = tot / nrows
                if kind == "raise":
                    # model error grows with bet size: prefer smaller bets on near-ties
                    ev -= 0.012 * P + SIZE_PENALTY * A
                if util is not None:
                    uev = utot / nrows
            if util is not None and kind == "fold":
                uev = u0
            scored.append((opt, ev, uev))
        return scored

    def _utility(self, state, opps):
        """Expected number of opponents we finish this game ahead of, as a
        function of this hand's chip gain from now. Each player's remaining
        hands are modelled as normal noise around their win rate so far.
        Returns None early in a game, where chips are all that matter."""
        h = self.num_hands - state.hand - 1
        if h > 50 or self.pid is None or self.hands_done < 5:
            return None
        n = state.num_players
        me = state.seat
        var = (self.sq_sum + 1600.0 * 50) / (self.sq_n + 50)
        hd = float(self.hands_done)
        my_total = self.totals.get(self.pid, 0)
        mu_me = my_total / (hd + 40.0)
        inv_me = self.stack - state.my_stack
        others = []
        dead = 0
        n_in = 0
        for s in range(n):
            if s == me:
                continue
            pid = state.player_at(s)
            t = self.totals.get(pid, 0)
            t += (t / (hd + 40.0) - mu_me) * h
            if state.folded[s]:
                lost = self.stack - state.stacks[s]
                dead += lost
                others.append((t - lost, False))
            else:
                n_in += 1
                others.append((t, True))
        n_in = max(1, n_in)
        scale = 1.0 / (math.sqrt(2.0 * var * h + 1.0) * 1.41421356)
        erf = math.erf
        memo = {}

        def util(gain):
            k = int(round(gain))
            v = memo.get(k)
            if v is None:
                x = k - inv_me  # our net result for the whole hand
                share = (dead - x) / n_in  # what each opponent still in nets
                mine = my_total + x
                v = 0.0
                for t, live in others:
                    d = mine - (t + share if live else t)
                    v += 0.5 * (1.0 + erf(d * scale))
                memo[k] = v
            return v

        return util

    # ------------------------------------------------------------ fallback
    def _fast(self, state, hole, board):
        to_call = state.to_call
        pot = state.pot
        if not board:
            q = hole_q(hole)
            cur = max(state.street_bets)
            if q <= 0.03 and state.can_raise:
                return self._raise(state, 3 * cur if cur < 20 else state.max_raise_to)
            if to_call == 0:
                return state.check()
            if q <= 0.06 or (q <= 0.15 and to_call <= 3 * self.bb):
                return state.call()
            return state.fold()
        v = hand_value(hole + board)
        cat = v >> 20
        hr = [c >> 2 for c in hole]
        br = [c >> 2 for c in board]
        pair_used = hr[0] == hr[1] or hr[0] in br or hr[1] in br
        if cat >= 2 and (pair_used or cat >= 4):
            if state.can_raise and to_call < pot:
                return self._raise(state, max(state.street_bets) + 0.7 * (pot + to_call))
            return state.call() if to_call > 0 else state.check()
        if cat == 1 and pair_used and to_call <= 0.4 * pot:
            return state.call() if to_call > 0 else state.check()
        return self._safe(state)


def hole_q_from(state):
    try:
        return hole_q([parse_card(c) for c in state.hole])
    except Exception:
        return 1.0
