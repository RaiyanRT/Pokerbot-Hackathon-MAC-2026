"""League runner: rank one generation of bots and crown its champion.

    python tournament.py gen1 [--rounds 20] [--deals 100] [--seed local] [--subprocess] [--crown]

Every candidate in bots/<gen>/*/main.py faces the same tests. Each round has:
  * the candidates' table: all candidates at one table (duplicate deals, so fair)
  * a reference table: each candidate vs the same 4 opponents, same seats, same
    seed, drawn from hall_of_fame/*/main.py (minus this gen's old champion) + house bots.
Plus one fixed table vs the 4 house bots (house_mbb), a yardstick only.

Each table is a duplicate set scored like the tournament
(docs.poker.monashcoding.com/game-format/scoring): chips rank each game into
game points, summed game points rank the table into placement points.

Ranking (fixed in advance): average placement points over every candidates'
and reference table, each table weighted equally; tie-break average game points.
A bot with any TLE/RTE/PV verdict can't be champion.
"""

import argparse
import csv
import glob
import os
import random
import shutil
from dataclasses import replace

from macpoker.bots import BUILTINS
from macpoker.cli import _make_transport
from macpoker.match import VERDICT_OK, MatchConfig, MatchRunner
from macpoker.transport import InProcessTransport

HOUSE = ["house:call", "house:checkfold", "house:allin", "house:random"]


def pts(vals):
    """5..1 style points by rank; ties share the average of the places they cover."""
    return [1 + sum(w < v for w in vals) + 0.5 * (sum(w == v for w in vals) - 1) for v in vals]


def name(spec):
    return spec if spec.startswith("house:") else os.path.relpath(os.path.dirname(spec)).replace("\\", "/")


def transport(spec, seed, args):
    # house bots always run in-process: they're trusted, and it lets house:random
    # be seeded (it's unseeded by default) so every mode is reproducible
    if spec == "house:random":
        return InProcessTransport(BUILTINS["random"](seed), name=spec)
    return _make_transport(spec, args.subprocess and not spec.startswith("house:"))


def play_table(specs, seed, args):
    """One duplicate set: a game per seat over the same decks, fresh bots each game.
    Returns (chips[game][seat], bad verdicts per seat, max ms/hand per seat)."""
    cfg = MatchConfig(seats=len(specs), deals=args.deals, seed=seed)
    budget = cfg.base_time_ms + cfg.increment_ms * cfg.deals
    chips, bad, ms = [], [set() for _ in specs], [0.0] * len(specs)
    for k in range(len(specs)):
        runner = MatchRunner(replace(cfg, offset=k), [transport(s, f"{seed}:{k}:{i}", args) for i, s in enumerate(specs)])
        res = runner.run()
        chips.append(res.chips)
        for i, v in enumerate(res.verdicts):
            if v != VERDICT_OK:
                bad[i].add(v)
            ms[i] = max(ms[i], (budget - runner.banks_ms[i]) / cfg.deals)
    return chips, bad, ms


def main():
    p = argparse.ArgumentParser()
    p.add_argument("gen")
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--deals", type=int, default=100)
    p.add_argument("--seed", default="local")
    p.add_argument("--subprocess", action="store_true", help="run your bots over the real wire protocol (slower, catches hangs)")
    p.add_argument("--crown", action="store_true", help="make the champion this gen's hall_of_fame entry")
    args = p.parse_args()
    if args.rounds < 1 or args.deals < 1:
        p.error("--rounds and --deals must be at least 1")

    # ponytail: in-process mode can't interrupt an infinite loop and shares sys.modules
    # between bots (two bots with a helper of the same filename clash); use --subprocess for both.
    cands = sorted(glob.glob(f"bots/{args.gen}/*/main.py"))
    if not cands:
        raise SystemExit(f"no bots in bots/{args.gen}/*/main.py")
    if len(cands) > 9:
        raise SystemExit("the candidates' table holds at most 9 bots")
    # this gen's old champion (from an earlier --crown) must not judge its own generation
    old = glob.glob(f"hall_of_fame/{args.gen}_*")
    ref_pool = [h for h in sorted(glob.glob("hall_of_fame/*/main.py")) if os.path.dirname(h) not in old] + HOUSE
    rng = random.Random(args.seed)

    stats = [{"place": [], "gp": [], "chips": 0, "hands": 0, "bad": set(), "ms": 0.0} for _ in cands]

    def record(i, table, seat):
        chips, bad, ms = table
        gp = [sum(col) for col in zip(*(pts(g) for g in chips))]
        s = stats[i]
        s["place"].append(pts(gp)[seat])
        s["gp"].append(gp[seat])
        s["chips"] += sum(g[seat] for g in chips)
        s["hands"] += len(chips) * args.deals
        s["bad"] |= bad[seat]
        s["ms"] = max(s["ms"], ms[seat])

    for r in range(args.rounds):
        if len(cands) > 1:
            table = play_table(cands, f"{args.seed}:{r}:cands", args)
            for i in range(len(cands)):
                record(i, table, i)
        opps = rng.sample(ref_pool, 4)  # same opponents, seats and seed for every candidate
        for i, c in enumerate(cands):
            record(i, play_table([c] + opps, f"{args.seed}:{r}:ref", args), 0)
        print(f"round {r + 1}/{args.rounds} done")

    rows = []
    for c, s in zip(cands, stats):
        chips, bad, ms = play_table([c] + HOUSE, f"{args.seed}:house", args)
        model_file = os.path.join(os.path.dirname(c), "model.txt")
        model = open(model_file).read().strip() if os.path.exists(model_file) else "?"
        rows.append({
            "gen": args.gen, "bot": name(c), "model": model,
            "avg_placement": round(sum(s["place"]) / len(s["place"]), 3),
            "avg_game_points": round(sum(s["gp"]) / len(s["gp"]), 3),
            "league_mbb": round(s["chips"] / 2 / s["hands"] * 1000, 1),
            "house_mbb": round(sum(g[0] for g in chips) / 2 / (len(chips) * args.deals) * 1000, 1),
            "ms_per_hand": round(max(s["ms"], ms[0]), 2),
            "verdicts": " ".join(sorted(s["bad"] | bad[0])) or VERDICT_OK,
        })

    key = lambda r: (r["verdicts"] == VERDICT_OK, r["avg_placement"], r["avg_game_points"])
    rows.sort(key=key, reverse=True)
    print(f"\n{'bot':<22}{'model':<14}{'place':>7}{'gamepts':>9}{'league':>9}{'house':>9}{'ms/hand':>9}  verdicts")
    for r in rows:
        print(f"{r['bot']:<22}{r['model']:<14}{r['avg_placement']:>7}{r['avg_game_points']:>9}"
              f"{r['league_mbb']:>9}{r['house_mbb']:>9}{r['ms_per_hand']:>9}  {r['verdicts']}")

    os.makedirs("results", exist_ok=True)
    with open(f"results/{args.gen}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote results/{args.gen}.csv")

    champ = rows[0]
    if champ["verdicts"] != VERDICT_OK:
        raise SystemExit("no bot finished every game cleanly; no champion")
    if len(rows) > 1 and key(rows[1]) == key(champ):
        print("WARNING: exact tie for first; champion picked alphabetically.")
    print(f"champion: {champ['bot']} ({champ['model']})")
    if args.crown:
        # copy first, then swap out the old entry, so a failure never leaves the gen without a champion
        dst = f"hall_of_fame/{args.gen}_{os.path.basename(champ['bot'])}"
        shutil.copytree(champ["bot"], dst + ".new", dirs_exist_ok=True)
        for o in old:
            shutil.rmtree(o)
        os.replace(dst + ".new", dst)
        print(f"crowned -> {dst}")


if __name__ == "__main__":
    main()
