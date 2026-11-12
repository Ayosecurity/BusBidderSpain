"""Custom exception hierarchy for BusBidder Spain.

All application errors derive from ``BusBidderError`` so the CLI can catch
them in one place and show a friendly message instead of a traceback.
"""


class BusBidderError(Exception):
    """Base class for all application-specific errors."""


# --- Data loading ---------------------------------------------------------
class DataFileError(BusBidderError):
    """A required data/config file is missing, unreadable or has the wrong header."""


class RecordValidationError(BusBidderError):
    """A single record contains missing, inconsistent or impossible values.

    ``reasons`` holds one short machine-readable code per problem, e.g.
    ``["NEGATIVE_PRICE", "UNKNOWN_DESTINATION"]`` so that rejected records can
    be counted and reported per category.
    """

    def __init__(self, record_id: str, reasons: list[str]):
        self.record_id = record_id
        self.reasons = list(reasons)
        super().__init__(f"{record_id}: {', '.join(self.reasons)}")


# --- Traveller input ------------------------------------------------------
class InvalidRequestError(BusBidderError):
    """The traveller request itself is inconsistent (e.g. end date before start date)."""


class WeightError(BusBidderError):
    """Criterion weights are negative, unknown or do not sum to 1.0 / 100 %."""


# --- Booking ---------------------------------------------------------------
class BookingError(BusBidderError):
    """Generic booking failure."""


class SeatsUnavailableError(BookingError):
    """Not enough seats remain on the selected offer."""


class BookingNotFoundError(BookingError):
    """No booking exists with the given reference."""
