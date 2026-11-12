"""Section 5: normalisation, weights and ranking."""

import unittest
from datetime import time

from busbidder.exceptions import WeightError
from busbidder.explain import explain_top
from busbidder.ranking import rank_offers, sensitivity, shift_weight
from busbidder.scoring import Weights, departure_convenience, normalise_relative

from tests.helpers import CAM, make_offer, make_request

W4 = {"price": 0.4, "duration": 0.25, "departure": 0.15, "flexibility": 0.2}


class TestNormalisation(unittest.TestCase):
    def test_lower_is_better_inverted(self):
        self.assertEqual(normalise_relative([10, 20, 30], higher_is_better=False),
                         [100.0, 50.0, 0.0])

    def test_higher_is_better(self):
        self.assertEqual(normalise_relative([1, 3], higher_is_better=True), [0.0, 100.0])

    def test_equal_values_all_get_full_score(self):
        self.assertEqual(normalise_relative([25, 25], False), [100.0, 100.0])

    def test_single_offer(self):
        self.assertEqual(normalise_relative([42.0], False), [100.0])

    def test_spread_floor_keeps_tiny_differences_small(self):
        # EUR 30.00 vs 30.50 with a EUR 5 floor -> 100 vs 90, not 100 vs 0
        self.assertEqual(normalise_relative([30.0, 30.5], False, min_spread=5.0), [100.0, 90.0])

    def test_missing_value_gets_neutral_score(self):
        self.assertEqual(normalise_relative([10, None, 20], False), [100.0, 50.0, 0.0])
        self.assertEqual(normalise_relative([None, None], False), [50.0, 50.0])

    def test_robust_bounds_limit_extreme_value(self):
        values = [20, 21, 22, 23, 24, 25, 26, 27, 28, 500]
        plain = normalise_relative(values, False)
        robust = normalise_relative(values, False, robust=True)
        # with plain min-max the outlier squeezes all normal offers above 94
        self.assertGreater(min(plain[:-1]), 94)
        self.assertLess(robust[8], 50)   # 28 EUR now ~41 instead of ~98
        self.assertEqual(robust[-1], 0.0)

    def test_robust_equals_minmax_without_outliers(self):
        values = [20, 22, 25, 27, 30, 31]
        self.assertEqual(normalise_relative(values, False),
                         normalise_relative(values, False, robust=True))

    def test_scores_always_within_0_100(self):
        for s in normalise_relative([3, 7, 1000, -2, 55], False, robust=True, robust_min_n=3):
            self.assertTrue(0 <= s <= 100)


class TestDeparture(unittest.TestCase):
    def test_inside_and_outside_window(self):
        self.assertEqual(departure_convenience(time(9, 0), "morning"), 100.0)
        self.assertEqual(departure_convenience(time(13, 0), "morning"), 80.0)
        self.assertEqual(departure_convenience(time(23, 0), "morning"), 0.0)
        self.assertEqual(departure_convenience(time(3, 0), "any"), 100.0)

    def test_night_window_wraps_midnight(self):
        self.assertEqual(departure_convenience(time(23, 30), "night"), 100.0)
        self.assertEqual(departure_convenience(time(5, 0), "night"), 100.0)
        self.assertEqual(departure_convenience(time(21, 0), "night"), 80.0)


class TestWeights(unittest.TestCase):
    def test_fractions_and_percentages(self):
        self.assertAlmostEqual(sum(Weights.create(W4).values()), 1.0)
        w = Weights.parse("price=40,duration=25,departure=15,flexibility=20")
        self.assertAlmostEqual(w["price"], 0.4)

    def test_wrong_sum_rejected_unless_normalised(self):
        with self.assertRaises(WeightError):
            Weights.create({"price": 0.5, "duration": 0.6})
        w = Weights.create({"price": 2, "duration": 2}, normalise=True)
        self.assertEqual(w, {"price": 0.5, "duration": 0.5})

    def test_invalid_weights(self):
        for bad in [{"price": -0.1, "duration": 1.1}, {"comfort": 1.0}, {},
                    {"price": 0, "duration": 0}, {"price": "abc"}]:
            with self.assertRaises(WeightError, msg=bad):
                Weights.create(bad)
        with self.assertRaises(WeightError):
            Weights.parse("price40")

    def test_dominance_warning(self):
        self.assertTrue(Weights.create({"price": 0.7, "duration": 0.3}).dominance_warnings())
        self.assertFalse(Weights.create(W4).dominance_warnings())

    def test_shift_weight_keeps_sum(self):
        w2 = shift_weight(Weights.create(W4), "price", 0.1)
        self.assertAlmostEqual(w2["price"], 0.5)
        self.assertAlmostEqual(sum(w2.values()), 1.0)


class TestRanking(unittest.TestCase):
    def setUp(self):
        self.cheap_slow = make_offer("SOL-AGP-20260712-0700", dep=time(7, 0), arr=time(16, 0),
                                     price=25.0, transfers=1, changeable=False)
        self.fast_flex = make_offer("CAM-AGP-20260712-0900", company=CAM, dep=time(9, 0),
                                    arr=time(14, 30), price=45.0, changeable=True,
                                    refundable=True)
        self.offers = [self.cheap_slow, self.fast_flex]

    def top(self, weights, **req):
        return rank_offers(self.offers, make_request(**req), Weights.create(weights))[0]

    def test_total_is_weighted_sum(self):
        r = rank_offers(self.offers, make_request(), Weights.create(W4))
        for x in r:
            self.assertAlmostEqual(x.total, sum(W4[c] * x.criterion_scores[c] for c in W4),
                                   places=1)

    def test_different_weights_give_different_winners(self):
        self.assertIs(self.top({"price": 1.0}).offer, self.cheap_slow)
        self.assertIs(self.top({"duration": 0.5, "flexibility": 0.5}).offer, self.fast_flex)

    def test_ties_broken_deterministically_by_price(self):
        a = make_offer("SOL-AGP-20260712-0900", price=30.0)
        b = make_offer("CAM-AGP-20260712-0900", company=CAM, price=30.0)
        for order in ([a, b], [b, a]):
            r = rank_offers(order, make_request(), Weights.create({"flexibility": 1.0}))
            self.assertEqual([x.offer.offer_id for x in r],
                             ["CAM-AGP-20260712-0900", "SOL-AGP-20260712-0900"])
            self.assertTrue(r[1].tied_with_previous)

    def test_reproducible(self):
        a = rank_offers(self.offers, make_request(), Weights.create(W4))
        b = rank_offers(list(reversed(self.offers)), make_request(), Weights.create(W4))
        self.assertEqual([(x.offer.offer_id, x.total) for x in a],
                         [(x.offer.offer_id, x.total) for x in b])

    def test_empty_input(self):
        self.assertEqual(rank_offers([], make_request(), Weights.create(W4)), [])
        self.assertIn("No offer", explain_top([], Weights.create(W4)))

    def test_explanation_mentions_disadvantage_and_caveat(self):
        w = Weights.create({"duration": 0.5, "flexibility": 0.3, "price": 0.2})
        r = rank_offers(self.offers, make_request(), w)
        text = explain_top(r, w)
        self.assertIn("Camino Express", text)
        self.assertIn("Disadvantages: price", text)
        self.assertIn("not an objectively best", text)

    def test_missing_rating_marked(self):
        self.cheap_slow.rating = None
        r = rank_offers(self.offers, make_request(), Weights.create({"rating": 1.0}))
        missing = next(x for x in r if x.offer is self.cheap_slow)
        self.assertEqual(missing.missing, ["rating"])
        self.assertEqual(missing.criterion_scores["rating"], 50.0)

    def test_sensitivity_rows(self):
        rows = sensitivity(self.offers, make_request(), Weights.create(W4))
        self.assertEqual(len(rows), 8)


if __name__ == "__main__":
    unittest.main()
