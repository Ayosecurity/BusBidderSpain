"""Weighted multi-criteria scoring.

Every criterion is converted to a 0-100 score where **100 is always best**,
so criteria where lower is better (price, duration, CO2) are inverted.
Two kinds of criteria are used:

* *relative* criteria (price, duration, CO2) have no natural scale, so they
  are normalised against the offers that survived filtering (min-max, with
  two safeguards, see ``normalise_relative``);
* *absolute* criteria (departure convenience, flexibility, transfers, rating)
  have a natural scale and are scored with a fixed, explainable rule, so their
  score does not change when other offers are added or removed.

Total score = sum(weight_c * score_c), with weights summing to 1.0, so the
total is also on a 0-100 scale.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import time
from typing import Optional

from .exceptions import WeightError
from .models import Offer, TravellerRequest
from .registry import Registry

log = logging.getLogger(__name__)
CRITERIA = Registry("criterion")

PERIODS = {                     # preferred departure windows (start, end) in minutes
    "morning": (6 * 60, 12 * 60),
    "afternoon": (12 * 60, 18 * 60),
    "evening": (18 * 60, 22 * 60),
    "night": (22 * 60, 30 * 60),   # 22:00-06:00, wraps past midnight
}
PENALTY_PER_HOUR = 20.0          # departure score lost per hour outside the window
FLEX_SCORES = {(True, True): 100.0, (True, False): 60.0, (False, True): 50.0,
               (False, False): 0.0}
TRANSFER_SCORES = {0: 100.0, 1: 50.0}   # 2 or more -> 0


# ---------------------------------------------------------------- criteria --
@CRITERIA.register("price", kind="relative", higher_is_better=False,
                   label="Price", unit="EUR")
def price_value(o: Offer, r: TravellerRequest) -> float:
    return o.price_eur


@CRITERIA.register("duration", kind="relative", higher_is_better=False,
                   label="Duration", unit="min")
def duration_value(o: Offer, r: TravellerRequest) -> float:
    return float(o.duration_min)


@CRITERIA.register("co2", kind="relative", higher_is_better=False,
                   label="Est. CO2", unit="kg")
def co2_value(o: Offer, r: TravellerRequest) -> Optional[float]:
    return o.co2_kg


@CRITERIA.register("departure", kind="absolute", label="Departure convenience")
def departure_score(o: Offer, r: TravellerRequest) -> float:
    return departure_convenience(o.departure, r.preferred_period)


@CRITERIA.register("flexibility", kind="absolute", label="Ticket flexibility")
def flexibility_score(o: Offer, r: TravellerRequest) -> float:
    return FLEX_SCORES[(o.fare.changeable, o.fare.refundable)]


@CRITERIA.register("transfers", kind="absolute", label="Transfers")
def transfers_score(o: Offer, r: TravellerRequest) -> float:
    return TRANSFER_SCORES.get(o.transfers, 0.0)


@CRITERIA.register("rating", kind="absolute", label="Customer rating")
def rating_score(o: Offer, r: TravellerRequest) -> Optional[float]:
    if o.rating is None:
        return None
    return (o.rating - 1.0) / 4.0 * 100.0


def departure_convenience(dep: time, period: str) -> float:
    """100 inside the preferred window, minus 20 points per hour outside it."""
    if period == "any":
        return 100.0
    if period not in PERIODS:
        raise ValueError(f"unknown period '{period}'")
    start, end = PERIODS[period]
    t = dep.hour * 60 + dep.minute
    best = math.inf
    for shifted in (t - 1440, t, t + 1440):        # handle the midnight wrap
        if start <= shifted <= end:
            return 100.0
        best = min(best, abs(shifted - start), abs(shifted - end))
    return max(0.0, 100.0 - PENALTY_PER_HOUR * best / 60.0)


# ----------------------------------------------------------- normalisation --
def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (same as numpy's default)."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    return s[f] + (s[c] - s[f]) * (k - f)


def normalise_relative(values: list[Optional[float]], higher_is_better: bool,
                       min_spread: float = 0.0, robust: bool = False,
                       iqr_factor: float = 1.5, robust_min_n: int = 5,
                       missing_score: float = 50.0) -> list[float]:
    """Map raw values to 0-100 (100 = best).

    Safeguards against one criterion dominating unintentionally:
    1. *Spread floor*: if all offers cost EUR 30.00-30.50, plain min-max would turn
       a 50-cent difference into a 100-point gap. The denominator is therefore at
       least ``min_spread`` (e.g. EUR 5), so trivial differences stay trivial.
    2. *Robust bounds* (optional): with at least ``robust_min_n`` offers, the bounds
       are clipped to Tukey's fences (Q1 - 1.5*IQR, Q3 + 1.5*IQR). One extreme offer
       then gets 0 (or 100) instead of squeezing every normal offer into a narrow
       band. Without outliers the fences lie outside min/max, so the result is
       identical to plain min-max.
    Missing values receive a neutral ``missing_score`` (and are reported).
    """
    present = [v for v in values if v is not None]
    if not present:
        return [missing_score for _ in values]
    lo, hi = min(present), max(present)
    if robust and len(present) >= robust_min_n:
        q1, q3 = percentile(present, 25), percentile(present, 75)
        iqr = q3 - q1
        lo, hi = max(lo, q1 - iqr_factor * iqr), min(hi, q3 + iqr_factor * iqr)
    spread = max(hi - lo, min_spread)
    if spread == 0:
        return [100.0 if v is not None else missing_score for v in values]
    out = []
    for v in values:
        if v is None:
            out.append(missing_score)
            continue
        if higher_is_better:
            ref = hi - spread
            x = (min(max(v, ref), hi) - ref) / spread
        else:
            x = 1.0 - (min(max(v, lo), lo + spread) - lo) / spread
        out.append(round(100.0 * x, 2))
    return out


# ------------------------------------------------------------------ weights --
class Weights(dict):
    """Validated mapping criterion -> weight (fractions summing to 1.0)."""

    TOLERANCE = 1e-6

    @classmethod
    def create(cls, raw: dict[str, float], normalise: bool = False) -> "Weights":
        if not raw:
            raise WeightError("at least one weight is required")
        unknown = [k for k in raw if k not in CRITERIA]
        if unknown:
            raise WeightError(f"unknown criterion {unknown}; choose from {CRITERIA.names()}")
        try:
            values = {k: float(v) for k, v in raw.items()}
        except (TypeError, ValueError):
            raise WeightError("weights must be numbers") from None
        if any(v < 0 or math.isnan(v) for v in values.values()):
            raise WeightError("weights cannot be negative")
        total = sum(values.values())
        if total <= 0:
            raise WeightError("weights must not all be zero")
        if abs(total - 100.0) < 1e-6:             # percentages accepted
            values = {k: v / 100.0 for k, v in values.items()}
        elif abs(total - 1.0) > cls.TOLERANCE:
            if not normalise:
                raise WeightError(f"weights sum to {total:g}; they must sum to 1.0 or 100 "
                                  f"(use --normalise-weights to rescale automatically)")
            values = {k: v / total for k, v in values.items()}
        return cls({k: v for k, v in values.items() if v > 0})

    @classmethod
    def parse(cls, text: str, normalise: bool = False) -> "Weights":
        """Parse 'price=40,duration=25,departure=15,flexibility=20'."""
        raw = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            if "=" not in part:
                raise WeightError(f"'{part}' is not in the form name=value")
            k, v = (s.strip() for s in part.split("=", 1))
            raw[k] = v
        return cls.create(raw, normalise)

    def dominance_warnings(self, threshold: float = 0.6) -> list[str]:
        return [f"'{k}' has {v:.0%} of the total weight and will largely decide the ranking"
                for k, v in self.items() if v > threshold]

    def describe(self) -> str:
        return ", ".join(f"{k} {v:.0%}" for k, v in self.items())
