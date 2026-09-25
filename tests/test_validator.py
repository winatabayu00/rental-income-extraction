"""Validator: duplicates, overlaps, amount inconsistency, address grouping."""
import unittest

from src.models import AIRecord
from src.rental_validator import group_by_property, validate_property


def rec(addr, s, e, amt, rtype="monthly_rent", tenant=None, rows=None):
    return AIRecord(
        property_address=addr,
        tenant=tenant,
        period_start=s,
        period_end=e,
        amount=amt,
        currency="SGD",
        record_type=rtype,
        confidence=0.9,
        source_rows=rows or [1],
        source_sheet="GL",
    )


class TestValidator(unittest.TestCase):
    def test_duplicate_period(self):
        recs = [
            rec("A", "2024-01-01", "2024-01-31", 10000, rows=[1]),
            rec("A", "2024-01-01", "2024-01-31", 10000, rows=[2]),
        ]
        _, issues, _ = validate_property("A", recs, "f.xlsx")
        self.assertTrue(any(i.type == "DUPLICATE_PERIOD" for i in issues))

    def test_overlapping_period(self):
        recs = [
            rec("A", "2024-01-01", "2024-01-31", 10000, rows=[1]),
            rec("A", "2024-01-15", "2024-02-15", 10000, rows=[2]),
        ]
        _, issues, _ = validate_property("A", recs, "f.xlsx")
        self.assertTrue(any(i.type == "OVERLAPPING_PERIOD" for i in issues))

    def test_overlap_ignored_for_adjustment(self):
        recs = [
            rec("A", "2024-01-01", "2024-01-31", 10000, rows=[1]),
            rec("A", "2024-01-15", "2024-02-15", -500, rtype="adjustment", rows=[2]),
        ]
        _, issues, _ = validate_property("A", recs, "f.xlsx")
        self.assertFalse(any(i.type == "OVERLAPPING_PERIOD" for i in issues))

    def test_amount_inconsistency(self):
        recs = [
            rec("A", "2024-01-01", "2024-01-31", 10000, rows=[1]),
            rec("A", "2024-02-01", "2024-02-29", 10000, rows=[2]),
            rec("A", "2024-03-01", "2024-03-31", 12000, rows=[3]),
            rec("A", "2024-04-01", "2024-04-30", 10000, rows=[4]),
        ]
        _, issues, _ = validate_property("A", recs, "f.xlsx")
        self.assertTrue(any(i.type == "AMOUNT_INCONSISTENCY" for i in issues))

    def test_missing_address(self):
        recs = [rec(None, "2024-01-01", "2024-01-31", 10000, rows=[5])]
        _, issues, _ = validate_property(None, recs, "f.xlsx")
        self.assertTrue(any(i.type == "MISSING_PROPERTY_ADDRESS" for i in issues))

    def test_address_grouping_case_insensitive(self):
        recs = [
            rec("29 Arab St #01-01", "2024-01-01", "2024-01-31", 5500, rows=[1]),
            rec("29  Arab St  #01-01", "2024-02-01", "2024-02-29", 5500, rows=[2]),
        ]
        groups = group_by_property(recs)
        self.assertEqual(len(groups), 1)


if __name__ == "__main__":
    unittest.main()
