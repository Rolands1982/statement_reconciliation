"""
Reconcile a statement CSV against one or more P21 response JSON files.
Adds p21_amount, p21_voucher_type, p21_vendor_id, discrepancy, match_status columns.

Usage:
    python match_statement.py <statement_csv> <p21_json> [<p21_json2> ...]

Examples:
    python match_statement.py "output/CASCADE Statement_DJO.csv" response_DJO response_DrComfort.json
    python match_statement.py "output/1005987_Statement_20260501_Juzo.csv" response_Juzo.json
"""
import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path


def to_decimal(val) -> Decimal | None:
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


def normalize(inv: str) -> str:
    """Normalize invoice numbers for consistent matching.

    Steps applied in order:
    1. Strip whitespace and uppercase
    2. Strip leading alpha characters (e.g. 'CD2139288' -> '2139288', Aspen pattern)
    3. Strip trailing dash+alpha suffix (e.g. '2050162-IN' -> '2050162', JMS Plastics pattern)
    4. Strip leading zeros (e.g. '0100887371' -> '100887371')
    5. Strip '100' prefix left over from '0100XXXXXX' pattern (Justin Blair)
       only when result is exactly 9 digits starting with '100'
    """
    import re
    s = inv.strip().upper()
    s = re.sub(r"^[A-Z]+", "", s)           # strip leading alpha (Aspen: CD prefix)
    s = s.lstrip("-")                        # strip leading dash (Langer: CUSINV- -> -)
    s = re.sub(r"-[A-Z]+$", "", s)          # strip trailing -IN / -CM suffix (JMS Plastics)
    s = s.lstrip("0")                        # strip leading zeros (Juzo)
    if len(s) == 9 and s.startswith("100") and s[3:].isdigit():
        s = s[3:]                            # strip 0100XXXXXX pattern (Justin Blair)
    return s


def load_p21(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Returns (by_invoice_no, by_po_no) — both normalized."""
    # Try utf-8-sig first (handles BOM), fall back to utf-8
    for enc in ("utf-8-sig", "utf-8"):
        try:
            with path.open(encoding=enc) as f:
                data = json.load(f)
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    records = data.get("value", data) if isinstance(data, dict) else data
    by_inv = {}
    by_po  = {}
    dupes  = 0
    for rec in records:
        inv_no = normalize(str(rec.get("invoice_no", "")))
        if not inv_no:
            continue
        if inv_no in by_inv:
            dupes += 1
        else:
            by_inv[inv_no] = rec
        # Also index by po_no (for vendors like KidSole where stmt uses PO as invoice)
        po_no = normalize(str(rec.get("po_no", "")))
        if po_no and po_no not in by_po:
            by_po[po_no] = rec
    print(f"  {path.name}: {len(records):,} records, {len(by_inv):,} unique invoice_no"
          + (f", {dupes} duplicates kept first" if dupes else ""))
    return by_inv, by_po


def load_statements(paths: list[Path]) -> tuple[list[dict], Path]:
    """Load and merge one or more statement CSVs. Output path based on first file."""
    all_rows = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as f:
            all_rows.extend(list(csv.DictReader(f)))
    return all_rows, paths[0]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    # Auto-detect: .csv files = statements, everything else = P21 JSON
    all_args    = [Path(p) for p in sys.argv[1:]]
    stmt_paths  = [p for p in all_args if p.suffix.lower() == ".csv"]
    p21_paths   = [p for p in all_args if p.suffix.lower() != ".csv"]

    if not stmt_paths or not p21_paths:
        print("ERROR: provide at least one .csv statement and one P21 JSON file")
        sys.exit(1)

    output_path = stmt_paths[0].parent / (stmt_paths[0].stem + "_reconciled.csv")

    # ── Load and merge all P21 files ─────────────────────────────────────────
    print("Loading P21 data:")
    p21:    dict[str, dict] = {}
    p21_po: dict[str, dict] = {}
    for path in p21_paths:
        by_inv, by_po = load_p21(path)
        overlap = set(by_inv) & set(p21)
        if overlap:
            print(f"  WARNING: {len(overlap)} invoice_no(s) appear in multiple files — "
                  f"keeping first occurrence")
        p21.update({k: v for k, v in by_inv.items() if k not in p21})
        p21_po.update({k: v for k, v in by_po.items() if k not in p21_po})
    print(f"  Total unique P21 records: {len(p21):,}")

    # ── Load statement rows ───────────────────────────────────────────────────
    print(f"Loading statements: {[p.name for p in stmt_paths]}")
    stmt_rows, _ = load_statements(stmt_paths)
    fieldnames_base = list(stmt_rows[0].keys()) if stmt_rows else []

    # ── Match against statement ───────────────────────────────────────────────
    matched = not_found = no_inv = amount_mismatch = 0
    new_rows = []

    new_cols   = ["p21_invoice_no_raw", "p21_invoice_no_normalized",
                  "p21_invoice_amount", "p21_remaining", "p21_voucher_type",
                  "p21_vendor_id", "discrepancy", "match_status"]
    fieldnames = fieldnames_base + new_cols

    for row in stmt_rows:
        raw_inv = str(row.get("invoice_number", ""))
        # BSN pattern: invoice_number starting with '21' is a batch ref —
        # use notes column as the actual invoice number for matching
        if raw_inv.startswith("21") and row.get("notes", "").strip():
            raw_inv = str(row.get("notes", "")).strip()
        inv_no = normalize(raw_inv)

        if not inv_no:
            row.update(p21_invoice_no_raw="", p21_invoice_no_normalized="",
                       p21_invoice_amount="", p21_remaining="", p21_voucher_type="",
                       p21_vendor_id="", discrepancy="", match_status="No invoice number")
            no_inv += 1

        elif inv_no in p21 or inv_no in p21_po:
            # Primary match by invoice_no; fallback to po_no (e.g. KidSole)
            rec         = p21.get(inv_no) or p21_po[inv_no]
            p21_raw_no  = str(rec.get("invoice_no", "")).strip()
            p21_inv_amt = to_decimal(rec.get("invoice_amount"))
            p21_paid    = to_decimal(rec.get("amount_paid"))
            p21_remain  = (p21_inv_amt - p21_paid) if (p21_inv_amt is not None and p21_paid is not None) else None
            stmt_bal    = to_decimal(row.get("balance_amount"))
            stmt_inv    = to_decimal(row.get("invoice_amount"))

            row["p21_invoice_no_raw"]        = p21_raw_no
            row["p21_invoice_no_normalized"] = normalize(p21_raw_no)
            row["p21_invoice_amount"]        = str(p21_inv_amt) if p21_inv_amt is not None else ""
            row["p21_remaining"]             = str(p21_remain)  if p21_remain  is not None else ""
            row["p21_voucher_type"]          = rec.get("voucher_type", "")
            row["p21_vendor_id"]             = str(rec.get("vendor_id", ""))

            if p21_remain is not None and stmt_bal is not None and abs(p21_remain - stmt_bal) < Decimal("0.01"):
                row["discrepancy"]  = "0.00"
                row["match_status"] = "Matched (remaining)"
                matched += 1
            elif p21_inv_amt is not None and stmt_bal is not None and abs(p21_inv_amt - stmt_bal) < Decimal("0.01"):
                row["discrepancy"]  = "0.00"
                row["match_status"] = "Matched"
                matched += 1
            elif p21_inv_amt is not None and stmt_inv is not None and abs(p21_inv_amt - stmt_inv) < Decimal("0.01"):
                disc = (p21_inv_amt - stmt_bal) if stmt_bal is not None else None
                row["discrepancy"]  = str(disc) if disc is not None else ""
                row["match_status"] = "Partial payment"
                amount_mismatch += 1
            else:
                disc = (p21_inv_amt - stmt_bal) if (p21_inv_amt is not None and stmt_bal is not None) else None
                row["discrepancy"]  = str(disc) if disc is not None else ""
                row["match_status"] = "Amount mismatch"
                amount_mismatch += 1

        else:
            row.update(p21_invoice_no_raw="", p21_invoice_no_normalized="",
                       p21_invoice_amount="", p21_remaining="", p21_voucher_type="",
                       p21_vendor_id="", discrepancy="", match_status="Not in P21")
            not_found += 1

        new_rows.append(row)

    # ── Write output ──────────────────────────────────────────────────────────
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    total = len(new_rows)
    print(f"\nResults ({total} statement lines):")
    print(f"  Matched                : {matched}  ({matched/total*100:.1f}%)")
    print(f"  Partial payment        : {sum(1 for r in new_rows if r['match_status']=='Partial payment')}")
    print(f"  Amount mismatch        : {sum(1 for r in new_rows if r['match_status']=='Amount mismatch')}")
    print(f"  Not in P21             : {not_found}")
    print(f"  No invoice number      : {no_inv}")
    print(f"\nOutput: {output_path}")

    non_matched = [r for r in new_rows if r["match_status"] in ("Partial payment", "Amount mismatch")]
    if non_matched:
        print("\nPartial payments / mismatches:")
        for row in non_matched:
            print(f"  inv={row['invoice_number']}  type={row['transaction_type']}"
                  f"  stmt_bal={row['balance_amount']}  stmt_inv={row['invoice_amount']}"
                  f"  p21_inv={row['p21_invoice_amount']}  p21_rem={row['p21_remaining']}"
                  f"  status={row['match_status']}")


if __name__ == "__main__":
    main()
