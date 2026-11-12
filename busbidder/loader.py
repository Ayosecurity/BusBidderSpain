"""Load companies, destinations and offers from CSV and validate them.

The loader never stops at the first bad row: it validates every record,
keeps the good ones, logs every decision and returns a ``LoadReport`` that
the CLI and the report use as evidence.
"""

from __future__ import annotations

import csv
import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .exceptions import DataFileError, RecordValidationError
from .models import Company, Destination, FareConditions, Offer
from .registry import logged
from .validation import (OFFER_ID_RE, Correction, FieldError, canonical_key, parse_bool,
                         parse_date, parse_int, parse_optional_float, parse_price,
                         parse_rating, parse_time)

log = logging.getLogger(__name__)

OFFER_COLUMNS = ["offer_id", "company_id", "destination", "travel_date", "departure",
                 "arrival", "arrival_day_offset", "price_eur", "transfers", "luggage_kg",
                 "changeable", "refundable", "seats_available", "rating", "co2_kg"]


@dataclass
class RejectedRecord:
    line: int
    record_id: str
    reasons: list[str]
    raw: dict


@dataclass
class LoadReport:
    offers: list[Offer] = field(default_factory=list)
    rejected: list[RejectedRecord] = field(default_factory=list)
    corrected: list[tuple[str, list[str]]] = field(default_factory=list)
    review: list[tuple[str, list[str]]] = field(default_factory=list)
    rows_read: int = 0

    def reason_counts(self) -> Counter:
        return Counter(r for rec in self.rejected for r in rec.reasons)

    def flag_counts(self) -> Counter:
        return Counter(f for o in self.offers for f in o.flags)


def _read_csv(path: Path, required: list[str]) -> list[dict]:
    if not path.exists():
        raise DataFileError(f"Data file not found: {path}")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in required if c not in header]
            if missing:
                raise DataFileError(f"{path.name}: missing column(s) {missing}")
            return list(reader)
    except UnicodeDecodeError as exc:
        raise DataFileError(f"{path.name} is not UTF-8 text: {exc}") from exc


def load_companies(path: Path) -> dict[str, Company]:
    companies = {}
    for row in _read_csv(path, ["company_id", "name", "profile"]):
        cid = row["company_id"].strip().upper()
        companies[cid] = Company(cid, row["name"].strip(), row["profile"].strip())
    if not companies:
        raise DataFileError(f"{path.name} contains no companies")
    log.info("Loaded %d companies from %s", len(companies), path.name)
    return companies


def load_destinations(path: Path) -> dict[str, tuple[str, Destination]]:
    """Return {canonical_name: (code, Destination)}."""
    dests = {}
    for row in _read_csv(path, ["code", "name", "region", "distance_km", "coastal"]):
        d = Destination(row["name"].strip(), row["region"].strip(),
                        int(row["distance_km"]), row["coastal"].strip().lower() == "yes")
        dests[canonical_key(d.name)] = (row["code"].strip().upper(), d)
    if not dests:
        raise DataFileError(f"{path.name} contains no destinations")
    log.info("Loaded %d destinations from %s", len(dests), path.name)
    return dests


def _field(errors: list[str], notes: list[str], func: Callable, *args):
    """Run one parser; collect error codes and corrections instead of raising."""
    try:
        value = func(*args)
    except FieldError as e:
        errors.append(e.code)
        return None
    if isinstance(value, Correction):
        notes.append(value.note)
        return value.value
    return value


def parse_offer(row: dict, companies: dict[str, Company],
                destinations: dict[str, tuple[str, Destination]],
                rating_scale: tuple[float, float]) -> tuple[Offer, list[str]]:
    """Validate one CSV row. Raises RecordValidationError listing all problems."""
    errors: list[str] = []
    notes: list[str] = []
    oid = (row.get("offer_id") or "").strip()
    m = OFFER_ID_RE.match(oid)
    if not m:
        errors.append("MALFORMED_OFFER_ID")

    cid_raw = (row.get("company_id") or "").strip()
    cid = cid_raw.upper()
    if cid != cid_raw:
        notes.append(f"company_id '{cid_raw}' -> '{cid}'")
    company = companies.get(cid)
    if company is None:
        errors.append("UNKNOWN_COMPANY")

    dest_raw = row.get("destination") or ""
    dest_entry = destinations.get(canonical_key(dest_raw))
    if dest_entry is None:
        errors.append("UNKNOWN_DESTINATION")
        dest_code, destination = None, None
    else:
        dest_code, destination = dest_entry
        if dest_raw != destination.name:
            notes.append(f"destination '{dest_raw}' -> '{destination.name}'")

    travel_date = _field(errors, notes, parse_date, row.get("travel_date"))
    dep = _field(errors, notes, parse_time, row.get("departure"))
    arr = _field(errors, notes, parse_time, row.get("arrival"))
    offset = _field(errors, notes, parse_int, row.get("arrival_day_offset"), "DAY_OFFSET", 0, 1)
    price = _field(errors, notes, parse_price, row.get("price_eur"))
    transfers = _field(errors, notes, parse_int, row.get("transfers"), "TRANSFERS", 0, 5)
    luggage = _field(errors, notes, parse_int, row.get("luggage_kg"), "LUGGAGE", 0, 50)
    changeable = _field(errors, notes, parse_bool, row.get("changeable"), "changeable")
    refundable = _field(errors, notes, parse_bool, row.get("refundable"), "refundable")
    seats = _field(errors, notes, parse_int, row.get("seats_available"), "SEATS", 0, 100)
    rating = _field(errors, notes, parse_rating, row.get("rating"), rating_scale)
    co2 = _field(errors, notes, parse_optional_float, row.get("co2_kg"), "CO2")

    # Cross-field consistency checks
    if dep is not None and arr is not None and offset == 0 and arr <= dep:
        errors.append("ARRIVAL_BEFORE_DEPARTURE")
    if m and not errors:
        if m["company"] != cid or m["dest"] != dest_code \
                or m["date"] != travel_date.strftime("%Y%m%d") \
                or m["time"] != dep.strftime("%H%M"):
            errors.append("OFFER_ID_MISMATCH")

    if errors:
        raise RecordValidationError(oid or "<no id>", errors)

    offer = Offer(oid, company, destination, travel_date, dep, arr, offset, price,
                  transfers, FareConditions(changeable, refundable, luggage), seats,
                  rating, co2)
    if seats == 0:
        offer.flags.append("SOLD_OUT")
    if rating is None:
        offer.flags.append("MISSING_RATING")
    if co2 is None:
        offer.flags.append("MISSING_CO2")
    return offer, notes


@logged
def load_offers(path: Path, companies: dict[str, Company],
                destinations: dict[str, tuple[str, Destination]],
                rating_scale: tuple[float, float] = (1.0, 5.0),
                outlier_factor: float = 3.0) -> LoadReport:
    report = LoadReport()
    seen: set[str] = set()
    rows = _read_csv(path, OFFER_COLUMNS)
    for line, row in enumerate(rows, start=2):           # line 1 = header
        report.rows_read += 1
        try:
            offer, notes = parse_offer(row, companies, destinations, rating_scale)
            if offer.offer_id in seen:
                raise RecordValidationError(offer.offer_id, ["DUPLICATE_ID"])
        except RecordValidationError as exc:
            report.rejected.append(RejectedRecord(line, exc.record_id, exc.reasons, row))
            log.warning("REJECTED line %d %s", line, exc)
            continue
        seen.add(offer.offer_id)
        if notes:
            report.corrected.append((offer.offer_id, notes))
            log.info("CORRECTED %s: %s", offer.offer_id, "; ".join(notes))
        report.offers.append(offer)

    _flag_price_outliers(report, outlier_factor)
    log.info("Offers: %d read, %d accepted, %d corrected, %d rejected, %d for review",
             report.rows_read, len(report.offers), len(report.corrected),
             len(report.rejected), len(report.review))
    return report


def _flag_price_outliers(report: LoadReport, factor: float) -> None:
    """Keep but flag offers priced far above the median for their destination."""
    by_dest = defaultdict(list)
    for o in report.offers:
        by_dest[o.destination.name].append(o.price_eur)
    medians = {d: statistics.median(p) for d, p in by_dest.items()}
    for o in report.offers:
        med = medians[o.destination.name]
        if o.price_eur > factor * med:
            o.flags.append("PRICE_OUTLIER")
            report.review.append((o.offer_id, [f"price {o.price_eur:.2f} > {factor:g} x "
                                               f"median {med:.2f}"]))
            log.warning("REVIEW %s: price %.2f is > %.1fx destination median %.2f",
                        o.offer_id, o.price_eur, factor, med)


def write_rejected(report: LoadReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["line", "offer_id", "reasons"] + OFFER_COLUMNS)
        for r in report.rejected:
            w.writerow([r.line, r.record_id, ";".join(r.reasons)]
                       + [r.raw.get(c, "") for c in OFFER_COLUMNS])


def write_review(report: LoadReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["offer_id", "notes"])
        for oid, notes in report.review:
            w.writerow([oid, "; ".join(notes)])


@dataclass
class Marketplace:
    """Everything loaded from disk, bundled for the rest of the application."""
    companies: dict[str, Company]
    destinations: dict[str, tuple[str, Destination]]
    report: LoadReport

    @property
    def offers(self) -> list[Offer]:
        return self.report.offers

    def destination_names(self) -> list[str]:
        return [d.name for _, d in self.destinations.values()]

    def resolve_destination(self, text: str) -> str | None:
        entry = self.destinations.get(canonical_key(text))
        return entry[1].name if entry else None

    def find_offer(self, offer_id: str) -> Offer | None:
        return next((o for o in self.offers if o.offer_id == offer_id), None)


def load_marketplace(cfg) -> Marketplace:
    companies = load_companies(cfg.path("companies_file"))
    destinations = load_destinations(cfg.path("destinations_file"))
    report = load_offers(cfg.path("offers_file"), companies, destinations,
                         tuple(cfg.get("rating_scale", [1.0, 5.0])),
                         cfg.get("price_outlier_factor", 3.0))
    write_rejected(report, cfg.path("rejected_file"))
    write_review(report, cfg.path("review_file"))
    return Marketplace(companies, destinations, report)
