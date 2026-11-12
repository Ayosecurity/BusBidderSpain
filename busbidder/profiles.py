"""Traveller profiles: named sets of weights, preferred period and extra constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .exceptions import DataFileError, InvalidRequestError
from .models import TravellerRequest
from .scoring import PERIODS, Weights

ALLOWED_CONSTRAINTS = {f.name for f in fields(TravellerRequest)} - {
    "destination", "date_from", "date_to", "preferred_period"}


@dataclass(frozen=True)
class TravellerProfile:
    name: str
    description: str
    weights: Weights
    preferred_period: str
    constraints: dict

    def apply(self, base: TravellerRequest) -> TravellerRequest:
        """Profile constraints are added on top of the trip the traveller asked for."""
        return replace(base, preferred_period=self.preferred_period, **self.constraints)


def load_profiles(path: Path) -> dict[str, TravellerProfile]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataFileError(f"Profile file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataFileError(f"Profile file {path} is not valid JSON: {exc}") from exc
    profiles = {}
    for name, p in data.items():
        period = p.get("preferred_period", "any")
        if period != "any" and period not in PERIODS:
            raise DataFileError(f"profile '{name}': unknown period '{period}'")
        extra = set(p.get("constraints", {})) - ALLOWED_CONSTRAINTS
        if extra:
            raise DataFileError(f"profile '{name}': unknown constraint(s) {sorted(extra)}")
        profiles[name] = TravellerProfile(name, p.get("description", ""),
                                          Weights.create(p["weights"]), period,
                                          p.get("constraints", {}))
    return profiles


def validate_request(r: TravellerRequest) -> None:
    if r.date_to < r.date_from:
        raise InvalidRequestError("end date is before start date")
    if r.max_price is not None and r.max_price <= 0:
        raise InvalidRequestError("budget must be positive")
    if r.seats < 1:
        raise InvalidRequestError("at least one seat is required")
    if r.max_transfers is not None and r.max_transfers < 0:
        raise InvalidRequestError("max transfers cannot be negative")
    if r.preferred_period != "any" and r.preferred_period not in PERIODS:
        raise InvalidRequestError(f"preferred period must be one of any, {', '.join(PERIODS)}")
