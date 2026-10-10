"""check_my_work.py: acceptance checks for the Week 0A Lead Intake CLI.

Run it from YOUR project root (the folder that contains lead_intake/), with your venv active:

    python ../week-0A/lead-intake-project/check_my_work.py
    python check_my_work.py path/to/lead-intake-project      # if you copied this file into your project

It runs your CLI exactly as SPEC.md describes, on both data files in this pack, writes
into temporary folders, and compares your report.json and valid_leads.json with the
files in expected/. It never imports or reads your code; it only runs it.

Standard library only. Python 3.11+. Exit code 0 only if every required check passes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

COLUMNS = ["lead_id", "full_name", "email", "loan_amount", "credit_score",
           "annual_income", "property_state", "loan_type", "created_at"]
REPORT_KEYS = ["run_at", "input_file", "total_rows", "valid_rows", "invalid_rows",
               "errors_by_field", "errors"]
DATASETS = [("sample", "leads_sample"), ("nightly", "leads_2026-10-02")]
TIMEOUT = 120

results: list[tuple[str, bool, bool]] = []   # (name, passed, required)
skipped: list[str] = []                       # datasets whose later checks couldn't run


# ---------------------------------------------------------------- output helpers
def say(text: str = "") -> None:
    print(text, flush=True)


def record(name: str, passed: bool, detail: str = "", required: bool = True) -> bool:
    tag = ("PASS" if passed else "FAIL") if required else ("PASS" if passed else "----")
    label = name if required else f"OPTIONAL  {name}"
    say(f"  {tag}  {label}")
    if detail:
        for line in detail.rstrip().splitlines():
            say(f"          {line}")
    results.append((name, passed, required))
    return passed


def tail(text: str, n: int = 6) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join("| " + ln[:160] for ln in lines[-n:])


def show(items: list, limit: int = 6) -> str:
    out = [f"- {x}" for x in items[:limit]]
    if len(items) > limit:
        out.append(f"... and {len(items) - limit} more")
    return "\n".join(out)


# ---------------------------------------------------------------- running the CLI
def run_cli(project: Path, args: list[str], log_level: str = "INFO") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["LOG_LEVEL"] = log_level
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", "lead_intake", *args], cwd=project, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=TIMEOUT)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path.name} was not written"
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"{path.name} is not valid JSON ({e})"


def crash_hint(stderr: str) -> str:
    if "\\ufefflead_id" in stderr or "KeyError: 'lead_id'" in stderr:
        return "Hint: the file starts with an Excel BOM. See SPEC.md section 1 (encoding)."
    if "NoneType" in stderr and ("strip" in stderr or "lower" in stderr or "upper" in stderr):
        return "Hint: a short row gives None for missing values. See SPEC.md section 3 (row shape)."
    if "No module named lead_intake" in stderr:
        return "Hint: run this from your project root, the folder that contains lead_intake/."
    if "No module named" in stderr:
        return "Hint: is your venv active? Install your requirements first."
    return ""


# ---------------------------------------------------------------- dataset checks
def check_dataset(project: Path, pack: Path, label: str, stem: str, tmp: Path) -> None:
    csv_path = pack / "data" / f"{stem}.csv"
    expected, err = load_json(pack / "expected" / f"{stem}.expected.json")
    exp_leads, err2 = load_json(pack / "expected" / f"{stem}.valid_leads.json")
    say(f"\n[{label}] data/{stem}.csv")
    if err or err2:
        record(f"{label}: pack files present", False, err or err2)
        return

    out = tmp / f"out-{label}" / "nested"   # also proves you create missing folders
    try:
        proc = run_cli(project, [str(csv_path), "--output-dir", str(out)])
    except subprocess.TimeoutExpired:
        record(f"{label}: run finishes", False, f"Still running after {TIMEOUT} s.")
        return
    ok = record(f"{label}: run completes with exit code 0", proc.returncode == 0,
                "" if proc.returncode == 0 else
                f"Exit code {proc.returncode}. Last lines of output:\n{tail(proc.stderr or proc.stdout)}\n"
                + crash_hint(proc.stderr))
    if not ok:
        skipped.append(label)
        return

    report, err = load_json(out / "report.json")
    leads, err2 = load_json(out / "valid_leads.json")
    if not record(f"{label}: report.json and valid_leads.json written to --output-dir",
                  report is not None and leads is not None, "\n".join(e for e in (err, err2) if e)):
        skipped.append(label)
        return
    if not isinstance(report, dict):
        record(f"{label}: report.json is an object", False, "Expected a JSON object {...} at the top level.")
        return
    missing = [k for k in REPORT_KEYS if k not in report]
    record(f"{label}: report.json has every key from SPEC.md", not missing,
           f"Missing: {', '.join(missing)}" if missing else "")

    # counts
    got = tuple(report.get(k) for k in ("total_rows", "valid_rows", "invalid_rows"))
    want = tuple(expected[k] for k in ("total_rows", "valid_rows", "invalid_rows"))
    detail = ""
    if got != want:
        detail = f"Expected {want[0]} / {want[1]} / {want[2]}, got {got[0]} / {got[1]} / {got[2]}."
        if isinstance(got[0], int) and got[0] > want[0]:
            detail += "\nHint: blank lines are skipped and not counted (SPEC.md section 2)."
    record(f"{label}: counts {want[0]} total / {want[1]} valid / {want[2]} invalid", got == want, detail)

    # errors_by_field
    ebf = report.get("errors_by_field")
    if not isinstance(ebf, dict):
        record(f"{label}: errors_by_field", False, "errors_by_field should be an object {field: count}.")
    else:
        fields = sorted(set(expected["errors_by_field"]) | {k for k, v in ebf.items() if v})
        diffs = [f"{f}: expected {expected['errors_by_field'].get(f, 0)}, got {ebf.get(f, 0)}"
                 for f in fields if expected["errors_by_field"].get(f, 0) != ebf.get(f, 0)]
        record(f"{label}: errors_by_field matches", not diffs, show(diffs, 10))

    # individual errors: compare (row, field) pairs, never the message text
    errors = report.get("errors")
    if not isinstance(errors, list):
        record(f"{label}: errors list", False, "errors should be a list of {row, lead_id, field, message}.")
    else:
        bad_shape = [e for e in errors if not (isinstance(e, dict) and isinstance(e.get("row"), int)
                     and isinstance(e.get("field"), str) and "lead_id" in e
                     and isinstance(e.get("message"), str) and e.get("message").strip())]
        record(f"{label}: every error has row (int), lead_id, field and a non-empty message",
               not bad_shape, "First problem: " + json.dumps(bad_shape[0])[:150] if bad_shape else "")
        want_pairs = Counter((e["row"], e["field"]) for e in expected["errors"])
        got_pairs = Counter((e.get("row"), e.get("field")) for e in errors if isinstance(e, dict))
        ids = {(e["row"], e["field"]): e["lead_id"] for e in expected["errors"]}
        missing = sorted((want_pairs - got_pairs).elements(), key=order)
        extra = sorted((got_pairs - want_pairs).elements(), key=order)
        lines = []
        if missing:
            lines.append(f"{len(missing)} expected error(s) missing:")
            lines.append(show([f"row {r} ({ids[(r, f)] or 'no id'}): {f}" for r, f in missing]))
        if extra:
            lines.append(f"{len(extra)} error(s) that should not be there:")
            lines.append(show([f"row {r}: {f}" for r, f in extra]))
        if missing and extra:
            extra_set = set(extra)
            shifted = sum(1 for wr, wf in missing
                          if any((wr - d, wf) in extra_set or (wr + d, wf) in extra_set for d in range(1, 6)))
            if shifted >= max(2, len(missing) // 2):
                lines.append("Hint: your row numbers are off by a few. A row's number is its line in the file, "
                             "and blank lines still count as lines (SPEC.md section 2).")
        if sum(1 for r, f in extra if f == "lead_id") >= 10:
            lines.append("Hint: lead_id looks missing on almost every row. The file starts with an "
                         "Excel BOM (SPEC.md section 1).")
        record(f"{label}: every expected (row, field) error present, and no extras",
               not missing and not extra, "\n".join(lines))

    # valid_leads.json
    check_leads(label, stem, leads, exp_leads)


def order(pair: tuple) -> tuple:
    """Sort (row, field) pairs by row number, then field."""
    return (pair[0] if isinstance(pair[0], int) else 10**9, str(pair[1]))


def type_problems(rec: dict) -> list[str]:
    probs = []
    if set(rec) != set(COLUMNS):
        extra, missing = sorted(set(rec) - set(COLUMNS)), sorted(set(COLUMNS) - set(rec))
        probs.append("keys should be exactly the 9 columns"
                     + (f"; extra: {', '.join(map(str, extra))}" if extra else "")
                     + (f"; missing: {', '.join(missing)}" if missing else ""))
    for f in ("lead_id", "full_name", "email", "property_state", "loan_type", "created_at"):
        if f in rec and not isinstance(rec[f], str):
            probs.append(f"{f} should be a string, got {type(rec[f]).__name__}")
    for f in ("loan_amount", "annual_income"):
        if f in rec and not isinstance(rec[f], float):
            probs.append(f"{f} should be a float (385000.0), got {type(rec[f]).__name__} {rec[f]!r}")
    cs = rec.get("credit_score")
    if "credit_score" in rec and (isinstance(cs, bool) or not isinstance(cs, int)):
        probs.append(f"credit_score should be an int (742), got {type(cs).__name__} {cs!r}")
    if isinstance(rec.get("email"), str) and rec["email"] != rec["email"].strip().lower():
        probs.append(f"email should be trimmed and lowercase: {rec['email']!r}")
    if isinstance(rec.get("property_state"), str) and rec["property_state"] != rec["property_state"].strip().upper():
        probs.append(f"property_state should be trimmed and uppercase: {rec['property_state']!r}")
    if isinstance(rec.get("loan_type"), str) and rec["loan_type"] != rec["loan_type"].strip().lower():
        probs.append(f"loan_type should be trimmed and lowercase: {rec['loan_type']!r}")
    for f in ("lead_id", "full_name"):
        if isinstance(rec.get(f), str) and rec[f] != rec[f].strip():
            probs.append(f"{f} should be trimmed: {rec[f]!r}")
    return probs


def same_value(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-9)
    return a == b


def check_leads(label: str, stem: str, leads, exp_leads: list) -> None:
    if not isinstance(leads, list) or not all(isinstance(x, dict) for x in leads):
        record(f"{label}: valid_leads.json is an array of records", False,
               "Expected a JSON array of objects, one per valid lead.")
        return
    probs = []
    for i, rec in enumerate(leads):
        for p in type_problems(rec):
            probs.append(f"{rec.get('lead_id', f'record {i}')}: {p}")
    record(f"{label}: valid_leads.json types and normalization (SPEC.md section 5)", not probs, show(probs, 5))

    got_ids = [r.get("lead_id") for r in leads]
    want_ids = [r["lead_id"] for r in exp_leads]
    detail = ""
    if got_ids != want_ids:
        if sorted(map(str, got_ids)) == sorted(want_ids):
            detail = "Same leads, different order. Keep the order of the input file."
        else:
            miss = [x for x in want_ids if x not in set(got_ids)]
            extra = [x for x in got_ids if x not in set(want_ids)]
            detail = (f"Expected {len(want_ids)} leads, got {len(got_ids)}.\n"
                      + (f"Missing: {', '.join(map(str, miss[:8]))}{' ...' if len(miss) > 8 else ''}\n" if miss else "")
                      + (f"Should not be there: {', '.join(map(str, extra[:8]))}{' ...' if len(extra) > 8 else ''}" if extra else ""))
    ok = record(f"{label}: valid_leads.json holds exactly the {len(want_ids)} valid leads, in file order",
                got_ids == want_ids, detail)
    if not ok:
        return
    diffs = []
    for got, want in zip(leads, exp_leads):
        for f in COLUMNS:
            if not same_value(got.get(f), want[f]):
                diffs.append(f"{want['lead_id']}.{f}: expected {want[f]!r}, got {got.get(f)!r}")
    record(f"{label}: every valid lead's values match expected/{stem}.valid_leads.json", not diffs, show(diffs, 5))


# ---------------------------------------------------------------- behaviour checks
def check_behaviour(project: Path, pack: Path, tmp: Path) -> None:
    say("\n[behaviour] exit codes and logging")
    sample = pack / "data" / "leads_sample.csv"

    # missing input -> exit 1 and an ERROR line
    missing = tmp / "does-not-exist" / "nope.csv"
    proc = run_cli(project, [str(missing), "--output-dir", str(tmp / "out-missing")])
    both = proc.stderr + proc.stdout
    has_error = any(" ERROR " in f" {ln} " or ln.startswith("ERROR") for ln in both.splitlines())
    detail = []
    if proc.returncode != 1:
        detail.append(f"Exit code was {proc.returncode}, expected 1.")
        if proc.returncode == 0:
            detail.append("A bare `return` or `sys.exit(None)` exits 0: return 1 explicitly.")
    if not has_error:
        detail.append("No ERROR log line found. Log it with logger.error(...).")
    record("missing input file -> exit code 1 and an ERROR log line",
           proc.returncode == 1 and has_error, "\n".join(detail))

    # LOG_LEVEL=DEBUG -> one 'Row N' DEBUG line per row; INFO -> none
    expected, _ = load_json(pack / "expected" / "leads_sample.expected.json")
    want_rows = set(range(2, 2 + (expected or {}).get("total_rows", 20)))
    proc = run_cli(project, [str(sample), "--output-dir", str(tmp / "out-debug")], log_level="DEBUG")
    debug_lines = [ln for ln in (proc.stderr + proc.stdout).splitlines() if "DEBUG" in ln]
    row_nums = Counter(int(m.group(1)) for ln in debug_lines for m in [re.search(r"\bRow (\d+)\b", ln)] if m)
    missing_rows = sorted(want_rows - set(row_nums))
    doubled = sorted(n for n, c in row_nums.items() if c > 1)
    detail = ""
    if proc.returncode != 0:
        detail = f"The DEBUG run exited {proc.returncode}.\n{tail(proc.stderr)}"
    elif not debug_lines and any(re.search(r"\bRow \d+\b", ln) for ln in proc.stderr.splitlines()):
        detail = "Your per-row 'Row N' lines are there, but not at DEBUG level. Log them with logger.debug(...)."
    elif not debug_lines:
        detail = ("No DEBUG lines at all. Read LOG_LEVEL from the environment; real environment "
                  "variables must win over .env (don't use override=True).")
    elif missing_rows or doubled:
        detail = ("Expected exactly one DEBUG line per row, written like 'Row 4 (L-1003): ...' "
                  "(SPEC.md section 7).")
        if missing_rows:
            detail += f"\nNo 'Row N' DEBUG line for rows: {', '.join(map(str, missing_rows[:12]))}"
        if doubled:
            detail += f"\nMore than one 'Row N' DEBUG line for rows: {', '.join(map(str, doubled[:12]))}"
    record("LOG_LEVEL=DEBUG -> one 'Row N' DEBUG line per row", not detail, detail)

    proc = run_cli(project, [str(sample), "--output-dir", str(tmp / "out-info")], log_level="INFO")
    lines = (proc.stderr + proc.stdout).splitlines()
    n_debug = sum(1 for ln in lines if "DEBUG" in ln)
    info_lines = [ln for ln in lines if "INFO" in ln]
    summary_ok = any(all(str(expected[k]) in ln for k in ("total_rows", "valid_rows", "invalid_rows"))
                     for ln in info_lines) if expected else bool(info_lines)
    detail = []
    if n_debug:
        detail.append(f"{n_debug} DEBUG line(s) printed at LOG_LEVEL=INFO.")
    if not summary_ok:
        detail.append("No INFO summary line with the three counts (e.g. '20 rows: 9 valid, 11 invalid ...').")
    record("LOG_LEVEL=INFO -> no DEBUG lines, one INFO summary with the counts", not detail, "\n".join(detail))


def check_strict(project: Path, pack: Path, tmp: Path) -> None:
    say("\n[optional] --strict")
    sample = pack / "data" / "leads_sample.csv"
    proc = run_cli(project, [str(sample), "--output-dir", str(tmp / "out-strict"), "--strict"])
    if "unrecognized arguments" in proc.stderr:
        record("--strict exits 2 when any row is invalid", False,
               "Not implemented yet (argparse doesn't know --strict). That's fine: it's a stretch goal.",
               required=False)
        return
    record("--strict exits 2 when any row is invalid", proc.returncode == 2,
           "" if proc.returncode == 2 else f"Exit code was {proc.returncode}.", required=False)
    clean = tmp / "clean.csv"
    lines = sample.read_text(encoding="utf-8-sig").splitlines()
    clean.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")   # header + 2 valid rows
    proc = run_cli(project, [str(clean), "--output-dir", str(tmp / "out-clean"), "--strict"])
    record("--strict exits 0 when every row is valid", proc.returncode == 0,
           "" if proc.returncode == 0 else f"Exit code was {proc.returncode} on a file with 2 valid rows.",
           required=False)


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Acceptance checks for the Week 0A Lead Intake CLI.")
    ap.add_argument("pack", nargs="?", type=Path, default=here,
                    help="the lead-intake-project folder (default: the folder this script is in)")
    ap.add_argument("--project", type=Path, default=Path.cwd(),
                    help="your project root, the folder containing lead_intake/ (default: current folder)")
    args = ap.parse_args(argv)
    pack, project = args.pack.resolve(), args.project.resolve()

    say("Lead Intake CLI: check_my_work.py")
    say(f"  project: {project}")
    say(f"  pack:    {pack}")
    say(f"  python:  {sys.executable} ({sys.version.split()[0]})")

    if sys.version_info < (3, 11):
        say("\nThis needs Python 3.11 or newer. Activate your project's venv and try again.")
        return 1
    if not (pack / "expected").is_dir() or not (pack / "data").is_dir():
        say(f"\nCan't find data/ and expected/ in {pack}.\n"
            "Pass the pack folder: python check_my_work.py path/to/lead-intake-project")
        return 1
    if not (project / "lead_intake" / "__main__.py").is_file():
        say(f"\nCan't find lead_intake/__main__.py in {project}.\n"
            "Run this from your project root (the folder that contains lead_intake/), or pass --project.")
        return 1

    with tempfile.TemporaryDirectory(prefix="lead-intake-check-") as t:
        tmp = Path(t)
        for label, stem in DATASETS:
            check_dataset(project, pack, label, stem, tmp)
        check_behaviour(project, pack, tmp)
        check_strict(project, pack, tmp)

    required = [r for r in results if r[2]]
    passed = sum(1 for r in required if r[1])
    optional = [r for r in results if not r[2]]
    opt_txt = f" | optional: {sum(1 for r in optional if r[1])} of {len(optional)}" if optional else ""
    say("\n" + "-" * 64)
    if passed == len(required):
        say(f"ALL REQUIRED CHECKS PASS: {passed} of {len(required)}{opt_txt}")
        say("Tick 'check_my_work.py: all required checks PASS' on the acceptance checklist.")
        return 0
    say(f"{passed} of {len(required)} required checks pass{opt_txt}")
    if skipped:
        say(f"More checks will run for [{'], ['.join(skipped)}] once that file's run completes.")
    say("Fix the first FAIL, run again. LOG_LEVEL=DEBUG and the per-row lines help you find it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
