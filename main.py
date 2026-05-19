from __future__ import annotations
import argparse
import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import config
from parsers.base_parser import CSV_COLUMNS, ParseResult, parse_date_from_filename
from parsers.detector import get_parser


def write_csv(out_path: Path, result: ParseResult, warning: str | None):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if warning:
            writer.writerow(["WARNING", warning])
            writer.writerow([])
        writer.writerow(CSV_COLUMNS)
        for line in result.lines:
            row = line.to_csv_row()
            writer.writerow([row[col] for col in CSV_COLUMNS])


def run(folder: str, out_dir_arg: str | None):
    folder_path = Path(folder)
    if not folder_path.exists():
        print(f"ERROR: folder not found: {folder_path}")
        sys.exit(1)

    out_dir = Path(out_dir_arg) if out_dir_arg else Path(config.OUTPUT_FOLDER)
    out_dir.mkdir(exist_ok=True)

    files = sorted(
        f for f in folder_path.iterdir()
        if f.suffix.lower() in (".xlsx", ".xls", ".pdf") and not f.name.startswith("~$")
    )

    # Juzo: prefer Excel over PDF — skip PDF files when an Excel version is present
    juzo_xlsx_exists = any("juzo" in f.name.lower() and f.suffix.lower() == ".xlsx" for f in files)
    if juzo_xlsx_exists:
        files = [f for f in files if not ("juzo" in f.name.lower() and f.suffix.lower() == ".pdf")]

    if not files:
        print("No .xlsx or .pdf files found.")
        return

    print(f"Processing {folder_path}/ ({len(files)} files)...")

    total_records = 0
    total_warnings = 0
    skipped = []

    for fpath in files:
        parser = get_parser(fpath)
        if parser is None:
            print(f"  [SKIP] {fpath.name} — no parser registered")
            skipped.append(fpath.name)
            continue

        try:
            result: ParseResult = parser.parse()
        except Exception as exc:
            print(f"  [ERROR] {fpath.name} — {exc}")
            skipped.append(fpath.name)
            continue

        count = len(result.lines)

        # Backfill statement_date from filename if content didn't provide one
        if result.lines and all(ln.statement_date is None for ln in result.lines):
            fn_date = parse_date_from_filename(fpath.name)
            if fn_date:
                for ln in result.lines:
                    ln.statement_date = fn_date

        # Validation
        warning = None
        if result.file_total is not None and count > 0:
            line_sum = sum(
                (ln.balance_amount for ln in result.lines if ln.balance_amount is not None),
                Decimal(0),
            )
            if abs(line_sum - result.file_total) > Decimal("0.01"):
                warning = (
                    f"sum of line totals ({line_sum:.2f}) "
                    f"does not equal total amount ({result.file_total:.2f})"
                )
                total_warnings += 1

        # Output CSV named after the source file (stem only, no extension)
        out_path = out_dir / f"{fpath.stem}.csv"
        write_csv(out_path, result, warning)

        status = "[WARN]" if warning else "[OK]  "
        print(f"  {status} {fpath.name:<55} -> {count:>4} lines  -> {out_path.name}")
        total_records += count

    total_files = len(files) - len(skipped)
    print(f"\nDone: {total_files} files processed, {total_records} records -> {out_dir}/")
    if skipped:
        print(f"Skipped ({len(skipped)}): {', '.join(skipped)}")
    if total_warnings:
        print(f"Validation warnings: {total_warnings}")


def main():
    parser = argparse.ArgumentParser(description="AP Statement Reconciliation -- parse & standardize")
    parser.add_argument("--folder", default=config.STATEMENTS_FOLDER, help="Folder with statement files")
    parser.add_argument("--outdir", default=None, help="Output folder (default: output/)")
    args = parser.parse_args()
    run(args.folder, args.outdir)


if __name__ == "__main__":
    main()
