"""Task 2: loading and validation - normal, invalid, missing-data and boundary cases."""

import csv
import tempfile
import unittest
from pathlib import Path

from busbidder.exceptions import DataFileError, RecordValidationError
from busbidder.loader import OFFER_COLUMNS, load_offers, parse_offer
from busbidder.validation import is_valid_booking_reference

from tests.helpers import COMPANIES, DESTINATIONS, csv_row

SCALE = (1.0, 5.0)


def parse(**kw):
    return parse_offer(csv_row(**kw), COMPANIES, DESTINATIONS, SCALE)


class TestValidRecords(unittest.TestCase):
    def test_valid_row_is_parsed_with_correct_types(self):
        offer, notes = parse()
        self.assertEqual(offer.price_eur, 30.0)
        self.assertEqual(offer.duration_min, 360)
        self.assertTrue(offer.fare.changeable)
        self.assertEqual(notes, [])

    def test_overnight_offer_with_day_offset_is_valid(self):
        offer, _ = parse(offer_id="SOL-AGP-20260712-2300", departure="23:00",
                         arrival="06:00", arrival_day_offset="1")
        self.assertEqual(offer.duration_min, 420)

    def test_boundary_rating_values_accepted(self):
        self.assertEqual(parse(rating="1.0")[0].rating, 1.0)
        self.assertEqual(parse(rating="5.0")[0].rating, 5.0)

    def test_zero_seats_kept_but_flagged_sold_out(self):
        offer, _ = parse(seats_available="0")
        self.assertIn("SOLD_OUT", offer.flags)


class TestInvalidRecords(unittest.TestCase):
    def assertRejected(self, reason, **kw):
        with self.assertRaises(RecordValidationError) as ctx:
            parse(**kw)
        self.assertIn(reason, ctx.exception.reasons)

    def test_negative_price(self):
        self.assertRejected("NEGATIVE_PRICE", price_eur="-5.00")

    def test_non_numeric_price(self):
        self.assertRejected("INVALID_PRICE", price_eur="cheap")

    def test_unknown_destination(self):
        self.assertRejected("UNKNOWN_DESTINATION", destination="Atlantis")

    def test_unknown_company(self):
        self.assertRejected("UNKNOWN_COMPANY", company_id="XYZ")

    def test_invalid_calendar_date(self):
        self.assertRejected("INVALID_DATE", travel_date="2026-02-30")

    def test_wrong_date_format(self):
        self.assertRejected("INVALID_DATE", travel_date="12/07/2026")

    def test_arrival_before_departure(self):
        self.assertRejected("ARRIVAL_BEFORE_DEPARTURE", arrival="08:00")

    def test_arrival_equal_departure_is_boundary_reject(self):
        self.assertRejected("ARRIVAL_BEFORE_DEPARTURE", arrival="09:00")

    def test_rating_outside_scale(self):
        self.assertRejected("RATING_OUT_OF_SCALE", rating="5.1")
        self.assertRejected("RATING_OUT_OF_SCALE", rating="0.9")

    def test_negative_seats(self):
        self.assertRejected("NEGATIVE_SEATS", seats_available="-1")

    def test_malformed_offer_id(self):
        self.assertRejected("MALFORMED_OFFER_ID", offer_id="sol_agp_1")

    def test_offer_id_inconsistent_with_fields(self):
        self.assertRejected("OFFER_ID_MISMATCH", departure="10:00", arrival="15:00")

    def test_all_problems_reported_at_once(self):
        with self.assertRaises(RecordValidationError) as ctx:
            parse(price_eur="-1", rating="9")
        self.assertEqual({"NEGATIVE_PRICE", "RATING_OUT_OF_SCALE"}, set(ctx.exception.reasons))


class TestMissingData(unittest.TestCase):
    def test_missing_price_rejected(self):
        with self.assertRaises(RecordValidationError) as ctx:
            parse(price_eur="")
        self.assertIn("MISSING_PRICE", ctx.exception.reasons)

    def test_missing_optional_rating_and_co2_kept(self):
        offer, _ = parse(rating="", co2_kg="")
        self.assertIsNone(offer.rating)
        self.assertIn("MISSING_RATING", offer.flags)
        self.assertIn("MISSING_CO2", offer.flags)


class TestCorrections(unittest.TestCase):
    def test_formatting_problems_are_corrected_and_noted(self):
        offer, notes = parse(destination="  MÁLAGA ", price_eur="30,50", changeable="Y",
                             company_id="sol")
        self.assertEqual(offer.destination.name, "Malaga")
        self.assertEqual(offer.price_eur, 30.5)
        self.assertTrue(offer.fare.changeable)
        self.assertEqual(len(notes), 4)


class TestFileLevel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows, header=OFFER_COLUMNS):
        p = self.dir / "offers.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return p

    def test_missing_file_raises_data_file_error(self):
        with self.assertRaises(DataFileError):
            load_offers(self.dir / "nope.csv", COMPANIES, DESTINATIONS)

    def test_missing_column_raises_data_file_error(self):
        p = self.write([csv_row()], header=OFFER_COLUMNS[:-1])
        with self.assertRaises(DataFileError):
            load_offers(p, COMPANIES, DESTINATIONS)

    def test_bad_rows_rejected_good_rows_kept_and_duplicates_detected(self):
        rows = [csv_row(), csv_row(), csv_row(offer_id="SOL-AGP-20260712-1000",
                                              departure="10:00", price_eur="-1")]
        rep = load_offers(self.write(rows), COMPANIES, DESTINATIONS)
        self.assertEqual(len(rep.offers), 1)
        self.assertEqual([r.reasons for r in rep.rejected],
                         [["DUPLICATE_ID"], ["NEGATIVE_PRICE"]])

    def test_price_outlier_kept_and_flagged_for_review(self):
        rows = [csv_row(offer_id=f"SOL-AGP-20260712-{h:02d}00", departure=f"{h:02d}:00",
                        arrival=f"{h + 6:02d}:00") for h in range(6, 11)]
        rows[-1]["price_eur"] = "300.00"
        rep = load_offers(self.write(rows), COMPANIES, DESTINATIONS, outlier_factor=3.0)
        self.assertEqual(len(rep.offers), 5)
        self.assertEqual(len(rep.review), 1)


class TestRegex(unittest.TestCase):
    def test_booking_reference_format(self):
        self.assertTrue(is_valid_booking_reference("BBS-AB23CD"))
        for bad in ["BBS-AB0CDE", "bbs-AB23CD", "BBS-AB23C", "XBS-AB23CD", "BBS-AB23CDE"]:
            self.assertFalse(is_valid_booking_reference(bad), bad)


if __name__ == "__main__":
    unittest.main()
