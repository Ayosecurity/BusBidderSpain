"""Domain model for BusBidder Spain.

Design notes
------------
* Plain, mostly immutable dataclasses: the objects carry data, while the
  behaviour (validation, filtering, scoring, booking) lives in separate
  modules. This keeps every module testable in isolation.
* Composition over inheritance: an ``Offer`` *has* ``FareConditions`` and
  refers to a ``Company`` and ``Destination``; there is no meaningful "is-a"
  hierarchy between these concepts, so inheritance would add nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional


@dataclass(frozen=True)
class Company:
    company_id: str          # three-letter code, e.g. "SOL"
    name: str
    profile: str


@dataclass(frozen=True)
class Destination:
    name: str
    region: str
    distance_km: int
    coastal: bool


@dataclass(frozen=True)
class FareConditions:
    changeable: bool
    refundable: bool
    luggage_kg: int

    @property
    def label(self) -> str:
        if self.changeable and self.refundable:
            return "changeable + refundable"
        if self.changeable:
            return "changeable"
        if self.refundable:
            return "refundable"
        return "fixed (no changes)"


@dataclass
class Offer:
    offer_id: str
    company: Company
    destination: Destination
    travel_date: date
    departure: time
    arrival: time
    arrival_day_offset: int        # 0 = same day, 1 = next day (overnight)
    price_eur: float
    transfers: int
    fare: FareConditions
    seats_available: int
    rating: Optional[float] = None  # 1.0-5.0, None when missing
    co2_kg: Optional[float] = None  # optional environmental measure
    flags: list[str] = field(default_factory=list)  # e.g. ["PRICE_OUTLIER"]

    @property
    def departure_dt(self) -> datetime:
        return datetime.combine(self.travel_date, self.departure)

    @property
    def arrival_dt(self) -> datetime:
        return datetime.combine(self.travel_date + timedelta(days=self.arrival_day_offset),
                                self.arrival)

    @property
    def duration_min(self) -> int:
        return int((self.arrival_dt - self.departure_dt).total_seconds() // 60)

    @property
    def duration_text(self) -> str:
        h, m = divmod(self.duration_min, 60)
        return f"{h}h{m:02d}"


@dataclass(frozen=True)
class TravellerRequest:
    """Hard constraints (must hold) plus soft preferences (used for ranking)."""
    destination: str
    date_from: date
    date_to: date
    max_price: Optional[float] = None
    seats: int = 1
    max_transfers: Optional[int] = None
    max_duration_min: Optional[int] = None
    min_luggage_kg: Optional[int] = None
    require_changeable: bool = False
    require_refundable: bool = False
    # soft preference
    preferred_period: str = "any"   # morning / afternoon / evening / night / any


@dataclass
class RankedOffer:
    offer: Offer
    criterion_scores: dict[str, float]      # 0-100 per criterion
    contributions: dict[str, float]         # weight * score
    total: float
    missing: list[str] = field(default_factory=list)
    rank: int = 0
    tied_with_previous: bool = False


@dataclass
class Booking:
    reference: str
    offer_id: str
    traveller_name: str
    seats: int
    price_per_seat: float
    total_price: float
    company: str
    destination: str
    travel_date: str
    departure: str
    fare_conditions: dict
    payment_status: str = "SIMULATED_PAID"
    status: str = "CONFIRMED"
    created_at: str = ""
    refund_eur: float = 0.0
    voucher_eur: float = 0.0
