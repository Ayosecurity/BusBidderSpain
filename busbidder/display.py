"""Plain-text (ASCII-only, Windows-console safe) presentation helpers."""

from __future__ import annotations

from .filters import CONSTRAINTS, FilterResult
from .loader import LoadReport
from .models import Booking, RankedOffer, TravellerRequest
from .scoring import CRITERIA, Weights

SHORT = {"price": "Pric", "duration": "Dur", "departure": "Dep", "flexibility": "Flex",
         "transfers": "Trf", "rating": "Rate", "co2": "CO2"}


def table(headers: list[str], rows: list[list], align: str | None = None) -> str:
    cols = list(zip(headers, *rows)) if rows else [(h,) for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    align = align or "l" * len(headers)

    def fmt(row):
        return "  ".join(str(c).rjust(w) if a == "r" else str(c).ljust(w)
                         for c, w, a in zip(row, widths, align)).rstrip()
    sep = "  ".join("-" * w for w in widths)
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def request_summary(r: TravellerRequest, weights: Weights) -> str:
    hard = [f"destination = {r.destination}",
            f"date {r.date_from} .. {r.date_to}",
            f"seats >= {r.seats}"]
    if r.max_price is not None:
        hard.append(f"price <= EUR {r.max_price:.2f}")
    if r.max_transfers is not None:
        hard.append(f"transfers <= {r.max_transfers}")
    if r.max_duration_min is not None:
        hard.append(f"duration <= {r.max_duration_min} min")
    if r.min_luggage_kg is not None:
        hard.append(f"luggage >= {r.min_luggage_kg} kg")
    if r.require_changeable:
        hard.append("changeable ticket")
    if r.require_refundable:
        hard.append("refundable ticket")
    soft = [f"weights: {weights.describe()}", f"preferred departure: {r.preferred_period}"]
    return ("HARD CONSTRAINTS (offers failing any are removed):\n  - " + "\n  - ".join(hard)
            + "\nSOFT PREFERENCES (used for ranking only):\n  - " + "\n  - ".join(soft))


def filter_summary(f: FilterResult) -> str:
    lines = [f"{f.considered} offers match the destination and dates; "
             f"{len(f.accepted)} satisfy all hard constraints."]
    counts = f.removal_counts()
    if counts:
        parts = [f"{CONSTRAINTS[n]['label'].lower()}: {c}" for n, c in counts.most_common()]
        lines.append("Removed (an offer can fail several): " + ", ".join(parts))
    return "\n".join(lines)


def ranking_table(ranked: list[RankedOffer], weights: Weights, top: int | None = None) -> str:
    crit = list(weights)
    headers = (["#", "Offer ID", "Company", "Date", "Dep", "Arr", "Time", "EUR", "Trf", "Fare"]
               + [SHORT.get(c, c[:4]) for c in crit] + ["TOTAL"])
    rows = []
    for r in ranked[:top] if top else ranked:
        o = r.offer
        fare = ("C" if o.fare.changeable else "-") + ("R" if o.fare.refundable else "-")
        arr = f"{o.arrival:%H:%M}" + ("+1" if o.arrival_day_offset else "")
        rank = f"{r.rank}" + ("=" if r.tied_with_previous else "")
        rows.append([rank, o.offer_id, o.company.name, f"{o.travel_date:%d.%m}",
                     f"{o.departure:%H:%M}", arr, o.duration_text,
                     f"{o.price_eur:.2f}" + ("!" if "PRICE_OUTLIER" in o.flags else ""),
                     o.transfers, fare]
                    + [f"{r.criterion_scores[c]:.0f}" + ("*" if c in r.missing else "")
                       for c in crit]
                    + [f"{r.total:.1f}"])
    align = "rlllllrrrl" + "r" * (len(crit) + 1)
    legend = ("Criterion scores are 0-100 (100 = best). Fare: C = changeable, R = refundable. "
              "'=' tied with previous, '*' missing value (neutral 50), "
              "'!' price flagged for review.\n"
              "Columns: " + ", ".join(f"{SHORT.get(c, c)} = {CRITERIA[c]['label']} "
                                      f"({weights[c]:.0%})" for c in crit))
    return table(headers, rows, align) + "\n" + legend


def load_summary(rep: LoadReport) -> str:
    lines = [f"Rows read: {rep.rows_read}",
             f"Accepted: {len(rep.offers)} (of which corrected: {len(rep.corrected)}, "
             f"flagged for review: {len(rep.review)})",
             f"Rejected: {len(rep.rejected)}"]
    if rep.rejected:
        lines.append("\nRejected records:")
        lines.append(table(["Line", "Offer ID", "Reasons"],
                           [[r.line, r.record_id, ", ".join(r.reasons)] for r in rep.rejected],
                           "rll"))
    if rep.corrected:
        lines.append("\nCorrected records:")
        lines += [f"  {oid}: {'; '.join(n)}" for oid, n in rep.corrected]
    if rep.review:
        lines.append("\nKept but flagged for review:")
        lines += [f"  {oid}: {'; '.join(n)}" for oid, n in rep.review]
    flags = rep.flag_counts()
    if flags:
        lines.append("\nInformational flags on accepted offers: "
                     + ", ".join(f"{k} {v}" for k, v in sorted(flags.items())))
    return "\n".join(lines)


def booking_confirmation(b: Booking) -> str:
    fc = b.fare_conditions
    return "\n".join([
        "=" * 52,
        "  BOOKING CONFIRMATION - BusBidder Spain (simulated)",
        "=" * 52,
        f"  Reference : {b.reference}",
        f"  Status    : {b.status}",
        f"  Traveller : {b.traveller_name}",
        f"  Journey   : Madrid -> {b.destination}",
        f"  Date/time : {b.travel_date} {b.departure}  ({b.company})",
        f"  Seats     : {b.seats} x EUR {b.price_per_seat:.2f} = EUR {b.total_price:.2f}",
        f"  Fare      : changeable={'yes' if fc['changeable'] else 'no'}, "
        f"refundable={'yes' if fc['refundable'] else 'no'}, luggage {fc['luggage_kg']} kg",
        f"  Payment   : {b.payment_status} (no real payment taken)",
        "=" * 52])
