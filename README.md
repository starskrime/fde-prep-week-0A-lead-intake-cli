# Lead Intake CLI

Reads the nightly leads CSV exported from Excel, validates every row, and writes three files:

- `valid_leads.json`: the clean, normalized, correctly typed leads, ready for the CRM.
- `errors.csv`: every error as a spreadsheet row (`row, lead_id, field, message`), opens directly in Excel.
- `report.json`: counts, errors per field, and every error with its row number, so the web team can fix the source data.

Bad rows never stop the run. They are reported, not crashed on.

## Quick start

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m lead_intake data/leads_sample.csv --output-dir out
```

Expected log line:

```
INFO     lead_intake.cli: 20 rows: 9 valid, 11 invalid. Wrote out
```

## Usage

```
python -m lead_intake INPUT [--output-dir DIR] [--strict]
```

| Argument | Meaning |
|---|---|
| `INPUT` | Path to the CSV file (required) |
| `--output-dir DIR` | Where to write the output files. Created if missing. Default: `out` |
| `--strict` | Exit with code 2 if any row is invalid (for schedulers that should alert on bad data) |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Run completed. Invalid rows are fine, see `report.json` |
| `1` | Input file missing or unreadable (not found, not UTF-8). An ERROR is logged and nothing is written |
| `2` | Only with `--strict`: run completed and at least one row is invalid. (argparse also uses 2 for a bad command line) |

### Logging

Set the level with the `LOG_LEVEL` environment variable, or in a `.env` file (copy `.env.example`). A real environment variable wins over `.env`. Default: `INFO`.

- `INFO`: one summary line at the end.
- `DEBUG`: one line per row, for example `Row 4 (L-1003): invalid: email`.
- `ERROR`: input file cannot be read.

```bash
LOG_LEVEL=DEBUG python -m lead_intake data/leads_sample.csv
```

## Input

A UTF-8 CSV with this header on line 1:

```
lead_id,full_name,email,loan_amount,credit_score,annual_income,property_state,loan_type,created_at
```

Handled on purpose:

- **Excel BOM** at the start of the file: read with `utf-8-sig`.
- **Blank lines**: skipped, not counted as rows, but still counted as lines.
- **`\n` and `\r\n`** line endings, quoted values with commas (`"$385,000"`).

## Validation rules

Every value is trimmed first. All problems in a row are collected (at most one per field). A row is valid only with zero errors.

| Field | Valid when | Stored as |
|---|---|---|
| `lead_id` | not empty, not a duplicate of an earlier row | `str` |
| `full_name` | not empty | `str` |
| `email` | has `@`, and a `.` after it | `str`, lowercased |
| `loan_amount` | number, `> 0` and `<= 5,000,000` | `float` |
| `credit_score` | whole number, 300 to 850 | `int` |
| `annual_income` | number, `>= 0` | `float` |
| `property_state` | US state code or `DC` | `str`, uppercased |
| `loan_type` | `purchase` or `refinance` | `str`, lowercased |
| `created_at` | real calendar date, written `YYYY-MM-DD` | `str` |

Principle: **fix spacing and letter case, never guess at numbers or dates.** `$385,000`, `350k` and `N/A` are rejected, not interpreted.

A row without exactly 9 values gets a single `columns` error and nothing else is checked.

Each error carries a plain-language message the web team reads every morning.

### Example error

```json
{"row": 4, "lead_id": "L-1003", "field": "email", "message": "not a valid email address: aisha.rahman@example"}
```

`row` is the line number in the file (header = line 1), so it matches what you see in a text editor, even after blank lines.

## Output

`out/report.json`:

```json
{
  "run_at": "2026-10-03T14:02:11",
  "input_file": "data/leads_sample.csv",
  "total_rows": 20,
  "valid_rows": 9,
  "invalid_rows": 11,
  "errors_by_field": {"created_at": 1, "credit_score": 2, "email": 1, "loan_amount": 3},
  "by_state": {"DC": 1, "GA": 1, "MA": 1, "NV": 1, "OK": 1, "TX": 4},
  "errors": [ {"row": 4, "lead_id": "L-1003", "field": "email", "message": "..."} ]
}
```

`invalid_rows` counts rows, `errors` counts problems: a row with two problems adds 1 and 2. `errors_by_field` lists only fields with at least one error, keys sorted A to Z. `by_state` counts **valid** leads per state, also sorted.

`out/valid_leads.json`: array of valid leads in file order, each with exactly the 9 columns, typed as in the table above.

## Check your work

`check_my_work.py` runs the CLI on both data files and compares results with `expected/`:

```bash
python check_my_work.py .
```

| File | total / valid / invalid |
|---|---|
| `data/leads_sample.csv` | 20 / 9 / 11 |
| `data/leads_2026-10-02.csv` | 250 / 209 / 41 |

It also checks exit codes, the log levels, and `--strict`. Exit code 0 means every required check passes.

## Project layout

```
lead_intake/
  __main__.py     entry point: sys.exit(main())
  cli.py          arguments, logging setup, orchestration, report building
  io_utils.py     read CSV (BOM, line numbers), write JSON
  validation.py   one parser per column, row and file validation
data/             sample and nightly CSVs
expected/         expected outputs used by check_my_work.py
check_my_work.py  acceptance checks
```

## Design notes

- **One parser per column** (`PARSERS` in `validation.py`). Each takes a trimmed string, returns the typed value or raises `ValueError` with the report message. Adding a field means adding one function and one line.
- **Row numbers come from `csv.reader.line_num`**, not `enumerate`, because blank lines would make `enumerate` drift.
- **Date shape is checked before `date.fromisoformat()`**, which on Python 3.11+ also accepts `20260901`.
- **`float()` accepts `nan` and `inf`**; both are rejected as `not a number`.
- Read errors are caught before anything is written, so a failed run leaves no half-written output.
