"""Find rental-related candidate blocks before calling the AI.

Sending whole ledgers to an LLM wastes tokens and increases hallucination
risk. This module isolates likely rental sections using case-insensitive
keyword matching, then groups nearby rows into blocks with context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from .normalizer import NormalizedRow

KEYWORDS = [
    "rent",
    "rental",
    "rental income",
    "lease",
    "monthly rental",
    "property",
    "unit",
    "premises",
    "tenant",
    "tenancy",
    "deposit received",
    "advances received",
]

# strong signals that almost certainly indicate a rental transaction row
STRONG_PATTERNS = [
    re.compile(r"\brent\b", re.I),
    re.compile(r"\brental\b", re.I),
    re.compile(r"\blease\b", re.I),
    re.compile(r"\btenant\b", re.I),
    re.compile(r"rent/", re.I),
    re.compile(r"#\d", re.I),  # unit numbers like #09-03A, #01-01
    re.compile(r"\bmcst\b", re.I),
]

ACCOUNT_HEADER_RE = re.compile(
    r"(rental income|rent\s*dep|tenant\s*acc|advances received|deposits received|"
    r"amount due|share capital|property loan)", re.I
)


@dataclass
class CandidateBlock:
    sheet: str
    start_row: int
    end_row: int
    rows: List[NormalizedRow] = field(default_factory=list)
    account: str = ""
    reason: str = ""


def _row_score(row: NormalizedRow) -> int:
    text = row.text.lower()
    score = 0
    for kw in KEYWORDS:
        if kw in text:
            score += 2 if kw in ("rent", "rental", "lease", "tenant") else 1
    for pat in STRONG_PATTERNS:
        if pat.search(row.text):
            score += 1
    return score


def _account_for_row(all_rows: List[NormalizedRow], idx: int) -> str:
    """Walk backwards to find the nearest account header row."""
    for j in range(idx, max(-1, idx - 15), -1):
        t = all_rows[j].text
        # account headers are short rows like 'Rental Income' or '622 Rent Deposit...'
        if ACCOUNT_HEADER_RE.search(t) and len(t) < 120:
            return t.split("|")[0].strip()[:100]
    return ""


def find_candidates(
    rows: List[NormalizedRow], context: int = 2, merge_gap: int = 6
) -> List[CandidateBlock]:
    # group rows by sheet to preserve sheet-local ordering
    by_sheet: dict[str, List[NormalizedRow]] = {}
    for r in rows:
        by_sheet.setdefault(r.sheet, []).append(r)
    blocks: List[CandidateBlock] = []
    for sheet, srows in by_sheet.items():
        srows = sorted(srows, key=lambda r: r.row)
        hits = [(i, r) for i, r in enumerate(srows) if _row_score(r) > 0]
        if not hits:
            continue
        # expand each hit with context, then merge overlapping windows
        windows: List[List[int]] = []
        for i, r in hits:
            lo = max(0, i - context)
            hi = min(len(srows) - 1, i + context)
            windows.append([lo, hi])
        windows.sort()
        merged: List[List[int]] = []
        for lo, hi in windows:
            if merged and lo <= merged[-1][1] + merge_gap:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        for lo, hi in merged:
            chunk = srows[lo : hi + 1]
            acct = _account_for_row(srows, lo)
            # reason: matched keywords in the core rows
            core = [r for i, r in hits if lo <= i <= hi]
            reason = "; ".join(sorted({c.text[:80] for c in core})[:3])
            blocks.append(
                CandidateBlock(
                    sheet=sheet,
                    start_row=chunk[0].row,
                    end_row=chunk[-1].row,
                    rows=chunk,
                    account=acct,
                    reason=reason,
                )
            )
    return blocks
