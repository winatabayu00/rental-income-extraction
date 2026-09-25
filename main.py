#!/usr/bin/env python3
"""Rental Income AI Extractor — CLI entry point (thin presentation layer).

Pipeline: Excel -> normalization -> candidate detection -> AI extraction
-> deterministic validation -> clarification generation -> CLI output.
All business logic lives in src/application_service.py.
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config
from src.application_service import discover_files, process_files
from src.output_writer import write_results


def main() -> int:
    input_dir = sys.argv[1] if len(sys.argv) > 1 else config.INPUT_DIR
    output_dir = sys.argv[2] if len(sys.argv) > 2 else config.OUTPUT_DIR
    print("Rental Income AI Extractor")
    print("────────────────────────────────────")
    files = discover_files(input_dir)
    print(f"\nFound {len(files)} Excel file(s).\n")
    payload, file_results = process_files(files)
    for i, fr in enumerate(file_results, start=1):
        print(f"[{i}/{len(file_results)}] Processing {fr['name']}")
        if fr["ok"]:
            s = fr["result"]["stats"]
            print(f"      Sheets scanned: {s['sheets_scanned']}")
            print(f"      Rental candidates: {s['rental_candidates']}")
            print(f"      Properties identified: {s['properties_identified']}")
            print(f"      Missing periods: {s['missing_periods']}")
            print(f"      Clarifications: {s['clarifications']}")
            print("      ✓ Completed")
        else:
            print(f"      ✗ Failed — {fr['error']}")
            traceback.print_exc()
        print()
    print("────────────────────────────────────")
    summary = payload["processing_summary"]
    print(f"\nFiles processed : {summary['files_processed']}")
    print(f"Files failed    : {summary['files_failed']}")
    for f in summary["failed_files"]:
        print(f"  ✗ {f}")
    out_path = write_results(payload, output_dir)
    print(f"\nOutput:\n{out_path}")
    return 0 if summary["files_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
