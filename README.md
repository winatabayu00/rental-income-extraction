# Rental Income AI Extractor

AI-assisted rental-income extraction from messy Excel general ledgers.
Supports `.xlsx` (openpyxl) and legacy `.xls` (xlrd) workbooks with
different worksheet layouts, multiple sheets, and multiple properties
per file.

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
8. **Application Service** (`src/application_service.py`) — single shared
   layer (`process_files`, `process_file`, `process_uploaded_files`).
   Both `main.py` (CLI) and `app.py` (GUI) call it; no business logic
   lives in the presentation layer.
9. **Output** (`output/results.json` + CLI summary / GUI views).

## Why Hybrid AI + Rules

> The AI model is responsible for interpreting semi-structured accounting descriptions. Deterministic Python logic handles financial validation such as missing periods, duplicate records, overlapping periods, date continuity, and rental amount consistency.

This separation reduces hallucination risk: the LLM never performs financial
math or invents missing values (it returns `null` when uncertain, and invalid
AI output is rejected by schema validation before entering the pipeline),
while all date continuity, gap, duplicate, overlap, and amount comparisons
are plain reproducible Python that can be unit-tested and audited against
source rows.

## Project Structure

```text
.
├── app.py                 # Streamlit GUI (presentation only)
├── main.py                # CLI (presentation only)
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── input/                 # put .xls / .xlsx files here
├── output/                # results.json
├── src/
│   ├── config.py
│   ├── models.py
│   ├── excel_reader.py
│   ├── normalizer.py
│   ├── candidate_detector.py
│   ├── ai_extractor.py
│   ├── extraction_service.py
│   ├── rental_validator.py
│   ├── clarification_service.py
│   ├── output_writer.py
│   └── application_service.py
└── tests/
    ├── test_excel_reader.py
    ├── test_normalizer.py
    ├── test_candidate_detector.py
    ├── test_validator.py
    └── test_gap_detection.py
```

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
company → property expanders, monthly-record tables (with source sheet/rows),
issues, clarification questions, raw JSON, and **Download JSON**
(`rental-income-results.json` — identical structure to the CLI
`output/results.json`).

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

## Results on the Provided Files

Latest verified run (`python main.py ./input`, 3 processed / 0 failed):

| File | Company | Properties | Findings |
| ---- | ------- | ---------: | -------- |
| Wah Sin `.xlsx` | WAH SIN F.E. MARKETING PTE LTD | 2 | `Suntec City Tower One #09-03A` / IAI AISA: 12× `SGD 37,325.50`, `2024-01-16`→`2025-01-15`, no gaps; 2 half-month timing rows (partial + adjustment) with missing-address clarifications |
| Clive `.xls` | Clive Shophouses Pte Ltd | 1 | `41 Clive Street` / HTL Music Bar: 4× `SGD 8,000`, `2022-07`→`2022-10`, no gaps |
| Kampong Glam `.xls` | Kampong Glam Shophouses Pte Ltd | 9 | 8 units incl. `55 Bussorah St` 12/12 clean; `29 Arab #01-01` duplicate Nov-2025 + `5,500`→`5,800` + Feb–Mar 26 tail gap; `29 #03-01` 4-month tail gap; `33 #02-01` McLeod→Maxgolf tenant change |

## Rental logic notes

- Only the **Rental Income** account defines monthly records; tenant-AR,
  deposits, GST, journal duplicates and other accounts are ignored for
  cadence (but deposit/tenant headers enrich addresses).
- Rental periods come from explicit description dates when present
  (e.g. `From 16 January 2024 to 15 February 2024`), otherwise the posting
  month (1st → month-end).
- Mid-month cadences (`16th → 15th`) are compared as **period continuity**
  (`next.start == prev.end + 1 day`), not calendar-month numbers.
- In multi-property files, units ending well before the file's latest
  period get tail/head `MISSING_RENTAL_PERIOD` clarifications (lease ended
  vs. records missing).
- `standard_monthly_rental` is the mode amount (1% tolerance) when a clear
  majority exists, else `null`.
- Debits inside Rental Income are stored as negative (contra-income)
  adjustments/reversals and excluded from gap/amount cadence.
- Short tenant-only descriptions (e.g. `Midsummer Sun`, `HTL Music Bar`)
  are resolved via `Rent/xx` reference knowledge; unresolvable ones keep
  `property_address: null` and raise a clarification instead of a guess.

## GUI overview

- Multi-file uploader (`.xls`, `.xlsx`), file checklist, **Process Files**
  button (no auto-run), per-file progress bar.
- Summary cards: Files Processed / Properties Found / Missing Periods /
  Clarifications.
- Company → property expanders with address, tenant, currency, rental
  period, standard rental, record count, records table, issues, numbered
  clarification questions, raw JSON expander, and Download JSON.

## Limitations

- Currency defaults to `SGD` for these Singapore ledgers when no explicit
  currency is stated (medium confidence); multi-currency files raise
  `CURRENCY_INCONSISTENCY`.
- `.xls` post-date serials rely on `xlrd`; heavily merged or pivoted sheets
  may need layout tuning.
- AI extraction requires an OpenAI-compatible endpoint; without it the
  deterministic parser handles the three supplied files but may miss
  novel phrasings an LLM would catch.
- Tail/head coverage gaps only apply in files with 2+ monthly-cadence
  properties; single-property files only flag internal gaps.
