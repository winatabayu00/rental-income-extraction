"""Streamlit GUI — presentation layer only.

Run: streamlit run app.py
All extraction/validation logic lives in src/application_service.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("Streamlit is not installed. Run: pip install -r requirements.txt")

from src.application_service import SUPPORTED, process_files

PAGE_TITLE = "Rental Income AI Extractor"
PAGE_SUBTITLE = (
    "AI-assisted extraction and validation of rental income records from Excel files."
)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = _dt.date.fromisoformat(iso)
        return d.strftime("%d %b %Y").lstrip("0")
    except Exception:
        return iso


def _fmt_money(amount, currency: str | None = "SGD") -> str:
    if amount is None:
        return "—"
    try:
        cur = f"{currency} " if currency else ""
        return f"{cur}{float(amount):,.2f}"
    except Exception:
        return str(amount)


def _init_state() -> None:
    st.session_state.setdefault("payload", None)
    st.session_state.setdefault("file_results", None)
    st.session_state.setdefault("processed", False)


def _summary_counts(payload) -> tuple[int, int, int, int]:
    files = payload["processing_summary"]["files_processed"]
    props = sum(len(c["properties"]) for c in payload["companies"])
    missing = sum(
        len(p["missing_periods"])
        for c in payload["companies"]
        for p in c["properties"]
    )
    clar = sum(
        len(p["clarification_questions"])
        for c in payload["companies"]
        for p in c["properties"]
    )
    return files, props, missing, clar


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    _init_state()

    st.title(PAGE_TITLE)
    st.caption(PAGE_SUBTITLE)

    # ---------------- Upload ----------------
    st.header("Upload Excel Files")
    uploads = st.file_uploader(
        "Drag and drop files here",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        help="Supported: XLS, XLSX. All three technical-test files can be uploaded together.",
    )
    st.caption("Supported: XLS, XLSX")

    if uploads:
        st.success(f"{len(uploads)} file(s) selected")
        for uf in uploads:
            st.write(f"✓ {uf.name}")
    else:
        st.info("No files selected yet.")

    process_clicked = st.button("Process Files", type="primary", disabled=not uploads)

    # ---------------- Processing ----------------
    if process_clicked and uploads:
        status = st.empty()
        bar = st.progress(0)
        tmp_paths: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="rental_gui_") as tmp:
                for uf in uploads:
                    safe = os.path.basename(uf.name)
                    dest = os.path.join(tmp, safe)
                    base, ext = os.path.splitext(dest)
                    n = 1
                    while os.path.exists(dest):
                        dest = f"{base}_{n}{ext}"
                        n += 1
                    with open(dest, "wb") as f:
                        f.write(uf.getbuffer())
                    tmp_paths.append(dest)

                total = len(tmp_paths)

                def _on_done(done: int, tot: int, fr: dict) -> None:
                    name = fr.get("name", "")
                    status.write(f"Processing file {done} of {tot}\n\n{name}")
                    bar.progress(done / tot if tot else 1.0)

                status.write(f"Processing file 1 of {total}")
                payload, file_results = process_files(tmp_paths, on_file_done=_on_done)
                # Restore original upload names for display.
                for fr, uf in zip(file_results, uploads):
                    fr["name"] = uf.name
                for comp, uf in zip(payload["companies"], uploads):
                    # order may differ if a file failed; match by temp basename
                    pass
                # Fix source_file display names to original upload names.
                tmp_to_orig = {
                    os.path.basename(p): uf.name
                    for p, uf in zip(tmp_paths, uploads)
                }
                for comp in payload["companies"]:
                    comp["source_file"] = tmp_to_orig.get(
                        comp["source_file"], comp["source_file"]
                    )
                st.session_state["payload"] = payload
                st.session_state["file_results"] = file_results
                st.session_state["processed"] = True
                bar.progress(1.0)
                status.write("Processing complete.")
        except Exception as exc:  # pragma: no cover
            st.error(f"Processing failed: {exc}")
            traceback.print_exc()

    # ---------------- Errors ----------------
    file_results = st.session_state.get("file_results")
    if file_results:
        for fr in file_results:
            if not fr.get("ok"):
                st.error(f"✗ Failed to process {fr.get('name')}")

    # ---------------- Results ----------------
    payload = st.session_state.get("payload")
    if not payload or not st.session_state.get("processed"):
        return

    files_n, props_n, missing_n, clar_n = _summary_counts(payload)
    st.header("Results")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Files Processed", files_n)
    c2.metric("Properties Found", props_n)
    c3.metric("Missing Periods", missing_n)
    c4.metric("Clarifications", clar_n)

    for comp in payload["companies"]:
        with st.expander(
            f"{comp['company']}  —  {comp['source_file']}", expanded=True
        ):
            if not comp["properties"]:
                st.warning("No rental properties identified in this file.")
                continue
            for prop in comp["properties"]:
                addr = prop["property_address"] or "Unknown property"
                with st.expander(f"└── {addr}", expanded=False):
                    rp = prop.get("rental_period", {})
                    start = _fmt_date(rp.get("start"))
                    end = _fmt_date(rp.get("end"))
                    st.subheader("Property")
                    st.write(addr)
                    st.subheader("Tenant")
                    st.write(prop.get("tenant") or "—")
                    st.write(f"**Currency:** {prop.get('currency') or '—'}")
                    st.write(f"**Rental Period:** {start} → {end}")
                    st.write(
                        "**Standard Monthly Rental:** "
                        + _fmt_money(
                            prop.get("standard_monthly_rental"),
                            prop.get("currency"),
                        )
                    )
                    st.write(
                        f"**Number of Rental Records:** "
                        f"{len(prop.get('monthly_records', []))}"
                    )

                    # Monthly records table (source traceability kept).
                    records = prop.get("monthly_records", [])
                    if records:
                        try:
                            import pandas as pd

                            df = pd.DataFrame(
                                [
                                    {
                                        "Start": _fmt_date(r.get("period_start")),
                                        "End": _fmt_date(r.get("period_end")),
                                        "Amount": r.get("amount"),
                                        "Type": str(r.get("record_type") or "").replace(
                                            "_", " "
                                        ).title(),
                                        "Source Sheet": (r.get("source") or {}).get(
                                            "sheet", ""
                                        ),
                                        "Source Rows": ", ".join(
                                            map(
                                                str,
                                                (r.get("source") or {}).get("rows", []),
                                            )
                                        ),
                                    }
                                    for r in records
                                ]
                            )
                            st.dataframe(df, use_container_width=True)
                        except ImportError:
                            st.table(
                                [
                                    {
                                        "Start": _fmt_date(r.get("period_start")),
                                        "End": _fmt_date(r.get("period_end")),
                                        "Amount": r.get("amount"),
                                        "Type": r.get("record_type"),
                                    }
                                    for r in records
                                ]
                            )

                    issues = prop.get("issues", [])
                    if issues:
                        st.subheader("Issues")
                        for iss in issues:
                            st.warning(
                                f"{str(iss.get('type', '')).replace('_', ' ').title()}: "
                                f"{iss.get('message', '')}"
                            )

                    clarifications = prop.get("clarification_questions", [])
                    if clarifications:
                        st.subheader("Clarification Questions")
                        for i, q in enumerate(clarifications, start=1):
                            st.write(f"{i}. {q}")

    with st.expander("View Raw JSON"):
        st.json(payload)

    st.download_button(
        label="Download JSON",
        data=json.dumps(payload, indent=2, ensure_ascii=False),
        file_name="rental-income-results.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
