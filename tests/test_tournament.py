"""Regression check for fair scoring and safe recrowning."""

import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tournament.py"
BOT = "from macpoker import Bot\nclass SameBot(Bot):\n    def act(self, state):\n        return state.check() if not state.to_call else state.fold()\n"


class TournamentTest(unittest.TestCase):
    def test_identical_bots_tie_and_recrown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for letter in "abcde":
                folder = root / "bots" / "gen1" / f"bot_{letter}"
                folder.mkdir(parents=True)
                (folder / "main.py").write_text(BOT)

            command = [sys.executable, str(SCRIPT), "gen1", "--rounds", "1", "--deals", "2", "--seed", "smoke", "--crown"]
            subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
            with (root / "results" / "gen1.csv").open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 5)
            for field in ("avg_placement", "avg_game_points", "league_mbb", "house_mbb"):
                self.assertEqual(len({row[field] for row in rows}), 1, field)

            hof = root / "hall_of_fame"
            shutil.copytree(hof / "gen1_bot_a", hof / "gen1_bot_a.new")
            subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
            self.assertEqual([p.name for p in hof.iterdir()], ["gen1_bot_a"])


if __name__ == "__main__":
    unittest.main()
