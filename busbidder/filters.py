"""Hard constraints: an offer that violates any of these is removed before ranking.

Each constraint is a small function registered with ``@CONSTRAINTS.register``.
It returns ``None`` when the offer is acceptable, or a short human-readable
reason when it is not. Inactive constraints (the traveller did not set them)
simply return ``None``.

Why these are *hard*: they describe things the traveller cannot accept at any
price - the wrong city or date, a ticket they cannot afford, a bus with no
seat, more changes than they can manage, or a fare type they are obliged to
have. Everything that is a matter of degree (cheaper, faster, nearer the
preferred time) is a *soft* preference and is handled by the scoring model.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from .models import Offer, TravellerRequest
from .registry import Registry, logged

log = logging.getLogger(__name__)
CONSTRAINTS = Registry("constraint")


@CONSTRAINTS.register("destination", label="Destination")
def _destination(o: Offer, r: TravellerRequest):
    if o.destination.name != r.destination:
        return f"goes to {o.destination.name}, not {r.destination}"


@CONSTRAINTS.register("travel_window", label="Travel window")
def _window(o: Offer, r: TravellerRequest):
    if not r.date_from <= o.travel_date <= r.date_to:
        return f"date {o.travel_date} outside {r.date_from}..{r.date_to}"


@CONSTRAINTS.register("seats", label="Seat availability")
def _seats(o: Offer, r: TravellerRequest):
    if o.seats_available < r.seats:
        return f"only {o.seats_available} seat(s) left, {r.seats} needed"


@CONSTRAINTS.register("budget", label="Maximum budget")
def _budget(o: Offer, r: TravellerRequest):
    if r.max_price is not None and o.price_eur > r.max_price:     # budget is per ticket
        return f"price EUR {o.price_eur:.2f} > budget EUR {r.max_price:.2f}"


@CONSTRAINTS.register("transfers", label="Maximum transfers")
def _transfers(o: Offer, r: TravellerRequest):
    if r.max_transfers is not None and o.transfers > r.max_transfers:
        return f"{o.transfers} transfer(s) > max {r.max_transfers}"


@CONSTRAINTS.register("duration", label="Maximum duration")
def _duration(o: Offer, r: TravellerRequest):
    if r.max_duration_min is not None and o.duration_min > r.max_duration_min:
        return f"duration {o.duration_text} > max {r.max_duration_min} min"


@CONSTRAINTS.register("luggage", label="Required luggage")
def _luggage(o: Offer, r: TravellerRequest):
    if r.min_luggage_kg is not None and o.fare.luggage_kg < r.min_luggage_kg:
        return f"luggage {o.fare.luggage_kg} kg < {r.min_luggage_kg} kg"


@CONSTRAINTS.register("changeable", label="Changeable ticket required")
def _changeable(o: Offer, r: TravellerRequest):
    if r.require_changeable and not o.fare.changeable:
        return "ticket not changeable"


@CONSTRAINTS.register("refundable", label="Refundable ticket required")
def _refundable(o: Offer, r: TravellerRequest):
    if r.require_refundable and not o.fare.refundable:
        return "ticket not refundable"


@dataclass
class FilterResult:
    accepted: list[Offer] = field(default_factory=list)
    removed: list[tuple[Offer, list[str]]] = field(default_factory=list)  # (offer, constraint names)
    considered: int = 0

    def removal_counts(self) -> Counter:
        """How many relevant offers each constraint removed (an offer may fail several)."""
        return Counter(name for _, names in self.removed for name in names)

    def __len__(self) -> int:
        return len(self.accepted)


@logged
def apply_constraints(offers: list[Offer], request: TravellerRequest) -> FilterResult:
    """Remove offers violating any hard constraint.

    Offers for other destinations/dates are not counted as "removed" in the
    summary, because showing "1000 offers removed: wrong city" is noise; the
    summary focuses on offers that matched the trip but failed a condition.
    """
    result = FilterResult()
    for offer in offers:
        if _destination(offer, request) or _window(offer, request):
            continue
        result.considered += 1
        failed = []
        for name, entry in CONSTRAINTS.items():
            if name in ("destination", "travel_window"):
                continue
            reason = entry["func"](offer, request)
            if reason:
                failed.append(name)
                log.debug("Removed %s: %s", offer.offer_id, reason)
        if failed:
            result.removed.append((offer, failed))
        else:
            result.accepted.append(offer)
    log.info("Filter %s %s..%s: %d considered, %d accepted, removed by %s",
             request.destination, request.date_from, request.date_to, result.considered,
             len(result.accepted), dict(result.removal_counts()))
    return result


def explain_rejection(offer: Offer, request: TravellerRequest) -> list[str]:
    """Human-readable reasons, used when the user asks why an offer is missing."""
    return [r for _, e in CONSTRAINTS.items() if (r := e["func"](offer, request))]
