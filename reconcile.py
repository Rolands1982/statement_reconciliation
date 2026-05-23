"""
Phase 2: AP Statement Reconciliation — P21 lookup.

Reads all vendor statement CSVs from output/, queries P21's apinv_hdr for each
vendor, matches by invoice number, and writes output/reconciliation_report.csv.

Usage:
    python reconcile.py
    python reconcile.py --run-phase1
    python reconcile.py --folder statements --outdir output --report output/reconciliation_report.csv

Options:
    --run-phase1        Re-parse all statement files before reconciling
    --folder PATH       Statements folder (default: config.STATEMENTS_FOLDER)
    --outdir PATH       Phase 1 output folder (default: config.OUTPUT_FOLDER)
    --report PATH       Reconciliation report path (default: output/reconciliation_report.csv)
    --vendor NAME       Reconcile only this vendor (substring match on vendor_name)
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import config
from p21.client import P21AuthError, P21ApiError, P21Client
from p21.ap_lookup import fetch_ap_records, ApRecord

# ── Report columns ────────────────────────────────────────────────────────────
REPORT_COLUMNS = [
    "source_file",
    "vendor_name",
    "statement_date",
    "invoice_number",
    "transaction_type",
    "invoice_date",
    "due_date",
    "po_number",
    "statement_amount",   # balance_amount from Phase 1
    "statement_inv_amount",  # original invoice_amount from Phase 1
    "p21_invoice_amount",
    "p21_remaining",
    "p21_voucher_type",
    "p21_vendor_id",
    "discrepancy",
    "match_status",
]

# match_status values
MS_MATCHED        = "Matched"
MS_MATCHED_REM    = "Matched (remaining)"
MS_PARTIAL        = "Partial payment"
MS_MISMATCH       = "Amount mismatch"
MS_NOT_IN_P21     = "Not in P21"
MS_NOT_CONFIGURED = "Vendor not configured"
MS_UNAVAILABLE    = "P21 unavailable"
MS_NO_INV         = "No invoice number"


def _to_decimal(val) -> Decimal | None:
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


def _normalize(inv: str) -> str:
    return inv.strip().lstrip("0").upper()


# ── Phase 1 CSV loading ───────────────────────────────────────────────────────

def load_statement_rows(csv_path: Path) -> list[dict]:
    """Load rows from a Phase 1 CSV, skipping WARNING header rows."""
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        raw = list(csv.reader(f))

    # Skip leading WARNING rows (Phase 1 writes "WARNING", "", <headers> pattern)
    start = 0
    for i, row in enumerate(raw):
        if row and row[0] == "WARNING":
            start = i + 2  # skip WARNING row + blank row
            break

    if not raw:
        return rows

    header = raw[start]
    for row in raw[start + 1:]:
        if not any(row):
            continue
        rows.append(dict(zip(header, row)))
    return rows


def collect_statement_lines(out_dir: Path, vendor_filter: str | None) -> dict[str, list[dict]]:
    """
    Load all vendor statement CSVs from out_dir.
    Returns {vendor_name: [row, ...]}
    Skips reconciliation_report.csv and *_reconciled.csv files.
    """
    by_vendor: dict[str, list[dict]] = {}
    for csv_path in sorted(out_dir.glob("*.csv")):
        name = csv_path.stem.lower()
        if "reconciliation_report" in name or name.endswith("_reconciled"):
            continue
        rows = load_statement_rows(csv_path)
        for row in rows:
            vendor = row.get("vendor_name", "").strip()
            if not vendor:
                continue
            if vendor_filter and vendor_filter.lower() not in vendor.lower():
                continue
            by_vendor.setdefault(vendor, []).append(row)
    return by_vendor


# ── Matching logic ────────────────────────────────────────────────────────────

def match_row(row: dict, p21_lookup: dict[str, ApRecord]) -> dict:
    """Match one statement row against the P21 lookup dict. Returns report dict."""
    inv_no   = _normalize(str(row.get("invoice_number", "")))
    stmt_bal = _to_decimal(row.get("balance_amount"))
    stmt_inv = _to_decimal(row.get("invoice_amount"))

    base = {
        "source_file":       row.get("source_file", ""),
        "vendor_name":       row.get("vendor_name", ""),
        "statement_date":    row.get("statement_date", ""),
        "invoice_number":    row.get("invoice_number", ""),
        "transaction_type":  row.get("transaction_type", ""),
        "invoice_date":      row.get("invoice_date", ""),
        "due_date":          row.get("due_date", ""),
        "po_number":         row.get("po_number", ""),
        "statement_amount":  str(stmt_bal) if stmt_bal is not None else row.get("balance_amount", ""),
        "statement_inv_amount": str(stmt_inv) if stmt_inv is not None else row.get("invoice_amount", ""),
        "p21_invoice_amount": "",
        "p21_remaining":      "",
        "p21_voucher_type":   "",
        "p21_vendor_id":      "",
        "discrepancy":        "",
        "match_status":       "",
    }

    if not inv_no:
        base["match_status"] = MS_NO_INV
        return base

    rec = p21_lookup.get(inv_no)
    if rec is None:
        base["match_status"] = MS_NOT_IN_P21
        return base

    base["p21_invoice_amount"] = str(rec.invoice_amount) if rec.invoice_amount is not None else ""
    base["p21_remaining"]      = str(rec.remaining)      if rec.remaining      is not None else ""
    base["p21_voucher_type"]   = rec.voucher_type or ""
    base["p21_vendor_id"]      = str(rec.vendor_id)

    p21_inv = rec.invoice_amount
    p21_rem = rec.remaining

    # Priority 1: balance matches P21 remaining
    if p21_rem is not None and stmt_bal is not None and abs(p21_rem - stmt_bal) < Decimal("0.01"):
        base["discrepancy"]  = "0.00"
        base["match_status"] = MS_MATCHED_REM

    # Priority 2: balance matches P21 invoice_amount
    elif p21_inv is not None and stmt_bal is not None and abs(p21_inv - stmt_bal) < Decimal("0.01"):
        base["discrepancy"]  = "0.00"
        base["match_status"] = MS_MATCHED

    # Priority 3: original invoice amounts match (partial payment situation)
    elif p21_inv is not None and stmt_inv is not None and abs(p21_inv - stmt_inv) < Decimal("0.01"):
        disc = (p21_inv - stmt_bal) if stmt_bal is not None else None
        base["discrepancy"]  = str(disc) if disc is not None else ""
        base["match_status"] = MS_PARTIAL

    # Priority 4: genuine mismatch
    else:
        disc = (p21_inv - stmt_bal) if (p21_inv is not None and stmt_bal is not None) else None
        base["discrepancy"]  = str(disc) if disc is not None else ""
        base["match_status"] = MS_MISMATCH

    return base


# ── Main reconciliation flow ──────────────────────────────────────────────────

def reconcile(
    out_dir: Path,
    report_path: Path,
    vendor_filter: str | None = None,
    client: P21Client | None = None,
) -> None:
    by_vendor = collect_statement_lines(out_dir, vendor_filter)
    if not by_vendor:
        print("No statement lines found.")
        return

    total_vendors = len(by_vendor)
    total_lines   = sum(len(v) for v in by_vendor.values())
    print(f"Loaded {total_lines:,} statement lines across {total_vendors} vendors")

    # Initialise P21 client once
    p21_ok = True
    if client is None:
        if not config.P21_BASE_URL:
            print("WARNING: P21_BASE_URL not set — all lines will be 'P21 unavailable'")
            p21_ok = False
        else:
            try:
                client = P21Client(
                    config.P21_BASE_URL,
                    config.P21_USERNAME,
                    config.P21_PASSWORD,
                )
                client._get_token()  # Eagerly validate credentials
                print(f"  [P21] Connected to {config.P21_BASE_URL}")
            except P21AuthError as e:
                print(f"WARNING: P21 auth failed — {e}\n  All lines will be 'P21 unavailable'")
                p21_ok = False

    # Normalise VENDOR_P21_IDS values to lists
    vendor_ids: dict[str, list[str]] = {
        name: ([ids] if isinstance(ids, str) else list(ids))
        for name, ids in config.VENDOR_P21_IDS.items()
    }

    report_rows: list[dict] = []
    stats = {MS_MATCHED: 0, MS_MATCHED_REM: 0, MS_PARTIAL: 0, MS_MISMATCH: 0,
             MS_NOT_IN_P21: 0, MS_NOT_CONFIGURED: 0, MS_UNAVAILABLE: 0, MS_NO_INV: 0}

    for vendor, rows in sorted(by_vendor.items()):
        print(f"\n  {vendor} ({len(rows)} lines)")

        # Vendor not in config
        if vendor not in vendor_ids:
            print(f"    -> not configured in VENDOR_P21_IDS -- skipping P21 lookup")
            for row in rows:
                r = match_row(row, {})
                r["match_status"] = MS_NOT_CONFIGURED
                report_rows.append(r)
                stats[MS_NOT_CONFIGURED] += 1
            continue

        # P21 unavailable
        if not p21_ok:
            for row in rows:
                r = match_row(row, {})
                r["match_status"] = MS_UNAVAILABLE
                report_rows.append(r)
                stats[MS_UNAVAILABLE] += 1
            continue

        # Compute min invoice_date from statement lines
        inv_dates = [
            date.fromisoformat(r["invoice_date"])
            for r in rows if r.get("invoice_date")
        ]
        min_date = min(inv_dates) if inv_dates else date.today()

        # Fetch from all P21 vendor IDs and merge
        p21_lookup: dict[str, ApRecord] = {}
        ids = vendor_ids[vendor]
        for vid in ids:
            try:
                records = fetch_ap_records(client, vid, min_date)
                dupes = sum(1 for k in (r.invoice_no for r in records) if k in p21_lookup)
                if dupes:
                    print(f"    WARNING: {dupes} duplicate invoice_no(s) across vendor IDs — keeping first")
                for rec in records:
                    if rec.invoice_no not in p21_lookup:
                        p21_lookup[rec.invoice_no] = rec
                print(f"    vendor_id {vid}: {len(records):,} records fetched")
            except P21ApiError as e:
                print(f"    WARNING: P21 API error for vendor_id {vid}: {e}")
                # Mark only this vendor's rows as unavailable and move on
                for row in rows:
                    r = match_row(row, {})
                    r["match_status"] = MS_UNAVAILABLE
                    report_rows.append(r)
                    stats[MS_UNAVAILABLE] += 1
                p21_lookup = None  # Signal that we already appended rows
                break

        if p21_lookup is None:
            continue  # Already handled above

        # Match each statement line
        vendor_stats = {k: 0 for k in stats}
        for row in rows:
            r = match_row(row, p21_lookup)
            report_rows.append(r)
            stats[r["match_status"]] += 1
            vendor_stats[r["match_status"]] += 1

        matched = vendor_stats[MS_MATCHED] + vendor_stats[MS_MATCHED_REM]
        print(f"    Matched: {matched}  Partial: {vendor_stats[MS_PARTIAL]}"
              f"  Mismatch: {vendor_stats[MS_MISMATCH]}  Not in P21: {vendor_stats[MS_NOT_IN_P21]}")

    # Write report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(report_rows)

    # Summary
    total = len(report_rows)
    matched_total = stats[MS_MATCHED] + stats[MS_MATCHED_REM]
    print(f"\n{'-'*55}")
    print(f"Reconciliation complete — {total:,} lines total")
    print(f"  Matched              : {matched_total:,}  ({matched_total/total*100:.1f}%)")
    print(f"  Matched (remaining)  : {stats[MS_MATCHED_REM]:,}")
    print(f"  Partial payment      : {stats[MS_PARTIAL]:,}")
    print(f"  Amount mismatch      : {stats[MS_MISMATCH]:,}")
    print(f"  Not in P21           : {stats[MS_NOT_IN_P21]:,}")
    print(f"  Vendor not configured: {stats[MS_NOT_CONFIGURED]:,}")
    print(f"  P21 unavailable      : {stats[MS_UNAVAILABLE]:,}")
    print(f"  No invoice number    : {stats[MS_NO_INV]:,}")
    print(f"\nReport: {report_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AP Statement Reconciliation — Phase 2")
    parser.add_argument("--run-phase1", action="store_true",
                        help="Re-parse statement files before reconciling")
    parser.add_argument("--folder",  default=config.STATEMENTS_FOLDER,
                        help="Statements folder")
    parser.add_argument("--outdir",  default=config.OUTPUT_FOLDER,
                        help="Phase 1 output folder")
    parser.add_argument("--report",  default="output/reconciliation_report.csv",
                        help="Reconciliation report output path")
    parser.add_argument("--vendor",  default=None,
                        help="Reconcile only this vendor (substring match)")
    args = parser.parse_args()

    if args.run_phase1:
        print("Running Phase 1 (parsing statements)...")
        import main as phase1
        phase1.run(args.folder, args.outdir)

    reconcile(
        out_dir     = Path(args.outdir),
        report_path = Path(args.report),
        vendor_filter = args.vendor,
    )


if __name__ == "__main__":
    main()
