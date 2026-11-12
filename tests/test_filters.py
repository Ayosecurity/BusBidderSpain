"""Task 3: hard constraints remove offers before ranking."""

import unittest
from datetime import date

from busbidder.filters import CONSTRAINTS, apply_constraints, explain_rejection
from busbidder.profiles import validate_request
from busbidder.exceptions import InvalidRequestError

from tests.helpers import TOLEDO, make_offer, make_request


class TestConstraints(unittest.TestCase):
    def test_all_expected_constraints_registered(self):
        self.assertTrue({"destination", "travel_window", "budget", "seats", "transfers",
                         "duration", "luggage", "changeable", "refundable"}
                        <= set(CONSTRAINTS.names()))

    def test_wrong_destination_and_dates_not_considered(self):
        offers = [make_offer(dest=TOLEDO), make_offer(day=date(2026, 7, 20))]
        res = apply_constraints(offers, make_request())
        self.assertEqual((res.considered, len(res.accepted)), (0, 0))

    def test_budget_boundary_is_inclusive(self):
        req = make_request(max_price=30.0)
        self.assertEqual(len(apply_constraints([make_offer(price=30.0)], req)), 1)
        self.assertEqual(len(apply_constraints([make_offer(price=30.01)], req)), 0)

    def test_window_boundaries_inclusive(self):
        req = make_request()
        offers = [make_offer(day=date(2026, 7, 12)), make_offer(day=date(2026, 7, 14)),
                  make_offer(day=date(2026, 7, 15))]
        self.assertEqual(len(apply_constraints(offers, req)), 2)

    def test_seats_needed_for_group(self):
        req = make_request(seats=3)
        res = apply_constraints([make_offer(seats=2), make_offer(seats=3)], req)
        self.assertEqual(len(res.accepted), 1)
        self.assertEqual(res.removal_counts()["seats"], 1)

    def test_sold_out_removed(self):
        self.assertEqual(len(apply_constraints([make_offer(seats=0)], make_request())), 0)

    def test_transfers_changeable_refundable_luggage_duration(self):
        req = make_request(max_transfers=0, require_changeable=True, require_refundable=True,
                           min_luggage_kg=25, max_duration_min=300)
        o = make_offer(transfers=1, changeable=False, refundable=False, luggage=20)
        res = apply_constraints([o], req)
        self.assertEqual(set(res.removed[0][1]),
                         {"transfers", "changeable", "refundable", "luggage", "duration"})
        self.assertEqual(len(explain_rejection(o, req)), 5)

    def test_inactive_constraints_do_not_remove(self):
        self.assertEqual(len(apply_constraints([make_offer(transfers=3)], make_request())), 1)


class TestRequestValidation(unittest.TestCase):
    def test_end_before_start(self):
        with self.assertRaises(InvalidRequestError):
            validate_request(make_request(date_to=date(2026, 7, 1)))

    def test_non_positive_budget(self):
        with self.assertRaises(InvalidRequestError):
            validate_request(make_request(max_price=0))


if __name__ == "__main__":
    unittest.main()
