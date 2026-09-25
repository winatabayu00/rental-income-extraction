"""OpenAI-compatible structured extraction client.

Design: AI for interpretation, deterministic code for validation.
The AI only converts free-form ledger text into the JSON schema; all
date math, gap detection and amount checks happen in Python.

When no API key is configured (or the call fails after retries), the
caller falls back to the deterministic rule-based extractor so the
tool remains usable offline and the acceptance files still process.
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import config
from .candidate_detector import CandidateBlock
from .models import AIExtractionResult

SYSTEM_PROMPT = """You are extracting rental-income information from accounting
and general-ledger records.

Only return information that is directly supported by the
provided records.

Do not guess missing property addresses, dates, rental amounts,
currencies, or tenant names.

A transaction posting date must not automatically be interpreted
as the rental period.

Distinguish normal monthly rental transactions from adjustments,
reversals, deposits, journal entries, and partial-month charges.

When a value is uncertain, return null.

Return only valid structured JSON matching the requested schema."""

SCHEMA_HINT = """Return JSON with this exact shape:
{"records": [{"property_address": str|null, "tenant": str|null,
"period_start": "YYYY-MM-DD"|null, "period_end": "YYYY-MM-DD"|null,
"amount": number|null, "currency": str|null,
"record_type": "monthly_rent|partial_rent|adjustment|reversal|unknown",
"confidence": number, "source_rows": [int]}]}"""


def block_to_text(block: CandidateBlock) -> str:
    lines = [
        f"Sheet: {block.sheet} | Account context: {block.account or 'n/a'}",
        "Rows (row_number | cells):",
    ]
    for r in block.rows:
        lines.append(f"{r.row} | {r.text}")
    return "\n".join(lines)


def extract_with_ai(block: CandidateBlock) -> Optional[AIExtractionResult]:
    """Return parsed records, or None when AI is unavailable/failing."""
    if not config.ai_enabled():
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_BASE_URL)
    user_msg = (
        SCHEMA_HINT
        + "\n\nLedger candidate block:\n"
        + block_to_text(block)
        + "\n\nRules: only extract supported info; null when uncertain; "
        + "keep source_rows as the Excel row numbers shown; "
        + "dates YYYY-MM-DD; amounts numeric with currency separate."
    )
    last_err: Optional[Exception] = None
    for _ in range(config.MAX_AI_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=config.AI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=60,
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            return AIExtractionResult.model_validate(data)
        except Exception as e:  # timeout, rate limit, bad JSON, schema mismatch
            last_err = e
            continue
    # exhausted retries -> signal failure without fabricating output
    _ = last_err
    return None


def extract_many(blocks: List[CandidateBlock]) -> List[AIExtractionResult]:
    out: List[AIExtractionResult] = []
    for b in blocks:
        res = extract_with_ai(b)
        if res is not None:
            out.append(res)
    return out
