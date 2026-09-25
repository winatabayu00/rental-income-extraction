"""Reader must open all three supplied workbooks without crashing (M01)."""
import os
import unittest

from src.excel_reader import read_workbook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATE_DIRS = [os.path.join(ROOT, "input"), ROOT]


def find_test_files():
    out = []
    seen = set()
    for d in CANDIDATE_DIRS:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.lower().endswith((".xlsx", ".xls")):
                p = os.path.join(d, name)
                if p not in seen:
                    seen.add(p)
                    out.append(p)
    return sorted(out)


class TestExcelReader(unittest.TestCase):
    def test_all_supplied_files_open(self):
        files = find_test_files()
        self.assertGreaterEqual(len(files), 3, f"expected >=3 files, got {files}")
        for path in files:
            wb = read_workbook(path)
            self.assertGreaterEqual(len(wb.sheets), 1)
            total_rows = sum(len(s.rows) for s in wb.sheets)
            self.assertGreater(total_rows, 0, f"{path} has no rows")

    def test_xlsx_and_xls_covered(self):
        files = find_test_files()
        exts = {os.path.splitext(f)[1].lower() for f in files}
        self.assertIn(".xlsx", exts)
        self.assertIn(".xls", exts)


if __name__ == "__main__":
    unittest.main()
