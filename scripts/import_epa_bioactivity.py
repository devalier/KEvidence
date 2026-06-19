#!/usr/bin/env python3
"""Build a local searchable EPA ToxCast/Tox21/ToxRefDB-style SQLite index.

This importer is intentionally generic because EPA/CompTox enhanced exports and
ToxRefDB summary files can differ by release and export route. It stores each
row as JSON plus a lowercase search string, and the KEvidence API normalizes
common columns such as chemical name, CASRN/DTXSID, assay/endpoint, AC50/POD,
and source links when present.

Examples:
  python scripts/import_epa_bioactivity.py --input toxcast_ac50_export.csv --db data/bioactivity.db
  python scripts/import_epa_bioactivity.py --input toxcast_exports/ --db data/bioactivity.db
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


def clean_table_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_") or "sheet"


def read_csv_rows(path: Path) -> Iterable[dict[str, Any]]:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            yield {str(k).strip(): v for k, v in row.items() if k is not None}


def read_excel_rows(path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise SystemExit("Reading .xlsx files requires openpyxl. Install requirements.txt first.") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = [str(v).strip() if v is not None else "" for v in next(rows)]
        except StopIteration:
            continue
        headers = [h or f"column_{idx + 1}" for idx, h in enumerate(headers)]
        table_name = clean_table_name(sheet.title)
        for values in rows:
            if not values or all(v is None or str(v).strip() == "" for v in values):
                continue
            yield table_name, {headers[idx]: values[idx] if idx < len(values) else None for idx in range(len(headers))}


def iter_input_rows(input_path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    if input_path.is_dir():
        for child in sorted(input_path.iterdir()):
            if child.suffix.lower() in {".csv", ".tsv", ".tab", ".xlsx", ".xlsm"}:
                yield from iter_input_rows(child)
        return
    if input_path.suffix.lower() in {".xlsx", ".xlsm"}:
        yield from read_excel_rows(input_path)
        return
    if input_path.suffix.lower() in {".csv", ".tsv", ".tab"}:
        table_name = clean_table_name(input_path.stem)
        for row in read_csv_rows(input_path):
            yield table_name, row
        return
    raise SystemExit(f"Unsupported input format: {input_path}")


def build_index(input_path: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS bioactivity_rows")
    cur.execute("DROP TABLE IF EXISTS bioactivity_metadata")
    cur.execute("CREATE TABLE bioactivity_rows (id INTEGER PRIMARY KEY, source_table TEXT, row_text TEXT, row_json TEXT)")
    cur.execute("CREATE INDEX idx_bioactivity_rows_text ON bioactivity_rows(row_text)")
    cur.execute("CREATE TABLE bioactivity_metadata (key TEXT PRIMARY KEY, value TEXT)")

    count = 0
    for source_table, row in iter_input_rows(input_path):
        row_json = json.dumps(row, ensure_ascii=False, default=str)
        row_text = f"{source_table} " + " ".join(str(v) for v in row.values() if v is not None)
        cur.execute(
            "INSERT INTO bioactivity_rows (source_table, row_text, row_json) VALUES (?, ?, ?)",
            (source_table, row_text.lower(), row_json),
        )
        count += 1
        if count % 10000 == 0:
            conn.commit()

    cur.execute("INSERT INTO bioactivity_metadata (key, value) VALUES (?, ?)", ("source_input", str(input_path)))
    cur.execute("INSERT INTO bioactivity_metadata (key, value) VALUES (?, ?)", ("row_count", str(count)))
    conn.commit()
    conn.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import EPA ToxCast/Tox21/ToxRefDB-style CSV/XLSX exports into a KEvidence SQLite index.")
    parser.add_argument("--input", required=True, help="CSV/TSV/XLSX file or directory of exported files")
    parser.add_argument("--db", default="data/bioactivity.db", help="Output SQLite DB path")
    args = parser.parse_args()
    count = build_index(Path(args.input), Path(args.db))
    print(f"Imported {count} EPA bioactivity/toxicity rows into {args.db}")


if __name__ == "__main__":
    main()
