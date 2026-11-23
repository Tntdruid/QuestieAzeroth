"""The overlay generator keeps its stock AzerothCore runs while AzerothCore and the generators are unchanged.

Each export ran every generator twice, against stock AzerothCore and against the live server: two hours, half of it
on the stock side that only changes with AzerothCore itself. The stock output is now reused while its key matches.
"""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _test_paths  # noqa: F401
import generate_ip_overlay as overlay


class StockCacheTest(unittest.TestCase):
    def build(self, work_dir, revision):
        args = argparse.Namespace(acore_source=Path("acore"), map_difficulty_dbc=None, reuse=False)
        ran = []

        def fake_run(command):
            ran.append(str(command[3]))
            Path(command[5]).write_text("return {}", encoding="utf-8")

        with patch.object(overlay, "acore_revision", return_value=revision), \
                patch.object(overlay, "run", side_effect=fake_run), \
                patch.object(overlay, "parse_module", return_value=("", "", {})), \
                patch.object(overlay, "write_overlay_module"), \
                patch.object(overlay, "revert_entries", return_value={}):
            overlay.build_generated(args, Path("live"), work_dir, "item")
        return ran

    def test_stock_run_is_reused_until_azerothcore_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            work_dir = Path(folder)
            self.assertEqual(self.build(work_dir, "abc\n"), ["acore", "live"], "the first time both run")
            self.assertEqual(self.build(work_dir, "abc\n"), ["live"], "the same AzerothCore: only the live run")
            self.assertEqual(self.build(work_dir, "def\n"), ["acore", "live"], "a new AzerothCore commit: both again")

    def test_without_git_both_always_run(self):
        with tempfile.TemporaryDirectory() as folder:
            work_dir = Path(folder)
            self.build(work_dir, "")
            self.assertEqual(self.build(work_dir, ""), ["acore", "live"], "no key, no reuse")


if __name__ == "__main__":
    unittest.main()
