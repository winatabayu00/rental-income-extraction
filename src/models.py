"""Pydantic schemas for AI output and final results."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

RecordType = Literal["monthly_rent", "partial_rent", "adjustment", "reversal", "unknown"]


class AIRecord(BaseModel):
    property_address: Optional[str] = None
    tenant: Optional[str] = None
    period_start: Optional[str] = None  # YYYY-MM-DD
    period_end: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    record_type: RecordType = "unknown"
    confidence: float = 0.5
    source_rows: List[int] = Field(default_factory=list)
    source_sheet: Optional[str] = None
    transaction_date: Optional[str] = None


class AIExtractionResult(BaseModel):
    records: List[AIRecord] = Field(default_factory=list)


class SourceRef(BaseModel):
    sheet: str
    rows: List[int]


class MonthlyRecord(BaseModel):
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    record_type: str = "monthly_rent"
    tenant: Optional[str] = None
    confidence: Optional[float] = None
    source: SourceRef


class MissingPeriod(BaseModel):
    expected_start: str
    expected_end: str


class Issue(BaseModel):
    type: str
    severity: str = "warning"
    message: str
    context: Dict[str, Any] = Field(default_factory=dict)


# ---- Explicit domain models (strongly typed pipeline I/O) ----
# Aliases kept for backward compatibility with existing imports.

SourceReference = SourceRef
RentalRecord = MonthlyRecord
ValidationIssue = Issue


class RentalPeriod(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class PropertyResult(BaseModel):
    property_address: Optional[str] = None
    tenant: Optional[str] = None
    currency: Optional[str] = None
    rental_period: RentalPeriod = Field(default_factory=RentalPeriod)
    standard_monthly_rental: Optional[float] = None
    monthly_records: List[MonthlyRecord] = Field(default_factory=list)
    missing_periods: List[MissingPeriod] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)


class CompanyResult(BaseModel):
    source_file: str
    company: str
    properties: List[PropertyResult] = Field(default_factory=list)


class ProcessingSummary(BaseModel):
    files_processed: int = 0
    files_failed: int = 0
    failed_files: List[str] = Field(default_factory=list)
    ai_enabled: bool = False


class ExtractionResult(BaseModel):
    processing_summary: ProcessingSummary = Field(default_factory=ProcessingSummary)
    companies: List[CompanyResult] = Field(default_factory=list)
