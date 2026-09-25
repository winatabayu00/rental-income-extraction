"""Normalize raw workbook rows into a common textual representation."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .excel_reader import WorkbookData

_AMOUNT_RE = re.compile(r"^-?\(?\$?S?\$?\s*[\d,]*\.?\d+\)?$")


@dataclass
class NormalizedRow:
    sheet: str
    row: int
    cells: List[str]
    text: str
    raw: List[Any] = field(default_factory=list)


def _cell_to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (_dt.datetime, _dt.date)):
        # keep date-like values in ISO form for downstream parsing
        if isinstance(v, _dt.datetime):
            if v.hour == 0 and v.minute == 0 and v.second == 0:
                return v.date().isoformat()
            return v.isoformat(sep=" ")
        return v.isoformat()
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    # collapse internal whitespace/newlines
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_workbook(wb: WorkbookData) -> List[NormalizedRow]:
    out: List[NormalizedRow] = []
    for sheet in wb.sheets:
        for r in sheet.rows:
            raw_cells: List[Any] = r["cells"]
            cells = [_cell_to_str(v) for v in raw_cells]
            # drop rows that are entirely empty after normalization
            if not any(c.strip() for c in cells):
                continue
            text = " | ".join(c for c in cells if c.strip())
            out.append(
                NormalizedRow(
                    sheet=sheet.sheet, row=r["row"], cells=cells, text=text, raw=raw_cells
                )
            )
    return out


def try_parse_amount(value: Any) -> Optional[float]:
    """Parse SG-style amounts like '37,325.50', '(500)', '$15,000'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace("S", "").replace(",", "").strip()
    s = s.replace(" ", "")
    try:
        num = float(s)
        return -num if neg else num
    except ValueError:
        return None


def parse_amount_from_cells(cells: List[str]) -> Optional[float]:
    for c in reversed(cells):  # amounts usually at the right
        amt = try_parse_amount(c)
        # avoid treating years / small integers as amounts when ambiguous?
        # only accept if the cell looks numeric
        if amt is not None and re.match(r"^\(?-?[\d,.$\sS]+\)?$", c.strip()) and any(
            ch.isdigit() for ch in c
        ):
            # reject pure years like '2024' or period codes '09'
            stripped = c.strip().replace(",", "")
            if re.fullmatch(r"(19|20)\d{2}", stripped):
                continue
            return amt
    return None


def normalize_address(addr: Optional[str]) -> str:
    if not addr:
        return ""
    s = re.sub(r"\s+", " ", addr.strip()).lower()
    return s
