import argparse
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .io_utils import read_rows, write_json
from .validation import validate_rows

load_dotenv()

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    parser = argparse.ArgumentParser(prog="lead_intake", description="Lead intake process")
    parser.add_argument("input", type=Path, help="Path to the CSV file")
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="Where to write the JSON files (default: out)")
    parser.add_argument("--strict", action="store_true", help="Exit 2 if any row is invalid")
    args = parser.parse_args()

    run_at = datetime.now().isoformat(timespec="seconds")

    try:
        rows = read_rows(args.input)
    except FileNotFoundError:
        logger.error("Input file not found: %s", args.input)
        return 1
    except (OSError, UnicodeDecodeError) as error:
        logger.error("Cannot read input file %s: %s", args.input, error)
        return 1

    result = validate_rows(rows)

    write_json(args.output_dir, "valid_leads.json", result["valid"])
    write_json(args.output_dir, "report.json", build_report(run_at, args.input, result))

    logger.info("%s rows: %s valid, %s invalid. Wrote %s",
                result["total_rows"], result["valid_rows"], result["invalid_rows"], args.output_dir)

    return 2 if args.strict and result["invalid_rows"] else 0


def build_report(run_at, path, result):
    return {
        "run_at": run_at,
        "input_file": str(path),
        "total_rows": result["total_rows"],
        "valid_rows": result["valid_rows"],
        "invalid_rows": result["invalid_rows"],
        "errors_by_field": result["errors_by_field"],
        "errors": result["errors"],
    }
