import logging
from pathlib import Path
import csv
import json

logger = logging.getLogger(__name__)


def read_rows(path: Path) -> list:
    """Return (row_number, row) pairs. Row number = line in the file, header is line 1."""
    logger.debug("Reading rows from %s", path)

    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        # line_num is read right after each row is parsed, so blank lines are counted
        return [(reader.line_num, row) for row in reader]


def write_json(path, name, data):
    logger.debug("Writing %s", name)
    check_path_and_create(path)
    with open(path / name, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def check_path_and_create(path: Path):
    path.mkdir(parents=True, exist_ok=True)
