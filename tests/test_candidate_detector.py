"""Candidate detection: keywords, context blocks, case-insensitivity."""
import unittest

from src.candidate_detector import find_candidates
from src.normalizer import NormalizedRow


def _row(sheet, num, text):
    cells = [c.strip() for c in text.split("|")]
    return NormalizedRow(sheet=sheet, row=num, cells=cells, text=text, raw=[])


class TestCandidateDetector(unittest.TestCase):
    def test_keyword_rows_found_case_insensitive(self):
        rows = [
            _row("GL", 1, "Date | Source | Description"),
            _row("GL", 2, "2024-01-08 | Receivable | Monthly RENTAL of unit #03-01"),
            _row("GL", 3, "2024-01-09 | Bank | Bank charges"),
        ]
        blocks = find_candidates(rows)
        self.assertTrue(blocks)
        covered = {r.row for b in blocks for r in b.rows}
        self.assertIn(2, covered)

    def test_context_included_not_isolated_row(self):
        rows = [
            _row("GL", 10, "Rental Income"),
            _row("GL", 11, "2024-01-08 | Receivable | HTL Music Bar"),
            _row("GL", 12, "2024-02-08 | Receivable | HTL Music Bar"),
            _row("GL", 13, "Total Rental Income"),
        ]
        blocks = find_candidates(rows)
        self.assertTrue(blocks)
        # block should include surrounding context rows, not only the hit
        biggest = max(len(b.rows) for b in blocks)
        self.assertGreater(biggest, 1)

    def test_irrelevant_rows_ignored(self):
        rows = [
            _row("GL", 1, "2024-01-10 | Payable | ACCRAFILE PTE LTD"),
            _row("GL", 2, "2024-01-11 | Payable | Bank charges"),
        ]
        self.assertEqual(find_candidates(rows), [])

    def test_reference_pattern_detected(self):
        rows = [_row("S1", 5, "09 | GL-JE | HTL Music Bar | Rent/41 | 8000")]
        blocks = find_candidates(rows)
        self.assertTrue(blocks)


if __name__ == "__main__":
    unittest.main()
