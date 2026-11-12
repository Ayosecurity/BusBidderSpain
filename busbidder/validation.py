"""Field-level parsing and validation rules.

Every parser either returns a clean value, returns a corrected value together
with a note (``Correction``), or raises ``FieldError`` with a short reason code.
The loader collects all reason codes of a row before deciding, so a rejected
record reports *every* problem, not just the first one.

Policy (also explained in the report):
* REJECT  - values that are impossible or ambiguous (negative price, unknown
            destination, invalid date, arrival before departure, rating outside
            the scale, negative seats, malformed identifier, duplicates).
            Guessing a value here could give a traveller a wrong ticket.
* CORRECT - pure formatting problems whose meaning is unambiguous
            (surrounding spaces, letter case, accents, "34,90" decimal comma,
            "Y"/"TRUE" booleans). The correction is logged.
* REVIEW  - plausible but suspicious values (extreme price outliers). The offer
            is kept and flagged, and written to a review file for a human.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time

# Regular expressions are used where the data has a real structured format.
OFFER_ID_RE = re.compile(
    r"^(?P<company>[A-Z]{3})-(?P<dest>[A-Z]{3})-(?P<date>\d{8})-(?P<time>\d{4})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
PRICE_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")
PRICE_COMMA_RE = re.compile(r"^\d+,\d{1,2}$")
# Booking reference: prefix + 6 chars, ambiguous characters 0/O/1/I excluded.
BOOKING_REF_RE = re.compile(r"^BBS-[A-HJ-NP-Z2-9]{6}$")
TRAVELLER_NAME_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '\-.]){1,59}$")

TRUE_CANON, FALSE_CANON = "yes", "no"
TRUE_ALIASES = {"y", "true", "1", "ja", "si", "sí"}
FALSE_ALIASES = {"n", "false", "0", "nei"}


class FieldError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class Correction:
    value: object
    note: str


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                    if not unicodedata.combining(c))


def canonical_key(text: str) -> str:
    """'  Málaga ' -> 'malaga' (used to match destination names)."""
    return strip_accents(text).strip().casefold()


def parse_required(raw: str | None, code: str) -> str:
    if raw is None or str(raw).strip() == "":
        raise FieldError(code)
    return str(raw)


def parse_date(raw: str) -> date:
    raw = parse_required(raw, "MISSING_DATE").strip()
    if not DATE_RE.match(raw):
        raise FieldError("INVALID_DATE")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise FieldError("INVALID_DATE") from None


def parse_time(raw: str, code: str = "INVALID_TIME") -> time:
    raw = parse_required(raw, "MISSING_TIME").strip()
    if not TIME_RE.match(raw):
        raise FieldError(code)
    h, m = map(int, raw.split(":"))
    return time(h, m)


def parse_price(raw: str) -> float | Correction:
    raw = parse_required(raw, "MISSING_PRICE").strip()
    if raw.startswith("-"):
        raise FieldError("NEGATIVE_PRICE")
    if PRICE_RE.match(raw):
        value = float(raw)
        if value == 0:
            raise FieldError("ZERO_PRICE")
        return value
    if PRICE_COMMA_RE.match(raw):
        return Correction(float(raw.replace(",", ".")), f"price '{raw}' -> decimal point")
    raise FieldError("INVALID_PRICE")


def parse_int(raw: str, code: str, minimum: int | None = 0, maximum: int | None = None) -> int:
    raw = parse_required(raw, f"MISSING_{code}").strip()
    try:
        value = int(raw)
    except ValueError:
        raise FieldError(f"INVALID_{code}") from None
    if minimum is not None and value < minimum:
        raise FieldError(f"NEGATIVE_{code}" if minimum == 0 else f"{code}_OUT_OF_RANGE")
    if maximum is not None and value > maximum:
        raise FieldError(f"{code}_OUT_OF_RANGE")
    return value


def parse_bool(raw: str, field: str) -> bool | Correction:
    raw_s = parse_required(raw, f"MISSING_{field.upper()}").strip()
    low = raw_s.casefold()
    if low == TRUE_CANON:
        return True
    if low == FALSE_CANON:
        return False
    if low in TRUE_ALIASES:
        return Correction(True, f"{field} '{raw_s}' -> yes")
    if low in FALSE_ALIASES:
        return Correction(False, f"{field} '{raw_s}' -> no")
    raise FieldError(f"INVALID_{field.upper()}")


def parse_rating(raw: str, scale: tuple[float, float]) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None                       # missing is allowed; handled in scoring
    try:
        value = float(str(raw).strip())
    except ValueError:
        raise FieldError("INVALID_RATING") from None
    if not scale[0] <= value <= scale[1]:
        raise FieldError("RATING_OUT_OF_SCALE")
    return value


def parse_optional_float(raw: str, code: str) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        raise FieldError(f"INVALID_{code}") from None
    if value < 0:
        raise FieldError(f"NEGATIVE_{code}")
    return value


def is_valid_booking_reference(ref: str) -> bool:
    return bool(BOOKING_REF_RE.match(ref or ""))


def is_valid_traveller_name(name: str) -> bool:
    return bool(TRAVELLER_NAME_RE.match((name or "").strip()))
