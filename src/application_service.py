"""Central application/service layer.

Both CLI (main.py) and Streamlit GUI (app.py) call this module.
No business logic lives in the presentation layer.
"""
from __future__ import annotations

import os
import tempfile
import traceback
from collections import Counter
from typing import Any, Dict, List, Tuple

from . import config
from .candidate_detector import find_candidates
from .clarification_service import questions_for_property
from .excel_reader import read_workbook
from .extraction_service import infer_company, run_extraction
from .models import AIRecord, Issue, MissingPeriod
from .normalizer import normalize_workbook
from .output_writer import write_results
from .rental_validator import (
    detect_coverage_gaps,
    group_by_property,
    validate_property,
)

SUPPORTED = (".xlsx", ".xls")


def discover_files(input_dir: str) -> List[str]:
    if not os.path.isdir(input_dir):
        input_dir = "."
    files: List[str] = []
    for name in sorted(os.listdir(input_dir)):
        p = os.path.join(input_dir, name)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in SUPPORTED:
            files.append(p)
        elif ext in (".csv", ".xlsm", ".xlsb", ".ods", ".numbers"):
            print(f"  ! Skipping unsupported file: {name}")
    return files


def build_property_payload(
    display_address: str | None,
    records: List[AIRecord],
    source_file: str,
    coverage_missing: List[MissingPeriod] | None = None,
) -> Dict[str, Any]:
    records_sorted = sorted(
        records, key=lambda r: (r.period_start or "", r.period_end or "")
    )
    extra, issues, _ = validate_property(display_address, records_sorted, source_file)
    coverage_missing = coverage_missing or []
    for m in coverage_missing:
        issues.append(
            Issue(
                type="MISSING_RENTAL_PERIOD",
                severity="warning",
                message=(
                    f"No rental record identified for {m.expected_start} "
                    f"to {m.expected_end}."
                ),
                context={
                    "expected_start": m.expected_start,
                    "expected_end": m.expected_end,
                    "coverage": "tail_or_head",
                },
            )
        )
    all_missing = list(extra["missing"]) + list(coverage_missing)

    monthly_records = []
    for r in records_sorted:
        monthly_records.append(
            {
                "period_start": r.period_start,
                "period_end": r.period_end,
                "amount": abs(r.amount) if r.amount is not None else None,
                "amount_signed": r.amount,
                "currency": r.currency,
                "record_type": r.record_type,
                "tenant": r.tenant,
                "confidence": r.confidence,
                "transaction_date": r.transaction_date,
                "source": {"sheet": r.source_sheet, "rows": r.source_rows},
            }
        )
    currencies = [r.currency for r in records_sorted if r.currency]
    tenants = [r.tenant for r in records_sorted if r.tenant]
    currency = Counter(currencies).most_common(1)[0][0] if currencies else None
    tenant = Counter(tenants).most_common(1)[0][0] if tenants else None

    return {
        "property_address": display_address,
        "tenant": tenant,
        "currency": currency,
        "rental_period": {"start": extra["rental_start"], "end": extra["rental_end"]},
        "standard_monthly_rental": extra["standard"],
        "monthly_records": monthly_records,
        "missing_periods": [
            {"expected_start": m.expected_start, "expected_end": m.expected_end}
            for m in all_missing
        ],
        "issues": [i.model_dump() for i in issues],
        "clarification_questions": questions_for_property(display_address, issues),
    }


def process_file(path: str) -> Dict[str, Any]:
    """Process one workbook path. Raises on failure (caller isolates errors)."""
    wb = read_workbook(path)
    rows = normalize_workbook(wb)
    company = infer_company(wb, rows)
    blocks = find_candidates(rows)
    records, stats = run_extraction(wb, rows, blocks)
    groups = group_by_property(records)
    coverage = detect_coverage_gaps(groups)
    properties = []
    for key in sorted(groups):
        recs = groups[key]
        display = next((r.property_address for r in recs if r.property_address), None)
        properties.append(
            build_property_payload(display, recs, wb.file, coverage.get(key, []))
        )
    properties.sort(
        key=lambda p: (p["property_address"] is None, p["property_address"] or "")
    )
    missing_total = sum(len(p["missing_periods"]) for p in properties)
    clar_total = sum(len(p["clarification_questions"]) for p in properties)
    return {
        "source_file": wb.file,
        "company": company,
        "properties": properties,
        "stats": {
            "sheets_scanned": len(wb.sheets),
            "rental_candidates": stats.get("rental_candidates", len(records)),
            "properties_identified": len(properties),
            "missing_periods": missing_total,
            "clarifications": clar_total,
            "ai_used": stats.get("ai_used", 0),
        },
    }


def process_files(
    paths: List[str], on_file_done: Any = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Process many workbook paths.

    One file's failure never stops the rest. Returns (payload, file_results)
    where file_results[i] is {"ok": bool, "name": str, "result"|"error": ...}.
    Optional on_file_done(index, total, file_result) callback for progress UIs.
    """
    companies: List[Dict[str, Any]] = []
    failed: List[str] = []
    file_results: List[Dict[str, Any]] = []
    total = len(paths)
    for idx, path in enumerate(paths):
        name = os.path.basename(path)
        try:
            result = process_file(path)
            companies.append(
                {
                    "source_file": result["source_file"],
                    "company": result["company"],
                    "properties": result["properties"],
                }
            )
            fr: Dict[str, Any] = {"ok": True, "name": name, "result": result}
            file_results.append(fr)
        except Exception as e:  # isolate per-file errors
            failed.append(name)
            fr = {
                "ok": False,
                "name": name,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            file_results.append(fr)
        if on_file_done is not None:
            try:
                on_file_done(idx + 1, total, file_results[-1])
            except Exception:
                pass
    payload = {
        "processing_summary": {
            "files_processed": len(companies),
            "files_failed": len(failed),
            "failed_files": failed,
            "ai_enabled": config.ai_enabled(),
        },
        "companies": companies,
    }
    return payload, file_results


def process_files_to_output(
    paths: List[str], output_dir: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    payload, file_results = process_files(paths)
    out_path = write_results(payload, output_dir)
    return payload, file_results, out_path


def process_uploaded_files(
    uploads: List[Tuple[str, bytes]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Process in-memory Streamlit uploads via safe temp files.

    Original filenames are preserved in metadata; temp files are cleaned up.
    Only .xls/.xlsx are processed; others are reported as failures.
    """
    payload_companies: List[Dict[str, Any]] = []
    failed: List[str] = []
    file_results: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rental_upload_") as tmp:
        for filename, data in uploads:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED:
                failed.append(filename)
                file_results.append(
                    {"ok": False, "name": filename, "error": "Unsupported file type"}
                )
                continue
            # Preserve original filename inside the controlled temp dir.
            safe_name = os.path.basename(filename)
            tmp_path = os.path.join(tmp, safe_name)
            base, e = os.path.splitext(tmp_path)
            counter = 1
            while os.path.exists(tmp_path):
                tmp_path = f"{base}_{counter}{e}"
                counter += 1
            with open(tmp_path, "wb") as f:
                f.write(data)
            try:
                result = process_file(tmp_path)
                # Override with the user's original filename for display.
                result["source_file"] = safe_name
                payload_companies.append(
                    {
                        "source_file": safe_name,
                        "company": result["company"],
                        "properties": result["properties"],
                    }
                )
                file_results.append(
                    {"ok": True, "name": safe_name, "result": result}
                )
            except Exception as exc:
                failed.append(safe_name)
                file_results.append(
                    {
                        "ok": False,
                        "name": safe_name,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
    payload = {
        "processing_summary": {
            "files_processed": len(payload_companies),
            "files_failed": len(failed),
            "failed_files": failed,
            "ai_enabled": config.ai_enabled(),
        },
        "companies": payload_companies,
    }
    return payload, file_results
