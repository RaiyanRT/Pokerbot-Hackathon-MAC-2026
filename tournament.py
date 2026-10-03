"""League runner: rank one generation of bots and crown its champion.

    python tournament.py gen1 [--rounds 20] [--deals 100] [--seed local] [--subprocess] [--crown]

Every candidate in bots/<gen>/*/main.py plays:
  * one fixed table against the 4 house bots (house_mbb: the yardstick across generations)
  * --rounds league tables against 4 random opponents drawn from the other
    candidates, hall_of_fame/*/main.py and the house bots.

Each table is a duplicate set scored like the tournament
(docs.poker.monashcoding.com/game-format/scoring): chips rank each game into
game points, summed game points rank the table into placement points.
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
    # house:random is unseeded by default, which made identical bots score differently
    if spec == "house:random" and not args.subprocess:
        return InProcessTransport(BUILTINS["random"](seed), name=spec)
    return _make_transport(spec, args.subprocess)


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
    p.add_argument("--subprocess", action="store_true", help="real wire protocol (slower, catches hangs)")
    p.add_argument("--crown", action="store_true", help="copy the champion into hall_of_fame/")
    args = p.parse_args()

    # ponytail: in-process mode can't interrupt an infinite loop and shares sys.modules
    # between bots (two bots with a helper of the same filename clash); use --subprocess for both.
    cands = sorted(glob.glob(f"bots/{args.gen}/*/main.py"))
    hof = sorted(glob.glob("hall_of_fame/*/main.py"))
    if not cands:
        raise SystemExit(f"no bots in bots/{args.gen}/*/main.py")
    rng = random.Random(args.seed)
    rows = []
    for c in cands:
        chips, b, m = play_table([c] + HOUSE, f"{args.seed}:house", args)
        house_mbb = sum(g[0] for g in chips) / 2 / (args.deals * len(chips)) * 1000
        bad, ms = set(b[0]), m[0]

        place, game_pts, league_chips = [], [], 0
        pool = [x for x in cands if x != c] + hof + HOUSE
        for r in range(args.rounds):
            chips, b, m = play_table([c] + rng.sample(pool, 4), f"{args.seed}:{r}:{name(c)}", args)
            gp = [sum(col) for col in zip(*(pts(g) for g in chips))]
            place.append(pts(gp)[0])
            game_pts.append(gp[0])
            league_chips += sum(g[0] for g in chips)
            bad |= b[0]
            ms = max(ms, m[0])

        hands = args.rounds * 5 * args.deals
        model_file = os.path.join(os.path.dirname(c), "model.txt")
        model = open(model_file).read().strip() if os.path.exists(model_file) else "?"
        rows.append({
            "gen": args.gen, "bot": name(c), "model": model,
            "avg_placement": round(sum(place) / len(place), 3) if place else 0,
            "avg_game_points": round(sum(game_pts) / len(game_pts), 3) if game_pts else 0,
            "league_mbb": round(league_chips / 2 / max(hands, 1) * 1000, 1),
            "house_mbb": round(house_mbb, 1),
            "ms_per_hand": round(ms, 2),
            "verdicts": " ".join(sorted(bad)) or VERDICT_OK,
        })
        print(f"done {name(c)}")

    rows.sort(key=lambda r: (r["verdicts"] == VERDICT_OK, r["avg_placement"], r["avg_game_points"]), reverse=True)
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
    print(f"champion: {champ['bot']} ({champ['model']})")
    if args.crown:
        dst = f"hall_of_fame/{args.gen}_{os.path.basename(champ['bot'])}"
        shutil.copytree(champ["bot"], dst, dirs_exist_ok=True)
        print(f"crowned -> {dst}")


if __name__ == "__main__":
    main()
