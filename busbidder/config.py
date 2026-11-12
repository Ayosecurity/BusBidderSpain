"""Configuration and logging setup.

All paths in ``config.json`` are relative to the project root so the program
behaves the same regardless of the current working directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .exceptions import DataFileError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"


class Config:
    def __init__(self, data: dict[str, Any], root: Path = PROJECT_ROOT):
        self.data = data
        self.root = root

    def path(self, key: str) -> Path:
        p = Path(self.data[key])
        return p if p.is_absolute() else self.root / p

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def scoring(self) -> dict[str, Any]:
        return self.data.get("scoring", {})


def load_config(path: Path | str | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as f:
            return Config(json.load(f), root=path.resolve().parent)
    except FileNotFoundError as exc:
        raise DataFileError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataFileError(f"Configuration file {path} is not valid JSON: {exc}") from exc


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """Log everything to file; only warnings and errors reach the console."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(ch)


def close_logging() -> None:
    """Close and detach all handlers so the log file is released.

    Needed on Windows, where an open file cannot be deleted or moved
    (e.g. when tests clean up their temporary folders).
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    # Without any handler Python would print warnings straight to the console
    # ("last resort" handler); a NullHandler keeps the output quiet instead.
    root.addHandler(logging.NullHandler())
