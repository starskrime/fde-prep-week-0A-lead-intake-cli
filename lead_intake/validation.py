import logging
import math
import re
from collections import Counter
from datetime import date

logger = logging.getLogger(__name__)

STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


def build_error_message(row_number, lead_id, field, message):
    return {"row": row_number, "lead_id": lead_id, "field": field, "message": message}


# One parser per column. Each gets a trimmed, non-empty string and returns the
# normalized, correctly typed value, or raises ValueError with the report message.

def parse_text(value):
    return value


def parse_email(value):
    domain = value.partition("@")[2]
    if "@" not in value or "." not in domain:
        raise ValueError(f"not a valid email address: {value}")
    return value.lower()


def to_float(value):
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):
        raise ValueError(f"not a number: {value}")
    return number


def parse_loan_amount(value):
    amount = to_float(value)
    if amount <= 0:
        raise ValueError(f"must be greater than 0: {value}")
    if amount > 5_000_000:
        raise ValueError(f"must be at most 5,000,000: {value}")
    return amount


def parse_credit_score(value):
    try:
        score = int(value)
    except ValueError:
        raise ValueError(f"not a whole number: {value}") from None
    if not 300 <= score <= 850:
        raise ValueError(f"outside 300-850: {value}")
    return score


def parse_annual_income(value):
    income = to_float(value)
    if income < 0:
        raise ValueError(f"must be 0 or more: {value}")
    return income


def parse_property_state(value):
    if value.upper() not in STATES:
        raise ValueError(f"not a US state code: {value}")
    return value.upper()


def parse_loan_type(value):
    if value.lower() not in ("purchase", "refinance"):
        raise ValueError(f"must be purchase or refinance: {value}")
    return value.lower()


def parse_created_at(value):
    # shape first: fromisoformat() alone also accepts "20260901"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError(f"not a YYYY-MM-DD date: {value}")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"not a real calendar date: {value}") from None
    return value


PARSERS = {  # dict keeps insertion order = column order
    "lead_id": parse_text,
    "full_name": parse_text,
    "email": parse_email,
    "loan_amount": parse_loan_amount,
    "credit_score": parse_credit_score,
    "annual_income": parse_annual_income,
    "property_state": parse_property_state,
    "loan_type": parse_loan_type,
    "created_at": parse_created_at,
}


def count_values(row):
    # DictReader: long row -> extras in a list under key None; short row -> None values
    if None in row:
        return len(PARSERS) + len(row[None])
    return sum(value is not None for value in row.values())


def validate_row(row_number, row, seen_ids):
    """Return (clean_row or None, errors)."""
    lead_id = (row["lead_id"] or "").strip()

    found = count_values(row)
    if found != len(PARSERS):
        return None, [build_error_message(row_number, lead_id, "columns", f"expected {len(PARSERS)} values, found {found}")]

    errors = []
    if lead_id in seen_ids:
        errors.append(build_error_message(row_number, lead_id, "lead_id", "duplicate of an earlier row"))
    elif lead_id:
        seen_ids.add(lead_id)

    clean = {}
    for field, parse in PARSERS.items():
        value = row[field].strip()
        try:
            if not value:
                raise ValueError("missing")
            clean[field] = parse(value)
        except ValueError as error:
            errors.append(build_error_message(row_number, lead_id, field, str(error)))

    return (None if errors else clean), errors


def validate_rows(rows):
    """rows: list of (row_number, DictReader row)."""
    seen_ids = set()
    errors = []
    valid = []
    for row_number, row in rows:
        clean, row_errors = validate_row(row_number, row, seen_ids)
        errors += row_errors
        if clean:
            valid.append(clean)

        lead_id = (clean or row_errors[0])["lead_id"]
        status = "ok" if clean else "invalid: " + ", ".join(e["field"] for e in row_errors)
        logger.debug("Row %s (%s): %s", row_number, lead_id or "no id", status)

    errors_by_field = Counter(sorted(el["field"] for el in errors))  # sorted first -> keys A to Z
    by_state = Counter(sorted(lead["property_state"] for lead in valid))

    return {"total_rows": len(rows),
            "valid_rows": len(valid),
            "invalid_rows": len(rows) - len(valid),
            "errors_by_field": errors_by_field,
            "by_state": by_state,
            "errors": errors,
            "valid": valid
            }
