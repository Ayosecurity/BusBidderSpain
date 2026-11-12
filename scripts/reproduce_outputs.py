"""Regenerate every output example used as evidence in the report.

Run from the project root:   python scripts/reproduce_outputs.py
Results are written to outputs/*.txt. Bookings made here use a temporary
state file, so your real data/state/bookings.json is not touched.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from busbidder.cli import main  # noqa: E402

OUT = ROOT / "outputs"
MALAGA = ["--to", "Malaga", "--from-date", "2026-07-12", "--to-date", "2026-07-14"]
EXAMPLE = MALAGA + ["--budget", "50", "--period", "morning", "--max-transfers", "1",
                    "--changeable"]

RUNS = {
    "01_validation.txt": ["validate"],
    "02_example_request.txt": ["search", *EXAMPLE, "--top", "0"],
    "03_profiles_malaga.txt": ["compare", *MALAGA, "--budget", "50", "--max-transfers", "1"],
    "04_profiles_barcelona.txt": ["compare", "--to", "Barcelona", "--from-date", "2026-07-10",
                                  "--to-date", "2026-07-16", "--budget", "70"],
    "05_sensitivity_example.txt": ["sensitivity", *EXAMPLE],
    "08_profiles_bilbao.txt": ["compare", "--to", "Bilbao", "--from-date", "2026-07-10",
                               "--to-date", "2026-07-12", "--budget", "45"],
    "06_minmax_vs_robust_toledo.txt": None,   # special, see below
    "07_booking_demo.txt": None,
}


def run(args: list[str], cfg: Path) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--config", str(cfg), *args])
    return buf.getvalue()


def make_config(tmp: Path, **scoring) -> Path:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for k in ("companies_file", "destinations_file", "offers_file", "profiles_file",
              "log_file", "rejected_file", "review_file"):
        cfg[k] = str(ROOT / cfg[k])
    cfg["bookings_file"] = str(tmp / "bookings.json")
    cfg["scoring"].update(scoring)
    path = tmp / f"config_{len(list(tmp.glob('config_*')))}.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def main_script() -> None:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg = make_config(tmp)
        for name, args in RUNS.items():
            if args is None:
                continue
            text = f"$ python -m busbidder {' '.join(args)}\n\n" + run(args, cfg)
            (OUT / name).write_text(text, encoding="utf-8")
            print("wrote", name)

        # Toledo contains the 189 EUR price outlier: compare normalisation methods.
        trip = ["search", "--to", "Toledo", "--from-date", "2026-07-12", "--to-date",
                "2026-07-12", "--weights", "price=40,duration=25,departure=15,flexibility=20",
                "--top", "0"]
        parts = []
        for method in ("minmax", "robust"):
            c = make_config(tmp, normalisation=method)
            parts.append(f"===== normalisation = {method} =====\n$ python -m busbidder "
                         f"{' '.join(trip)}\n\n" + run(trip, c))
        (OUT / "06_minmax_vs_robust_toledo.txt").write_text("\n\n".join(parts), encoding="utf-8")
        print("wrote 06_minmax_vs_robust_toledo.txt")

        demo = run(["book", "--offer", "VER-AGP-20260712-0710", "--name", "Lucia Fernandez",
                    "--seats", "2"], cfg)
        ref = next(l.split(":")[1].strip() for l in demo.splitlines() if "Reference" in l)
        demo += "\n" + run(["bookings"], cfg)
        demo += "\n$ cancel\n" + run(["cancel", ref], cfg)
        demo += "\n" + run(["bookings"], cfg)
        (OUT / "07_booking_demo.txt").write_text(demo, encoding="utf-8")
        print("wrote 07_booking_demo.txt")


if __name__ == "__main__":
    main_script()
