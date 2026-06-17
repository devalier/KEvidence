#!/usr/bin/env python3
"""Build a local searchable OpenFoodTox SQLite index from EFSA exports.

This is the non-IUCLID path for regular KEvidence installations. Download the
OpenFoodTox Excel export from EFSA/Zenodo, then run for example:

    python scripts/import_openfoodtox.py --input OpenFoodTox_3.xlsx --db data/openfoodtox.db

The importer intentionally stores source rows generically because OpenFoodTox
sheet names and column names may evolve. The application classifies matching
rows at query time into substances, toxicological values/study records, and
publication/source-link records.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Iterable


def clean_cell(value):
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split())


def iter_xlsx_rows(path: Path) -> Iterable[tuple[str, dict[str, str]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise SystemExit("openpyxl is required for .xlsx imports. Install requirements.txt first.") from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        rows = sheet.iter_rows(values_only=True)
        headers = None
        for raw in rows:
            values = [clean_cell(v) for v in raw]
            if not any(values):
                continue
            if headers is None:
                headers = [v or f"column_{i + 1}" for i, v in enumerate(values)]
                continue
            row = {headers[i] if i < len(headers) else f"column_{i + 1}": values[i] for i in range(len(values))}
            if any(row.values()):
                yield sheet.title, row


def iter_delimited_rows(path: Path) -> Iterable[tuple[str, dict[str, str]]]:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            cleaned = {clean_cell(k): clean_cell(v) for k, v in row.items() if k is not None}
            if any(cleaned.values()):
                yield path.stem, cleaned


def iter_input_rows(path: Path) -> Iterable[tuple[str, dict[str, str]]]:
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.suffix.lower() in {".csv", ".tsv", ".tab", ".xlsx", ".xlsm"}:
                yield from iter_input_rows(child)
    elif path.suffix.lower() in {".xlsx", ".xlsm"}:
        yield from iter_xlsx_rows(path)
    elif path.suffix.lower() in {".csv", ".tsv", ".tab"}:
        yield from iter_delimited_rows(path)
    else:
        raise SystemExit(f"Unsupported input format: {path}")


def build_index(input_path: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS oft_rows")
    cur.execute("DROP TABLE IF EXISTS oft_metadata")
    cur.execute("CREATE TABLE oft_rows (id INTEGER PRIMARY KEY, table_name TEXT, row_text TEXT, row_json TEXT)")
    cur.execute("CREATE INDEX idx_oft_rows_table ON oft_rows(table_name)")
    cur.execute("CREATE TABLE oft_metadata (key TEXT PRIMARY KEY, value TEXT)")

    count = 0
    for table_name, row in iter_input_rows(input_path):
        row_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
        row_text = f"{table_name} " + " ".join(str(v) for v in row.values())
        cur.execute(
            "INSERT INTO oft_rows (table_name, row_text, row_json) VALUES (?, ?, ?)",
            (table_name, row_text.lower(), row_json),
        )
        count += 1
        if count % 5000 == 0:
            conn.commit()

    cur.execute("INSERT INTO oft_metadata (key, value) VALUES (?, ?)", ("source_path", str(input_path)))
    cur.execute("INSERT INTO oft_metadata (key, value) VALUES (?, ?)", ("row_count", str(count)))
    conn.commit()
    conn.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="Import EFSA OpenFoodTox Excel/CSV exports into a KEvidence SQLite index.")
    parser.add_argument("--input", required=True, help="OpenFoodTox .xlsx file, .csv/.tsv file, or directory of exported sheets")
    parser.add_argument("--db", default="data/openfoodtox.db", help="Output SQLite DB path")
    args = parser.parse_args()

    count = build_index(Path(args.input), Path(args.db))
    print(f"Imported {count} OpenFoodTox rows into {args.db}")


if __name__ == "__main__":
    main()
