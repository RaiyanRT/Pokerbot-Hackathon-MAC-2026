"""Head-to-head between two bots over many duplicate sets.

    python h2h.py bots/gen1/bot_a/main.py bots/gen1/bot_b/main.py [filler ...] [--sets 50] [--deals 100] [--seed h2h] [--subprocess]

With no fillers it is heads-up: the official tie-break format, one game per
seat. Fillers (house:* or main.py paths) seat both bots at a bigger table, so
they are compared against the same field instead. Scored like tournament.py:
chips rank each game into game points, summed per set.
"""

import argparse
import math

from tournament import name, play_table, pts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("fillers", nargs="*")
    p.add_argument("--sets", type=int, default=50)
    p.add_argument("--deals", type=int, default=100)
    p.add_argument("--seed", default="h2h")
    p.add_argument("--subprocess", action="store_true", help="run bots over the real wire protocol")
    args = p.parse_args()
    if args.sets < 1 or args.deals < 1:
        p.error("--sets and --deals must be at least 1")

    specs = [args.a, args.b] + args.fillers
    wins = [0, 0]
    ties = 0
    diffs = []
    chips = [0, 0]
    bad = [set(), set()]
    for k in range(args.sets):
        table_chips, verdicts, _ = play_table(specs, f"{args.seed}:{k}", args)
        gp = [sum(col) for col in zip(*(pts(g) for g in table_chips))]
        diffs.append(gp[0] - gp[1])
        if gp[0] > gp[1]:
            wins[0] += 1
        elif gp[1] > gp[0]:
            wins[1] += 1
        else:
            ties += 1
        for i in (0, 1):
            chips[i] += sum(g[i] for g in table_chips)
            bad[i] |= verdicts[i]
        print(f"set {k + 1}/{args.sets}: game points {gp[0]:g} vs {gp[1]:g}")

    n = len(diffs)
    mean = sum(diffs) / n
    se = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1) / n) if n > 1 else float("nan")
    a, b = name(args.a), name(args.b)
    table = "heads-up" if not args.fillers else f"{len(specs)}-seat with {', '.join(name(f) for f in args.fillers)}"
    print(f"\n{n} sets, {table}")
    print(f"sets won: {a} {wins[0]}, {b} {wins[1]}, tied {ties}")
    print(f"game points per set, {a} minus {b}: {mean:+.2f} (standard error {se:.2f})")
    print(f"chips: {a} {chips[0]:+d}, {b} {chips[1]:+d}")
    for spec, v in zip((a, b), bad):
        if v:
            print(f"verdicts for {spec}: {' '.join(sorted(v))}")
    if n > 1 and abs(mean) < 2 * se:
        print("difference is within about two standard errors: not a clear winner, run more sets")


if __name__ == "__main__":
    main()
