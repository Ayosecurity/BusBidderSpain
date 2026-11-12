"""Simulated booking with persistent, consistent seat capacity.

The source data (offers.csv) is never modified. Seats taken by bookings are
stored next to the bookings in ONE JSON state file, written atomically
(temp file + rename). Bookings and capacity therefore cannot drift apart,
even if the program is interrupted while saving.

No payment information is collected; payment status is simulated.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .exceptions import BookingError, BookingNotFoundError, SeatsUnavailableError
from .models import Booking, Offer
from .validation import is_valid_booking_reference, is_valid_traveller_name

log = logging.getLogger(__name__)
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I to avoid misreading
CHANGE_FEE_EUR = 5.0


class BookingManager:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.bookings: dict[str, Booking] = {}
        self.seats_taken: dict[str, int] = {}
        self._load()

    # ------------------------------------------------------------ storage --
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.bookings = {b["reference"]: Booking(**b) for b in data.get("bookings", [])}
            self.seats_taken = {k: int(v) for k, v in data.get("seats_taken", {}).items()}
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise BookingError(f"Booking file {self.path} is corrupt: {exc}") from exc

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"bookings": [asdict(b) for b in self.bookings.values()],
                "seats_taken": self.seats_taken}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    # -------------------------------------------------------------- seats --
    def apply_to(self, offers: list[Offer]) -> None:
        """Reduce in-memory capacity by seats already booked in earlier sessions."""
        for o in offers:
            taken = self.seats_taken.get(o.offer_id, 0)
            if taken:
                o.seats_available = max(0, o.seats_available - taken)
                if o.seats_available == 0 and "SOLD_OUT" not in o.flags:
                    o.flags.append("SOLD_OUT")

    def new_reference(self) -> str:
        while True:
            ref = "BBS-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(6))
            if ref not in self.bookings:
                assert is_valid_booking_reference(ref)
                return ref

    # ------------------------------------------------------------ actions --
    def book(self, offer: Offer, traveller_name: str, seats: int = 1) -> Booking:
        if not is_valid_traveller_name(traveller_name):
            raise BookingError("Traveller name must be 2-60 letters (spaces, ' - . allowed)")
        if seats < 1 or seats > 9:
            raise BookingError("You can book between 1 and 9 seats")
        if offer.seats_available < seats:                 # confirm availability
            raise SeatsUnavailableError(
                f"Only {offer.seats_available} seat(s) left on {offer.offer_id}")
        ref = self.new_reference()
        booking = Booking(
            reference=ref, offer_id=offer.offer_id, traveller_name=traveller_name.strip(),
            seats=seats, price_per_seat=offer.price_eur,
            total_price=round(offer.price_eur * seats, 2), company=offer.company.name,
            destination=offer.destination.name, travel_date=offer.travel_date.isoformat(),
            departure=offer.departure.strftime("%H:%M"),
            fare_conditions={"changeable": offer.fare.changeable,
                             "refundable": offer.fare.refundable,
                             "luggage_kg": offer.fare.luggage_kg},
            created_at=datetime.now().isoformat(timespec="seconds"))
        # update memory and disk together
        offer.seats_available -= seats
        self.seats_taken[offer.offer_id] = self.seats_taken.get(offer.offer_id, 0) + seats
        self.bookings[ref] = booking
        try:
            self._save()
        except OSError as exc:                             # roll back on failure
            offer.seats_available += seats
            self.seats_taken[offer.offer_id] -= seats
            del self.bookings[ref]
            raise BookingError(f"Could not save booking: {exc}") from exc
        log.info("BOOKED %s: %s x%d on %s, EUR %.2f", ref, booking.traveller_name, seats,
                 offer.offer_id, booking.total_price)
        return booking

    def get(self, reference: str) -> Booking:
        ref = reference.strip().upper()
        if not is_valid_booking_reference(ref):
            raise BookingNotFoundError(f"'{reference}' is not a valid booking reference "
                                       f"(format BBS-XXXXXX)")
        if ref not in self.bookings:
            raise BookingNotFoundError(f"No booking with reference {ref}")
        return self.bookings[ref]

    def cancel(self, reference: str, offer: Offer | None = None) -> Booking:
        """Cancel and simulate the refund the stored fare conditions allow."""
        b = self.get(reference)
        if b.status == "CANCELLED":
            raise BookingError(f"{b.reference} is already cancelled")
        fc = b.fare_conditions
        if fc["refundable"]:
            b.refund_eur = b.total_price
        elif fc["changeable"]:
            b.voucher_eur = max(0.0, round(b.total_price - CHANGE_FEE_EUR, 2))
        b.status = "CANCELLED"
        b.payment_status = "SIMULATED_REFUNDED" if b.refund_eur else b.payment_status
        self.seats_taken[b.offer_id] = max(0, self.seats_taken.get(b.offer_id, 0) - b.seats)
        if offer is not None:
            offer.seats_available += b.seats
            if "SOLD_OUT" in offer.flags and offer.seats_available > 0:
                offer.flags.remove("SOLD_OUT")
        self._save()
        log.info("CANCELLED %s: refund EUR %.2f, voucher EUR %.2f", b.reference,
                 b.refund_eur, b.voucher_eur)
        return b
