"""End-to-end tests against the real dataset (uses a temporary bookings file)."""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from busbidder.cli import main
from busbidder.config import PROJECT_ROOT, close_logging

TRIP = ["--to", "Malaga", "--from-date", "2026-07-12", "--to-date", "2026-07-14",
        "--budget", "50", "--max-transfers", "1"]


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = json.loads((PROJECT_ROOT / "config.json").read_text(encoding="utf-8"))
        for key in ("companies_file", "destinations_file", "offers_file", "profiles_file"):
            cfg[key] = str(PROJECT_ROOT / cfg[key])
        for key in ("bookings_file", "log_file", "rejected_file", "review_file"):
            cfg[key] = str(Path(self.tmp.name) / Path(cfg[key]).name)
        self.cfg = Path(self.tmp.name) / "config.json"
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")

    def tearDown(self):
        close_logging()            # Windows cannot delete an open log file
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", str(self.cfg), *args])
        return code, out.getvalue(), err.getvalue()

    def test_validate_reports_rejections(self):
        code, out, _ = self.run_cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("Rejected: 12", out)

    def test_search_example_request(self):
        code, out, _ = self.run_cli("search", *TRIP, "--period", "morning", "--changeable")
        self.assertEqual(code, 0)
        self.assertIn("RECOMMENDATION", out)
        self.assertIn("HARD CONSTRAINTS", out)

    def test_profiles_produce_different_winners(self):
        code, out, _ = self.run_cli("compare", *TRIP)
        self.assertEqual(code, 0)
        summary = out.split("SUMMARY")[1]
        winners = {line.split()[1] for line in summary.splitlines()
                   if line.split()[:1] and line.split()[0] in
                   ("budget", "business", "flex_tourist", "eco")}
        self.assertGreaterEqual(len(winners), 3)

    def test_unknown_destination_gives_error_not_traceback(self):
        code, _, err = self.run_cli("search", "--to", "Paris", "--from-date", "2026-07-12")
        self.assertEqual(code, 1)
        self.assertIn("Unknown destination", err)

    def test_bad_weights_error(self):
        code, _, err = self.run_cli("search", *TRIP, "--weights", "price=50,duration=20")
        self.assertEqual(code, 1)
        self.assertIn("sum", err)

    def test_book_and_cancel_flow(self):
        code, out, _ = self.run_cli("book", "--offer", "VER-AGP-20260712-0710",
                                    "--name", "Test Person")
        self.assertEqual(code, 0)
        ref = next(line.split(":")[1].strip() for line in out.splitlines()
                   if "Reference" in line)
        code, out, _ = self.run_cli("cancel", ref)
        self.assertEqual(code, 0)
        self.assertIn("cancelled", out)

    def test_missing_config(self):
        code, _, err = main_err(["--config", "does_not_exist.json", "validate"])
        self.assertEqual(code, 1)


def main_err(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


if __name__ == "__main__":
    unittest.main()
