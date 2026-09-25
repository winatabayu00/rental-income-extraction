"""Normalizer: date/amount parsing and address normalization."""
import unittest

from src.extraction_service import parse_period_from_description
from src.normalizer import normalize_address, try_parse_amount


class TestNormalizer(unittest.TestCase):
    def test_amount_parsing(self):
        self.assertEqual(try_parse_amount("37,325.50"), 37325.50)
        self.assertEqual(try_parse_amount("$15,000"), 15000.0)
        self.assertEqual(try_parse_amount("(500)"), -500.0)
        self.assertEqual(try_parse_amount(8000), 8000.0)
        self.assertEqual(try_parse_amount(8000.0), 8000.0)
        self.assertIsNone(try_parse_amount(""))
        self.assertIsNone(try_parse_amount(None))

    def test_from_to_period(self):
        s, e = parse_period_from_description(
            "IAI AISA PTE LTD - Monthly rental of Suntec City Tower One #09-03A\n"
            "From 16 January 2024 to 15 February 2024"
        )
        self.assertEqual(s, "2024-01-16")
        self.assertEqual(e, "2024-02-15")

    def test_paren_range(self):
        s, e = parse_period_from_description(
            "Being half-rental for Jan 2024 (1/1/24-15/1/24) recognised"
        )
        self.assertEqual(s, "2024-01-01")
        self.assertEqual(e, "2024-01-15")

    def test_address_normalization(self):
        self.assertEqual(
            normalize_address("  Suntec City  Tower One #09-03A "),
            "suntec city tower one #09-03a",
        )
        self.assertEqual(
            normalize_address("29 Arab St #01-01"),
            normalize_address("29  Arab St  #01-01"),
        )


if __name__ == "__main__":
    unittest.main()
