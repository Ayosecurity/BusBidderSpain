"""Section 6: simulated booking, capacity and persistence."""

import json
import tempfile
import unittest
from pathlib import Path

from busbidder.booking import BookingManager
from busbidder.exceptions import BookingError, BookingNotFoundError, SeatsUnavailableError
from busbidder.validation import is_valid_booking_reference

from tests.helpers import make_offer


class TestBooking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state" / "bookings.json"
        self.mgr = BookingManager(self.path)
        self.offer = make_offer(seats=3, refundable=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_booking_reduces_capacity_and_is_saved(self):
        b = self.mgr.book(self.offer, "Ana García", 2)
        self.assertTrue(is_valid_booking_reference(b.reference))
        self.assertEqual(self.offer.seats_available, 1)
        self.assertEqual(b.total_price, 60.0)
        self.assertEqual(b.fare_conditions["refundable"], True)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["seats_taken"][self.offer.offer_id], 2)

    def test_capacity_persists_between_sessions(self):
        self.mgr.book(self.offer, "Ana", 2)
        fresh_offer = make_offer(seats=3)
        BookingManager(self.path).apply_to([fresh_offer])
        self.assertEqual(fresh_offer.seats_available, 1)

    def test_cannot_overbook(self):
        self.mgr.book(self.offer, "Ana", 3)
        with self.assertRaises(SeatsUnavailableError):
            self.mgr.book(self.offer, "Ben", 1)
        self.assertEqual(self.offer.seats_available, 0)

    def test_invalid_name_and_seat_count(self):
        with self.assertRaises(BookingError):
            self.mgr.book(self.offer, "4", 1)
        with self.assertRaises(BookingError):
            self.mgr.book(self.offer, "Ana", 0)
        self.assertEqual(self.offer.seats_available, 3)

    def test_references_unique(self):
        refs = {self.mgr.new_reference() for _ in range(500)}
        self.assertEqual(len(refs), 500)

    def test_cancel_refundable_restores_seats_and_refunds(self):
        b = self.mgr.book(self.offer, "Ana", 2)
        c = self.mgr.cancel(b.reference, self.offer)
        self.assertEqual((c.status, c.refund_eur), ("CANCELLED", 60.0))
        self.assertEqual(self.offer.seats_available, 3)
        with self.assertRaises(BookingError):
            self.mgr.cancel(b.reference, self.offer)

    def test_cancel_changeable_only_gives_voucher(self):
        offer = make_offer(seats=3, changeable=True, refundable=False, price=30.0)
        b = self.mgr.book(offer, "Ana", 1)
        c = self.mgr.cancel(b.reference, offer)
        self.assertEqual((c.refund_eur, c.voucher_eur), (0.0, 25.0))

    def test_unknown_or_malformed_reference(self):
        with self.assertRaises(BookingNotFoundError):
            self.mgr.get("BBS-ZZZZZZ")
        with self.assertRaises(BookingNotFoundError):
            self.mgr.get("hello")

    def test_corrupt_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(BookingError):
            BookingManager(self.path)


if __name__ == "__main__":
    unittest.main()
