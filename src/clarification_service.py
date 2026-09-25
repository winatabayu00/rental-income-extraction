"""Turn machine-readable issues into client-facing clarification questions."""
from __future__ import annotations

from typing import List

from .models import Issue


def questions_for_property(
    property_address: str | None, issues: List[Issue]
) -> List[str]:
    out: List[str] = []
    label = property_address or "the property"
    for iss in issues:
        t = iss.type
        ctx = iss.context
        if t == "MISSING_PROPERTY_ADDRESS":
            start = ctx.get("period_start") or "the recorded period"
            end = ctx.get("period_end") or ""
            period = f"{start} to {end}" if end else str(start)
            out.append(
                f"A rental transaction was identified for the period {period} "
                f"(sheet {ctx.get('sheet')}, row(s) {ctx.get('rows')}), but no "
                f"property address could be identified. Please confirm the "
                f"property address for this rental."
            )
        elif t == "MISSING_PERIOD":
            out.append(
                f"A rental entry (sheet {ctx.get('sheet')}, row(s) {ctx.get('rows')}) "
                f"is missing a clear rental period. Please confirm the rental "
                f"period this entry relates to."
            )
        elif t == "INVALID_PERIOD":
            out.append(
                f"The recorded period {ctx.get('period_start')} to "
                f"{ctx.get('period_end')} appears invalid (start is after end). "
                f"Please confirm the correct rental period."
            )
        elif t == "MISSING_RENTAL_PERIOD":
            if ctx.get("coverage"):
                out.append(
                    f"Rental records for {label} end before the file's latest "
                    f"period, and no rental entry was identified for "
                    f"{ctx.get('expected_start')} to {ctx.get('expected_end')}. "
                    f"Please confirm whether the lease ended or whether rental "
                    f"records are missing."
                )
            else:
                out.append(
                    f"Rental records for {label} were found before and after "
                    f"{ctx.get('expected_start')} to {ctx.get('expected_end')}, but no "
                    f"rental entry was identified for that period. Please confirm "
                    f"whether the rental record is missing or whether no rent was due."
                )
        elif t == "DUPLICATE_PERIOD":
            out.append(
                f"Multiple rental transactions were identified for {label} for "
                f"{ctx.get('period_start')} to {ctx.get('period_end')}. Please "
                f"confirm whether these represent separate rental charges or a "
                f"duplicated record."
            )
        elif t == "OVERLAPPING_PERIOD":
            first = ctx.get("first", {})
            second = ctx.get("second", {})
            out.append(
                f"Overlapping rental periods were found for {label}: "
                f"{first.get('start')} to {first.get('end')} overlaps with "
                f"{second.get('start')} to {second.get('end')}. Please confirm "
                f"the correct rental periods."
            )
        elif t == "AMOUNT_INCONSISTENCY":
            out.append(
                f"The recurring rental amount for {label} is "
                f"{ctx.get('expected_amount'):g}, but the rental for "
                f"{ctx.get('period_start')} to {ctx.get('period_end')} is recorded "
                f"as {ctx.get('actual_amount'):g}. Please confirm whether this "
                f"amount change is correct."
            )
        elif t == "PARTIAL_RENTAL":
            out.append(
                f"A partial rental charge was found for {label} for "
                f"{ctx.get('period_start')} to {ctx.get('period_end')} "
                f"(amount {ctx.get('amount')}). Please confirm whether this period "
                f"should be included as part of the lease period."
            )
        elif t == "CURRENCY_INCONSISTENCY":
            out.append(
                f"Rental records for {label} reference multiple currencies "
                f"({', '.join(map(str, ctx.get('currencies', [])))}). Please confirm "
                f"the correct billing currency."
            )
        elif t == "AMBIGUOUS_RECORD":
            if "tenants" in ctx:
                out.append(
                    f"Rental records for {label} reference multiple tenants "
                    f"({', '.join(ctx['tenants'])}). Please confirm the correct "
                    f"tenant for each period."
                )
            else:
                out.append(
                    f"An ambiguous rental record was found for {label}: "
                    f"{iss.message} Please confirm how it should be treated."
                )
    # de-duplicate while preserving order
    seen: set[str] = set()
    uniq: List[str] = []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq
