"""Deterministic validation: gaps, duplicates, overlaps, amount checks.

The AI never does date math. All continuity and consistency logic lives here
so results are predictable and auditable.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from collections import Counter
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta

from .models import AIRecord, Issue, MissingPeriod
from .normalizer import normalize_address


def _parse(d: Optional[str]) -> Optional[_dt.date]:
    if not d:
        return None
    try:
        return _dt.date.fromisoformat(d)
    except Exception:
        return None


def _add_month(d: _dt.date) -> _dt.date:
    return d + relativedelta(months=1)


def detect_missing_periods(
    periods: List[Tuple[_dt.date, _dt.date]],
) -> List[MissingPeriod]:
    """Compare rental periods, not calendar month numbers.

    Handles both calendar-month cadence (1 Jan->31 Jan) and mid-month
    cadence (16 Jan->15 Feb). A next period starting the day after the
    previous end is continuous; anything later is a gap.
    """
    if len(periods) < 2:
        return []
    missing: List[MissingPeriod] = []
    for prev_s, prev_e in sorted(periods):
        pass
    ordered = sorted(periods, key=lambda p: (p[0], p[1]))
    for i in range(len(ordered) - 1):
        prev_s, prev_e = ordered[i]
        cur_s, cur_e = ordered[i + 1]
        if cur_s <= prev_e:
            continue  # overlap/duplicate handled elsewhere
        expected_start = prev_e + _dt.timedelta(days=1)
        if cur_s == expected_start:
            continue
        # walk the gap in monthly steps
        cursor = expected_start
        guard = 0
        while cursor < cur_s and guard < 24:
            # expected end: one rental-month after cursor, capped at day before cur start
            step_end = (_add_month(cursor) - _dt.timedelta(days=1))
            cap = cur_s - _dt.timedelta(days=1)
            if step_end > cap:
                step_end = cap
            missing.append(
                MissingPeriod(
                    expected_start=cursor.isoformat(), expected_end=step_end.isoformat()
                )
            )
            cursor = step_end + _dt.timedelta(days=1)
            guard += 1
    return missing


def _mode_amount(amounts: List[float], tol: float = 0.01) -> Optional[float]:
    if not amounts:
        return None
    # cluster within relative tolerance
    best: Optional[float] = None
    best_count = 0
    for cand in amounts:
        cnt = sum(1 for a in amounts if abs(a - cand) <= abs(cand) * tol + 1e-9)
        if cnt > best_count:
            best_count = cnt
            best = cand
    if best is not None and best_count >= max(2, len(amounts) // 2 + 1):
        return best
    if len(set(round(a, 2) for a in amounts)) == 1:
        return amounts[0]
    return None


def validate_property(
    display_address: Optional[str],
    records: List[AIRecord],
    file: str,
) -> Tuple[dict, List[Issue], List[dict]]:
    """Validate one property group. Returns (summary_extra, issues, clarifications handled elsewhere)."""
    issues: List[Issue] = []
    # sort by period start
    dated = [r for r in records if _parse(r.period_start) and _parse(r.period_end)]
    undated = [r for r in records if not (_parse(r.period_start) and _parse(r.period_end))]

    for r in records:
        if not r.property_address:
            issues.append(
                Issue(
                    type="MISSING_PROPERTY_ADDRESS",
                    severity="warning",
                    message=(
                        f"No property address could be identified for a rental transaction"
                        + (
                            f" dated {r.transaction_date or r.period_start}"
                            if (r.transaction_date or r.period_start)
                            else ""
                        )
                        + f" (sheet {r.source_sheet}, row(s) {r.source_rows})."
                    ),
                    context={
                        "sheet": r.source_sheet,
                        "rows": r.source_rows,
                        "period_start": r.period_start,
                        "period_end": r.period_end,
                    },
                )
            )
    for r in undated:
        issues.append(
            Issue(
                type="MISSING_PERIOD",
                severity="warning",
                message=(
                    f"Rental period could not be established for a record "
                    f"(sheet {r.source_sheet}, row(s) {r.source_rows})."
                ),
                context={"sheet": r.source_sheet, "rows": r.source_rows},
            )
        )
    for r in dated:
        s, e = _parse(r.period_start), _parse(r.period_end)
        assert s and e
        if s > e:
            issues.append(
                Issue(
                    type="INVALID_PERIOD",
                    severity="error",
                    message=f"Invalid period {s} to {e}: start is after end.",
                    context={
                        "period_start": s.isoformat(),
                        "period_end": e.isoformat(),
                        "rows": r.source_rows,
                    },
                )
            )

    # Only monthly/partial define cadence & period
    cadence_recs = [
        r for r in dated if r.record_type in ("monthly_rent", "partial_rent")
    ]
    cadence_recs.sort(key=lambda r: (_parse(r.period_start), _parse(r.period_end)))  # type: ignore

    # rental overall period
    rental_start = rental_end = None
    if cadence_recs:
        starts = [_parse(r.period_start) for r in cadence_recs if _parse(r.period_start)]
        ends = [_parse(r.period_end) for r in cadence_recs if _parse(r.period_end)]
        if starts and ends:
            rental_start = min(starts)
            rental_end = max(ends)

    # duplicates & overlaps (monthly only to avoid adjustment noise, but check partial too)
    seen: Dict[Tuple[str, str], List[AIRecord]] = {}
    for r in cadence_recs:
        key = (r.period_start or "", r.period_end or "")
        seen.setdefault(key, []).append(r)
    for (s, e), group in seen.items():
        if len(group) > 1:
            issues.append(
                Issue(
                    type="DUPLICATE_PERIOD",
                    severity="warning",
                    message=f"Multiple rental transactions were identified for {s} to {e}.",
                    context={
                        "period_start": s,
                        "period_end": e,
                        "rows": [x.source_rows for x in group],
                    },
                )
            )
    for i in range(len(cadence_recs) - 1):
        a, b = cadence_recs[i], cadence_recs[i + 1]
        sa, ea = _parse(a.period_start), _parse(a.period_end)
        sb, eb = _parse(b.period_start), _parse(b.period_end)
        if sa is None or ea is None or sb is None or eb is None:
            continue
        if (sa, ea) == (sb, eb):
            continue  # already reported as duplicate
        if sb <= ea:
            # allow adjustment/partial to overlap quietly? spec: flag unless adjustment/partial
            if a.record_type in ("adjustment", "reversal") or b.record_type in (
                "adjustment",
                "reversal",
            ):
                continue
            issues.append(
                Issue(
                    type="OVERLAPPING_PERIOD",
                    severity="warning",
                    message=(
                        f"Overlapping rental periods: {sa} to {ea} overlaps "
                        f"with {sb} to {eb}."
                    ),
                    context={
                        "first": {"start": sa.isoformat(), "end": ea.isoformat()},
                        "second": {"start": sb.isoformat(), "end": eb.isoformat()},
                    },
                )
            )

    # gaps
    missing: List[MissingPeriod] = []
    if len(cadence_recs) >= 2:
        periods = [
            (_parse(r.period_start), _parse(r.period_end))  # type: ignore
            for r in cadence_recs
        ]
        periods = [(s, e) for s, e in periods if s and e]  # type: ignore
        missing = detect_missing_periods(periods)  # type: ignore
        for m in missing:
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
                    },
                )
            )

    # amount consistency (monthly only, signed amounts -> use abs for income)
    monthly_amounts = [
        abs(r.amount)
        for r in cadence_recs
        if r.record_type == "monthly_rent" and r.amount
    ]
    standard = _mode_amount(monthly_amounts) if monthly_amounts else None
    if standard is not None and monthly_amounts:
        for r in cadence_recs:
            if r.record_type != "monthly_rent" or not r.amount:
                continue
            if abs(abs(r.amount) - standard) > abs(standard) * 0.01 + 0.005:
                issues.append(
                    Issue(
                        type="AMOUNT_INCONSISTENCY",
                        severity="warning",
                        message=(
                            f"Recurring rental is {standard:g} but {r.period_start} "
                            f"to {r.period_end} is recorded as {abs(r.amount):g}."
                        ),
                        context={
                            "period_start": r.period_start,
                            "period_end": r.period_end,
                            "expected_amount": standard,
                            "actual_amount": abs(r.amount),
                            "rows": r.source_rows,
                        },
                    )
                )
                break  # one representative issue; clarification engine expands per period

    # partial rentals
    for r in records:
        if r.record_type == "partial_rent":
            issues.append(
                Issue(
                    type="PARTIAL_RENTAL",
                    severity="info",
                    message=(
                        f"A partial rental charge was found for {r.period_start} "
                        f"to {r.period_end} (amount {r.amount})."
                    ),
                    context={
                        "period_start": r.period_start,
                        "period_end": r.period_end,
                        "amount": r.amount,
                        "rows": r.source_rows,
                    },
                )
            )

    # currency consistency
    currencies = {r.currency for r in records if r.currency}
    if len(currencies) > 1:
        issues.append(
            Issue(
                type="CURRENCY_INCONSISTENCY",
                severity="warning",
                message=f"Multiple currencies observed: {sorted(currencies)}.",
                context={"currencies": sorted(currencies)},
            )
        )

    # properties with no monthly/partial records (only adjustments): flag for review
    if not cadence_recs:
        has_adjust = any(
            r.record_type in ("adjustment", "reversal", "unknown") for r in records
        )
        if has_adjust and dated:
            issues.append(
                Issue(
                    type="AMBIGUOUS_RECORD",
                    severity="warning",
                    message=(
                        f"Only adjustment-type entries were found for "
                        f"{display_address or 'this property'}; no monthly rental "
                        f"records could be established. Please confirm how these "
                        f"entries should be treated."
                    ),
                    context={"record_count": len(records)},
                )
            )
    # tenant change within same property (reported as AMBIGUOUS_RECORD
    # to stay within the recommended taxonomy, with tenant details in context)
    tenants = [r.tenant for r in cadence_recs if r.tenant]
    uniq_tenants = []
    for t in tenants:
        if t not in uniq_tenants:
            uniq_tenants.append(t)
    if len(uniq_tenants) > 1:
        # short-name variants of the same tenant (e.g. 'Midsummer Sun' vs
        # 'Midsummer Sun Pte Ltd') are not a real change.
        normed = {re_sub_tenant(t) for t in uniq_tenants}
        if len(normed) > 1:
            issues.append(
                Issue(
                    type="AMBIGUOUS_RECORD",
                    severity="warning",
                    message=(
                        f"Tenant appears to change for {display_address or 'this property'}: "
                        f"{' / '.join(uniq_tenants)}. Please confirm the correct tenant."
                    ),
                    context={"tenants": uniq_tenants},
                )
            )

    extra = {
        "rental_start": rental_start.isoformat() if rental_start else None,
        "rental_end": rental_end.isoformat() if rental_end else None,
        "standard": standard,
        "missing": missing,
    }
    return extra, issues, []


def re_sub_tenant(t: str) -> str:
    import re as _re

    s = t.lower()
    s = _re.sub(r"\b(pte|sdn|bhd|ltd)\b\.?", "", s)
    s = _re.sub(r"\bmgmt\b\.?", "management", s)
    s = _re.sub(r"\bsons\b", "son", s)
    s = _re.sub(r"\bthe\b", "", s)
    s = _re.sub(r"^kg\b", "", s)
    s = _re.sub(r"[^a-z0-9]+", "", s)
    return s


def group_by_property(records: List[AIRecord]) -> Dict[str, List[AIRecord]]:
    groups: Dict[str, List[AIRecord]] = {}
    for r in records:
        key = normalize_address(r.property_address) if r.property_address else "__unknown__"
        groups.setdefault(key, []).append(r)
    return groups


def detect_coverage_gaps(
    groups: Dict[str, List[AIRecord]],
) -> Dict[str, List[MissingPeriod]]:
    """Flag properties whose coverage ends early / starts late vs the file.

    Internal gaps are handled by detect_missing_periods; this surfaces leases
    that disappear (e.g. a unit with records only up to Nov while the file
    runs to Mar) so reviewers get a clarification instead of silence.
    Only applies when a file has 2+ properties with clear monthly cadence.
    """
    cadence_bounds: Dict[str, Tuple[_dt.date, _dt.date]] = {}
    for key, recs in groups.items():
        if key == "__unknown__":
            continue
        cad = [
            r
            for r in recs
            if r.record_type in ("monthly_rent", "partial_rent")
            and _parse(r.period_start)
            and _parse(r.period_end)
        ]
        if len(cad) < 2:
            continue
        starts = [_parse(r.period_start) for r in cad]  # type: ignore
        ends = [_parse(r.period_end) for r in cad]  # type: ignore
        cadence_bounds[key] = (min(s for s in starts if s), max(e for e in ends if e))  # type: ignore
    if len(cadence_bounds) < 2:
        return {}
    global_start = min(s for s, _ in cadence_bounds.values())
    global_end = max(e for _, e in cadence_bounds.values())
    out: Dict[str, List[MissingPeriod]] = {}
    for key, (s, e) in cadence_bounds.items():
        gaps: List[MissingPeriod] = []
        # tail: property ends > ~40 days before file end
        if (global_end - e).days >= 40:
            cursor = e + _dt.timedelta(days=1)
            guard = 0
            while cursor <= global_end and guard < 12:
                step_end = _add_month(cursor) - _dt.timedelta(days=1)
                if step_end > global_end:
                    step_end = global_end
                gaps.append(
                    MissingPeriod(
                        expected_start=cursor.isoformat(),
                        expected_end=step_end.isoformat(),
                    )
                )
                cursor = step_end + _dt.timedelta(days=1)
                guard += 1
        # head: property starts > ~40 days after file start
        if (s - global_start).days >= 40:
            cursor = global_start
            guard = 0
            cap = s - _dt.timedelta(days=1)
            while cursor <= cap and guard < 12:
                step_end = _add_month(cursor) - _dt.timedelta(days=1)
                if step_end > cap:
                    step_end = cap
                gaps.append(
                    MissingPeriod(
                        expected_start=cursor.isoformat(),
                        expected_end=step_end.isoformat(),
                    )
                )
                cursor = step_end + _dt.timedelta(days=1)
                guard += 1
        if gaps:
            # sort chronologically
            gaps.sort(key=lambda m: m.expected_start)
            out[key] = gaps
    return out
