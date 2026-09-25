"""Gap detection: mid-month cadence, calendar months, partial handling."""
import datetime as dt
import unittest

from src.models import AIRecord
from src.rental_validator import detect_missing_periods, validate_property


def rec(s, e, amt=10000, rtype="monthly_rent"):
    return AIRecord(
        property_address="P",
        tenant="T",
        period_start=s,
        period_end=e,
        amount=amt,
        currency="SGD",
        record_type=rtype,
        confidence=0.9,
        source_rows=[1],
        source_sheet="GL",
    )


class TestGapDetection(unittest.TestCase):
    def test_mid_month_gap(self):
        """16 Jan->15 Feb, 16 Feb->15 Mar, 16 Apr->15 May => missing 16 Mar->15 Apr."""
        recs = [
            rec("2024-01-16", "2024-02-15"),
            rec("2024-02-16", "2024-03-15"),
            rec("2024-04-16", "2024-05-15"),
        ]
        _, issues, _ = validate_property("P", recs, "f.xlsx")
        gaps = [i for i in issues if i.type == "MISSING_RENTAL_PERIOD"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].context["expected_start"], "2024-03-16")
        self.assertEqual(gaps[0].context["expected_end"], "2024-04-15")

    def test_calendar_month_no_gap(self):
        recs = [
            rec("2024-01-01", "2024-01-31"),
            rec("2024-02-01", "2024-02-29"),
            rec("2024-03-01", "2024-03-31"),
        ]
        _, issues, _ = validate_property("P", recs, "f.xlsx")
        self.assertFalse(any(i.type == "MISSING_RENTAL_PERIOD" for i in issues))

    def test_detect_missing_direct(self):
        periods = [
            (dt.date(2024, 1, 16), dt.date(2024, 2, 15)),
            (dt.date(2024, 2, 16), dt.date(2024, 3, 15)),
            (dt.date(2024, 4, 16), dt.date(2024, 5, 15)),
        ]
        missing = detect_missing_periods(periods)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].expected_start, "2024-03-16")
        self.assertEqual(missing[0].expected_end, "2024-04-15")

    def test_partial_not_counted_as_missing(self):
        """1 Jan->15 Jan (partial) + 16 Jan->15 Feb should not create a gap."""
        recs = [
            rec("2024-01-01", "2024-01-15", rtype="partial_rent"),
            rec("2024-01-16", "2024-02-15"),
        ]
        _, issues, _ = validate_property("P", recs, "f.xlsx")
        self.assertFalse(any(i.type == "MISSING_RENTAL_PERIOD" for i in issues))
        self.assertTrue(any(i.type == "PARTIAL_RENTAL" for i in issues))


if __name__ == "__main__":
    unittest.main()
