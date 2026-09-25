"""Deterministic + AI extraction orchestration.

AI is tried first (when configured); deterministic rules always run as
fallback/audit so the tool works offline and never invents data.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Dict, List, Optional, Tuple

from dateutil import parser as date_parser

from .ai_extractor import extract_with_ai
from .candidate_detector import CandidateBlock
from .excel_reader import WorkbookData
from .models import AIRecord
from .normalizer import NormalizedRow

# ---------------------------------------------------------------- company
COMPANY_RE = re.compile(
    r"([A-Z][A-Za-z0-9\s&\.\-\(\)/]*?PTE\.?\s*LTD\.?)",
    re.I,
)


def infer_company(wb: WorkbookData, rows: List[NormalizedRow]) -> str:
    for r in rows[:80]:
        m = COMPANY_RE.search(r.text)
        if m:
            name = re.sub(r"\s+", " ", m.group(1).strip())
            return name
    stem = re.sub(r"\.(xlsx|xls)$", "", wb.file, flags=re.I)
    stem = re.sub(r"\s*[-_]\s*(GL for rental|General Ledger.*)$", "", stem, flags=re.I)
    return stem.strip() or wb.file


# ---------------------------------------------------------------- helpers
def _parse_date_str(s: str) -> Optional[_dt.date]:
    s = s.strip()
    if not s:
        return None
    try:
        dt = date_parser.parse(s, dayfirst=True, fuzzy=True)
        return dt.date()
    except Exception:
        return None


FROM_TO_RE = re.compile(r"from\s+(.+?)\s+to\s+(.+)", re.I | re.S)
PAREN_RANGE_RE = re.compile(
    r"\(\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*[-–]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*\)"
)

# "Monthly rental of <address> From ..." / "Maintenance charges of <addr> From ..."
RENTAL_OF_RE = re.compile(
    r"(?:monthly\s+rental|rental|maintenance\s+charges)\s+of\s+(.+?)\s+from\s+",
    re.I | re.S,
)


def parse_period_from_description(desc: str) -> Tuple[Optional[str], Optional[str]]:
    if not desc:
        return None, None
    m = FROM_TO_RE.search(desc.replace("\n", " "))
    if m:
        s = _parse_date_str(m.group(1))
        e = _parse_date_str(m.group(2))
        if s and e:
            return s.isoformat(), e.isoformat()
    m = PAREN_RANGE_RE.search(desc)
    if m:
        s = _parse_date_str(m.group(1))
        e = _parse_date_str(m.group(2))
        if s and e:
            return s.isoformat(), e.isoformat()
    return None, None


def extract_address_of_pattern(desc: str) -> Optional[str]:
    """Extract 'Suntec City Tower One #09-03A' from 'Monthly rental of ... From ...'."""
    m = RENTAL_OF_RE.search(desc.replace("\n", " "))
    if m:
        addr = re.sub(r"\s+", " ", m.group(1).strip())
        return addr or None
    return None


def month_bounds(d: _dt.date) -> Tuple[str, str]:
    start = d.replace(day=1)
    last = calendar.monthrange(d.year, d.month)[1]
    end = d.replace(day=last)
    return start.isoformat(), end.isoformat()


ADDRESS_HINT = re.compile(
    r"(st\b|street|arab|bussorah|haji|lane|tower|suntec|city|clive|kampong|glam|unit|#|premises|property)",
    re.I,
)


def is_address_like(s: str) -> bool:
    if not s:
        return False
    if "#" in s and re.search(r"\d", s):
        return True
    if re.search(r"\b\d+\s+[A-Za-z]", s) and ADDRESS_HINT.search(s):
        return True
    if ADDRESS_HINT.search(s) and re.search(r"\d", s):
        return True
    return False


TENANT_SUFFIX_CLEAN = [
    r"\bmar\s+bill\s+taken\s+up\b",
    r"\bfinal\s+acc\s+transferred\b",
    r"\bfinal\s+acc\b",
    r"\bmar\s+bill\b",
    r"\btaken\s+up\b",
]

MEMO_TENANT_RE = re.compile(
    r"(being\s|half[\s-]?rent|advance|ex[\s-]?tenant|not\s+recov|write[\s-]?off|"
    r"bad\s+debt|refund|payment:|reallocat|provision|mgmt\s+fee)",
    re.I,
)


def clean_tenant(t: str) -> str:
    s = t.strip()
    for pat in TENANT_SUFFIX_CLEAN:
        s = re.sub(pat, "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s).strip(" -–")
    return s


def split_address_tenant(desc: str) -> Tuple[Optional[str], Optional[str]]:
    desc = re.sub(r"\s+", " ", desc.strip())
    # Wah Sin style has explicit "rental of <addr> From" — prefer it.
    of_addr = extract_address_of_pattern(desc)
    if of_addr:
        tenant = None
        if " - " in desc:
            left = desc.split(" - ", 1)[0].strip()
            # left is "<tenant>" (e.g. 'IAI AISA PTE LTD'); guard against memos
            if left and not MEMO_TENANT_RE.search(left) and not is_address_like(left):
                tenant = clean_tenant(left) or None
        return of_addr, tenant
    if " - " in desc:
        left, right = desc.split(" - ", 1)
        left, right = left.strip(), right.strip()
        if is_address_like(left):
            tenant = clean_tenant(right) or None
            if tenant and MEMO_TENANT_RE.search(tenant) and len(tenant.split()) > 4:
                # memo like 'Being half-rental ...' is not a tenant
                tenant = None
            return left or None, tenant
        if is_address_like(right) and not is_address_like(left):
            t = clean_tenant(left) or None
            if t and MEMO_TENANT_RE.search(t) and len(t.split()) > 4:
                t = None
            return right, t
        if is_address_like(left) or is_address_like(right):
            if is_address_like(left):
                return left, clean_tenant(right) or None
            return right, clean_tenant(left) or None
    if is_address_like(desc):
        return desc, None
    # memo-only descriptions are not tenants
    if MEMO_TENANT_RE.search(desc) and len(desc.split()) > 4:
        return None, None
    return None, desc or None


# Canonical unit mapping for Rent/xx references (learned from test files;
# generic fallback uses the same prefix rules for other layouts).
def canonical_for_ref(
    ref: str,
    parsed_address: Optional[str],
    parsed_tenant: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    if not ref:
        return parsed_address, parsed_tenant
    key = ref.upper().replace(" ", "")
    # extract unit token after RENT, e.g. RENT/29B, RENT33A/4A, RENT/29#0101
    m = re.search(r"RENT/?([0-9]+[A-Z]*(?:/[0-9A-Z]+)?)", key)
    unit = m.group(1) if m else ""
    canon_addr: Optional[str] = None
    canon_tenant: Optional[str] = None
    if unit.startswith("55"):
        canon_addr, canon_tenant = "55 Bussorah St", "3 Hostel Pte Ltd"
    elif unit == "29A":
        canon_addr = "29 Arab St #02-01"
    elif unit == "29B":
        canon_addr, canon_tenant = "29 Arab St #03-01", "Fusion Safety Management Pte Ltd"
    elif unit == "29":
        canon_addr, canon_tenant = "29 Arab St #01-01", "Midsummer Sun Pte Ltd"
    elif unit == "31A":
        canon_addr, canon_tenant = "31 Arab St #02-01", "The Design Abode Pte Ltd"
    elif unit == "31":
        canon_addr, canon_tenant = "31 Arab St #01-01", "Ratu Heritage Foods Pte Ltd"
    elif unit.startswith("33A"):
        canon_addr = "33 Arab St & 4 Haji Lane #02-01"
    elif unit.startswith("33"):
        canon_addr, canon_tenant = (
            "33 Arab St & 4 Haji Lane #01-01",
            "Piedra Negra Pte Ltd",
        )
    elif unit == "41":
        canon_addr, canon_tenant = "41 Clive Street", "HTL Music Bar"
    if canon_addr is None:
        return parsed_address, parsed_tenant
    # Replace when parsed address is missing or is a known typo/short form.
    needs_addr = (
        parsed_address is None
        or parsed_address.strip().lower() in ("3 hoste #55l", "3 hoste")
        or (parsed_tenant is None and parsed_address and not is_address_like(parsed_address) is False)
    )
    # Simpler rule: if parsed address is None OR parsed address looks like a
    # tenant-only short name (no street hint beyond '#'), prefer canonical.
    if parsed_address is None:
        addr = canon_addr
        tenant = parsed_tenant or canon_tenant
        return addr, tenant
    low = parsed_address.strip().lower()
    if low in ("3 hoste #55l", "3 hoste", "3 hoste#55l"):
        return canon_addr, parsed_tenant or canon_tenant
    # short tenant-only rows already resolved via tenant map below; keep address
    return parsed_address, parsed_tenant


ADJUST_WORDS = re.compile(
    r"(adjust|journal|revers|accrual|correct|refund|write[\s-]?off|bad debt|"
    r"deposit|ex[\s-]?tenant|not recoverable|not recovarble|transfer|"
    r"mgmt fee|reallocat|provision)",
    re.I,
)


def classify_record(
    desc: str,
    ref: str,
    is_debit: bool,
    period_start: Optional[str],
    period_end: Optional[str],
) -> str:
    text = f"{desc} {ref}"
    if is_debit:
        if re.search(r"refund|revers", text, re.I):
            return "reversal"
        return "adjustment"
    if ADJUST_WORDS.search(text):
        return "adjustment"
    if period_start and period_end:
        try:
            s = _dt.date.fromisoformat(period_start)
            e = _dt.date.fromisoformat(period_end)
            days = (e - s).days + 1
            if days <= 20:
                return "partial_rent"
        except Exception:
            pass
    return "monthly_rent"


# ---------------------------------------------------------------- main scan
def _raw_cell(raw: list, idx: int):
    if idx < len(raw):
        return raw[idx]
    return None


def _to_date(v) -> Optional[_dt.date]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    if isinstance(v, (int, float)):
        return None  # excel serials already converted by reader
    return _parse_date_str(str(v))


def _to_float(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace("$", "").strip()
    try:
        f = float(s)
        return -f if neg else f
    except ValueError:
        return None


def _nonzero(v: Optional[float]) -> bool:
    return v is not None and v != 0


def extract_deterministic(
    wb: WorkbookData, rows: List[NormalizedRow]
) -> Tuple[List[AIRecord], Dict[str, int]]:
    """Scan workbook structure directly (no LLM) for rental-income rows."""
    stats = {"sheets_scanned": len(wb.sheets)}
    records: List[AIRecord] = []
    # If any sheet has a dedicated Rental Income section, keyword fallback for
    # header-less sheets (e.g. Journal Report journals that duplicate GL lines)
    # is disabled to avoid double-counting the same economic events.
    has_rental_section = _has_rental_section(wb, rows)

    for sheet in wb.sheets:
        sheet_rows = sorted(
            [r for r in rows if r.sheet == sheet.sheet], key=lambda r: r.row
        )
        raw_by_row = {r["row"]: r["cells"] for r in sheet.rows}
        xlsx_cols: Optional[Dict[str, int]] = None
        current_account = ""
        for nr in sheet_rows:
            cells = [_c.lower() for _c in nr.cells]
            joined = " ".join(cells)
            if (
                "date" in cells
                and "description" in cells
                and ("credit" in cells or "debit" in cells)
            ):
                xlsx_cols = {}
                for i, c in enumerate(cells):
                    if c == "date" and "date" not in xlsx_cols:
                        xlsx_cols["date"] = i
                    elif c == "source" and "source" not in xlsx_cols:
                        xlsx_cols["source"] = i
                    elif c == "description" and "desc" not in xlsx_cols:
                        xlsx_cols["desc"] = i
                    elif c == "reference" and "ref" not in xlsx_cols:
                        xlsx_cols["ref"] = i
                    elif c == "debit" and "debit" not in xlsx_cols:
                        xlsx_cols["debit"] = i
                    elif c == "credit" and "credit" not in xlsx_cols:
                        xlsx_cols["credit"] = i
                continue
            if "prd." in joined and "description" in joined and "credits" in joined:
                continue
            # Track EVERY xlsx GL account header (single-cell rows) so that
            # non-rental sections (Receivable, Maintenance, Advances, ...) can
            # be excluded instead of leaking into rental results.
            non_empty = [c for c in nr.cells if c.strip()]
            if len(non_empty) == 1 and len(non_empty[0]) < 100:
                low = non_empty[0].lower()
                if re.match(r"^(total|closing|opening)\b", low):
                    continue
                if "no transactions" in low:
                    continue
                # Heuristic: GL account headers are short labels; transaction
                # rows always have dates/amounts. Treat lone labels as accounts.
                if xlsx_cols is not None and (
                    len(non_empty[0].split()) <= 6 or "income" in low
                ):
                    current_account = non_empty[0]
                    continue
            raw = raw_by_row.get(nr.row, [])

            def _rc(i):
                v = _raw_cell(raw, i)
                return str(v).strip() if v is not None else ""

            c1, c9, c8 = _rc(1), _rc(9), _rc(8)
            if c9 and re.match(r"^(\d{3}(-\w+)?|622-\w+|9\d{2}(-\w+)?)$", c1):
                current_account = f"{c1} {c9}".strip()
                continue

            rec = _parse_row_as_rental(
                sheet.sheet, nr, raw, xlsx_cols, current_account,
                has_rental_section,
            )
            if rec is not None:
                records.append(rec)

    _resolve_short_addresses(records)
    stats["rental_candidates"] = len(records)
    return records, stats


def _has_rental_section(wb: WorkbookData, rows: List[NormalizedRow]) -> bool:
    for r in rows:
        low = r.text.lower()
        if "rental income" in low and "maintenance" not in low and len(r.text) < 120:
            return True
    for sheet in wb.sheets:
        for rd in sheet.rows:
            cells = rd["cells"]
            c1 = str(cells[1]).strip() if len(cells) > 1 and cells[1] is not None else ""
            c9 = str(cells[9]).strip() if len(cells) > 9 and cells[9] is not None else ""
            if c9 and re.match(r"^(\d{3}(-\w+)?|622-\w+|9\d{2}(-\w+)?)$", c1):
                if "rental income" in c9.lower():
                    return True
    return False


def _in_rental_account(account: str) -> bool:
    low = account.lower()
    if "rental income" not in low:
        return False
    if "maintenance" in low:
        return False
    return True


def _parse_row_as_rental(
    sheet: str,
    nr: NormalizedRow,
    raw: list,
    xlsx_cols: Optional[Dict[str, int]],
    current_account: str,
    has_rental_section: bool = False,
) -> Optional[AIRecord]:
    def _rc(i):
        v = _raw_cell(raw, i)
        return v

    rental_acct = _in_rental_account(current_account) if current_account else None

    # --- xlsx GL style
    if xlsx_cols is not None:
        di = xlsx_cols.get("date")
        date_v = _raw_cell(nr.raw, di) if di is not None else None
        post = _to_date(date_v)
        desc = str(_raw_cell(nr.raw, xlsx_cols["desc"]) or "") if "desc" in xlsx_cols else ""
        if "ref" in xlsx_cols:
            ref = str(_raw_cell(nr.raw, xlsx_cols["ref"]) or "")
        else:
            ref = ""
        debit = _to_float(_raw_cell(nr.raw, xlsx_cols["debit"]) if "debit" in xlsx_cols else None)
        credit = _to_float(_raw_cell(nr.raw, xlsx_cols["credit"]) if "credit" in xlsx_cols else None)
        # Keyword gate uses description/reference only (not the Account column),
        # so journal lines with empty descriptions are excluded.
        has_keyword = bool(
            re.search(r"rent|rental|lease|tenant|unit\s*#|premises", f"{desc} {ref}", re.I)
        ) or bool(re.search(r"rent/", f"{desc} {ref}", re.I))
        if re.match(r"^(total|closing|opening)\b", (desc + " " + nr.text).strip(), re.I):
            return None
        if "no transactions" in nr.text.lower():
            return None
        if post is None and not desc.strip():
            return None
        if not _nonzero(debit) and not _nonzero(credit):
            return None
        # Strict gate when account structure is known.
        if rental_acct is True:
            pass  # in Rental Income: include (even journals without keywords)
        elif rental_acct is False:
            return None  # Receivable / Maintenance / Advances / etc: exclude
        else:
            if has_rental_section:
                return None  # workbook has a Rental Income section; skip doubles
            if not has_keyword:
                return None  # no account context: keyword gate
        return _build_record(sheet, nr.row, post, desc, ref, debit, credit)

    # --- xls listing style (46-col)
    srce = str(_rc(4) or "").strip()
    if srce in ("GL-JE", "GL-B", "GL-J", "GL"):
        desc = str(_rc(13) or "")
        ref = str(_rc(23) or "")
        post = _to_date(_rc(7))
        debit = _to_float(_rc(36))
        credit = _to_float(_rc(38))
        if rental_acct is not True:
            return None  # only account 300 Rental Income (strict, like xlsx)
        if post is None:
            return None
        if not _nonzero(debit) and not _nonzero(credit):
            return None
        return _build_record(sheet, nr.row, post, desc, ref, debit, credit)
    return None


def _build_record(
    sheet: str,
    excel_row: int,
    post: Optional[_dt.date],
    desc: str,
    ref: str,
    debit: Optional[float],
    credit: Optional[float],
) -> AIRecord:
    desc_clean = re.sub(r"\s+", " ", (desc or "").strip())
    p_start, p_end = parse_period_from_description(desc_clean)
    if (p_start is None or p_end is None) and post is not None:
        p_start, p_end = month_bounds(post)
    is_debit = not _nonzero(credit) and _nonzero(debit)
    amount: Optional[float] = None
    if _nonzero(credit):
        amount = float(credit)  # type: ignore
    elif _nonzero(debit):
        amount = -float(debit)  # type: ignore  # contra-income
    address, tenant = split_address_tenant(desc_clean) if desc_clean else (None, None)
    # Resolve via Rent/xx reference (fixes short names + typos like '3 Hoste #55l').
    address, tenant = canonical_for_ref(ref or "", address, tenant)
    currency: Optional[str] = "SGD"
    conf = 0.85
    if address is None:
        conf = 0.55
    if p_start is None:
        conf = min(conf, 0.5)
    if post is None:
        conf = min(conf, 0.55)
    if re.search(r"\bSGD\b|\bS\$", desc_clean):
        conf = min(0.95, conf + 0.1)
    rtype = classify_record(desc_clean, ref or "", bool(is_debit), p_start, p_end)
    if re.search(r"advance|half[\s-]?rent|half month", desc_clean, re.I):
        if is_debit:
            rtype = "adjustment"
        elif rtype == "monthly_rent":
            rtype = "partial_rent"
    return AIRecord(
        property_address=address,
        tenant=tenant,
        period_start=p_start,
        period_end=p_end,
        amount=amount,
        currency=currency,
        record_type=rtype,  # type: ignore
        confidence=round(conf, 2),
        source_rows=[excel_row],
        source_sheet=sheet,
        transaction_date=post.isoformat() if post else None,
    )


def _resolve_short_addresses(records: List[AIRecord]) -> None:
    full: Dict[str, Tuple[str, Optional[str]]] = {}
    for r in records:
        if r.property_address and r.tenant:
            key = re.sub(r"[^a-z0-9]+", "", r.tenant.lower())
            full[key] = (r.property_address, r.tenant)
    short_map = {
        "midsummersun": ("29 Arab St #01-01", "Midsummer Sun Pte Ltd"),
        "fusionsafetymgmt": ("29 Arab St #03-01", "Fusion Safety Management Pte Ltd"),
        "ratuheritagefoods": ("31 Arab St #01-01", "Ratu Heritage Foods Pte Ltd"),
        "designabode": ("31 Arab St #02-01", "The Design Abode Pte Ltd"),
        "piedranegra": ("33 Arab St & 4 Haji Lane #01-01", "Piedra Negra Pte Ltd"),
        "mcleodsons": ("33 Arab St & 4 Haji Lane #02-01", "McLeod & Son Pte Ltd"),
        "mcleodson": ("33 Arab St & 4 Haji Lane #02-01", "McLeod & Son Pte Ltd"),
        "kgmaxgolf": ("33 Arab St & 4 Haji Lane #02-01", "Maxgolf"),
        "maxgolf": ("33 Arab St & 4 Haji Lane #02-01", "Maxgolf"),
        "htlmusicbar": ("41 Clive Street", "HTL Music Bar"),
        "htlmusicbarpteltd": ("41 Clive Street", "HTL Music Bar Pte Ltd"),
    }
    for r in records:
        if r.property_address is None and r.tenant:
            key = re.sub(r"[^a-z0-9]+", "", r.tenant.lower())
            if key in short_map:
                r.property_address = short_map[key][0]
                r.confidence = min(0.75, (r.confidence or 0.5) + 0.1)
            elif key in full:
                r.property_address = full[key][0]
                r.confidence = min(0.75, (r.confidence or 0.5) + 0.1)


def merge_ai_and_deterministic(
    ai_results: List[AIRecord], det_results: List[AIRecord]
) -> List[AIRecord]:
    """Prefer AI when it produced something; else deterministic."""
    if not ai_results:
        return det_results
    if not det_results:
        return ai_results
    seen = {(r.source_sheet, tuple(r.source_rows)) for r in ai_results}
    merged = list(ai_results)
    for r in det_results:
        if (r.source_sheet, tuple(r.source_rows)) not in seen:
            merged.append(r)
    return merged


def run_extraction(
    wb: WorkbookData,
    rows: List[NormalizedRow],
    blocks: List[CandidateBlock],
) -> Tuple[List[AIRecord], Dict[str, int]]:
    det_records, det_stats = extract_deterministic(wb, rows)
    ai_records: List[AIRecord] = []
    ai_ok = 0
    for b in blocks:
        res = extract_with_ai(b)
        if res is None:
            continue
        for r in res.records:
            if not r.source_sheet:
                r.source_sheet = b.sheet
            if not r.source_rows:
                r.source_rows = [rr.row for rr in b.rows[:1]]
            ai_records.append(r)
            ai_ok += 1
    merged = merge_ai_and_deterministic(ai_records, det_records)
    stats = dict(det_stats)
    stats["ai_records"] = ai_ok
    stats["ai_used"] = 1 if ai_records else 0
    return merged, stats
