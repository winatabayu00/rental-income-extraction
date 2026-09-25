# Rental Income AI Extractor

AI-assisted rental-income extraction from messy Excel general ledgers.
Supports `.xlsx` (openpyxl) and legacy `.xls` (xlrd) workbooks with
different worksheet layouts.

## Architecture

```text
Excel
→ normalization
→ candidate detection
→ AI extraction
→ deterministic validation
→ clarification generation
→ CLI / GUI
```

1. **Workbook Reader** (`src/excel_reader.py`) — scans *all* worksheets of
   `.xlsx`/`.xls` files, preserving file/sheet/row traceability.
2. **Row Normalization** (`src/normalizer.py`) — removes empty rows,
   normalizes dates/numbers, keeps source locations.
3. **Rental Candidate Finder** (`src/candidate_detector.py`) — case-insensitive
   keyword detection (`rent`, `rental`, `lease`, `tenant`, …) grouped into
   contextual blocks so the LLM sees headers + surrounding rows, not the
   whole ledger.
4. **AI Extraction** (`src/ai_extractor.py`) — OpenAI-compatible structured
   extraction (free text → JSON schema). Retried `MAX_AI_RETRIES` times;
   on failure the run continues with deterministic results and never
   fabricates data.
5. **Deterministic fallback** (`src/extraction_service.py`) — rule-based
   parser for the supplied ledger styles (explicit `From … to …` periods,
   `Address - Tenant` descriptions, `Rent/xx` references, post-date months).
   Used when no API key is set and merged with AI output otherwise.
6. **Validation Engine** (`src/rental_validator.py`) — grouping by normalized
   address, rental-period bounds, missing/duplicate/overlap detection,
   amount-consistency and partial-rent checks. Pure Python, no LLM.
7. **Clarifications** (`src/clarification_service.py`) — specific,
   actionable, non-technical questions instead of guessed values.
8. **Output** (`output/results.json` + console summary).

## Why Hybrid AI + Rules

> The AI model is used for interpreting semi-structured accounting descriptions,
> while deterministic Python validation handles dates, missing periods,
> duplicate detection, and consistency checks.

> The AI model is responsible for interpreting semi-structured accounting descriptions. Deterministic Python logic handles financial validation such as missing periods, duplicate records, overlapping periods, date continuity, and rental amount consistency.

This separation reduces hallucination risk: the LLM never performs financial
math or invents missing values (it returns `null` when uncertain), while all
date continuity, gap, duplicate, overlap, and amount comparisons are plain
reproducible Python that can be unit-tested and audited against source rows.

AI is good at inconsistent human-written descriptions (address semantics,
period wording, adjustment vs rent). Financial validation must be predictable
and reproducible, so gaps, overlaps, duplicates and amount comparisons are
plain date/number logic that can be unit-tested and audited.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Set AI credentials (optional — the tool runs offline without them using the
deterministic extractor):

```env
AI_API_KEY=sk-...
AI_BASE_URL=          # optional, for OpenAI-compatible providers
AI_MODEL=gpt-4o-mini
INPUT_DIR=./input
OUTPUT_DIR=./output
```

No API key is committed to Git (see `.gitignore`).

## Running

CLI:

```bash
python main.py ./input
# output dir defaults to ./output; override: python main.py ./input ./output
```

GUI:

```bash
streamlit run app.py
```

Upload `.xls`/`.xlsx` files, click **Process Files**, review summary cards,
company → property expanders, monthly-record tables, issues, clarification
questions, raw JSON, and **Download JSON** (`rental-income-results.json` —
identical structure to the CLI `output/results.json`).

Tests:

```bash
python -m unittest discover -s tests -v
```

## Output

- `output/results.json` — machine-readable results:

```json
{
  "processing_summary": {"files_processed": 3, "files_failed": 0},
  "companies": [
    {
      "source_file": "example.xlsx",
      "company": "Example Pte Ltd",
      "properties": [
        {
          "property_address": "Example Property",
          "tenant": "Example Tenant",
          "currency": "SGD",
          "rental_period": {"start": "2024-01-01", "end": "2024-12-31"},
          "standard_monthly_rental": 10000,
          "monthly_records": [
            {
              "period_start": "2024-01-01",
              "period_end": "2024-01-31",
              "amount": 10000,
              "record_type": "monthly_rent",
              "source": {"sheet": "General Ledger", "rows": [51]}
            }
          ],
          "missing_periods": [],
          "issues": [],
          "clarification_questions": []
        }
      ]
    }
  ]
}
```

- Console summary per file (sheets scanned, candidates, properties,
  missing periods, clarifications).

## Rental logic notes

- Only the **Rental Income** account defines monthly records; tenant-AR,
  deposits, GST and other accounts are ignored for cadence (but deposit/
  tenant headers enrich addresses).
- Rental periods come from explicit description dates when present
  (e.g. `From 16 January 2024 to 15 February 2024`), otherwise the posting
  month (1st → month-end).
- Mid-month cadences (`16th → 15th`) are compared as **period continuity**
  (`next.start == prev.end + 1 day`), not calendar-month numbers.
- `standard_monthly_rental` is the mode amount (1% tolerance) when a clear
  majority exists, else `null`.
- Debits inside Rental Income are stored as negative (contra-income)
  adjustments/reversals and excluded from gap/amount cadence.
- Short tenant-only descriptions (e.g. `Midsummer Sun`, `HTL Music Bar`)
  are resolved via `Rent/xx` reference knowledge; unresolvable ones keep
  `property_address: null` and raise a clarification instead of a guess.

## Limitations

- Currency defaults to `SGD` for these Singapore ledgers when no explicit
  currency is stated (medium confidence); multi-currency files raise
  `CURRENCY_INCONSISTENCY`.
- `.xls` post-date serials rely on `xlrd`; heavily merged or pivoted sheets
  may need layout tuning.
- AI extraction requires an OpenAI-compatible endpoint; without it the
  deterministic parser handles the three supplied files but may miss
  novel phrasings an LLM would catch.
- Missing-period detection only flags gaps *between* first and last observed
  periods, not unobserved months before/after the lease.
