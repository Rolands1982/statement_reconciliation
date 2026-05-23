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
    return inv.strip().lstrip("0").upper()


def load_p21(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("value", data) if isinstance(data, dict) else data
    p21 = {}
    dupes = 0
    for rec in records:
        inv_no = normalize(str(rec.get("invoice_no", "")))
        if not inv_no:
            continue
        if inv_no in p21:
            dupes += 1
        else:
            p21[inv_no] = rec
    print(f"  {path.name}: {len(records):,} records, {len(p21):,} unique invoice_no"
          + (f", {dupes} duplicates kept first" if dupes else ""))
    return p21


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    statement_path = Path(sys.argv[1])
    p21_paths      = [Path(p) for p in sys.argv[2:]]

    output_path = statement_path.parent / (statement_path.stem + "_reconciled.csv")

    # ── Load and merge all P21 files ─────────────────────────────────────────
    print("Loading P21 data:")
    p21: dict[str, dict] = {}
    for path in p21_paths:
        chunk = load_p21(path)
        overlap = set(chunk) & set(p21)
        if overlap:
            print(f"  WARNING: {len(overlap)} invoice_no(s) appear in multiple files — "
                  f"keeping first occurrence")
        p21.update({k: v for k, v in chunk.items() if k not in p21})
    print(f"  Total unique P21 records: {len(p21):,}")

    # ── Match against statement ───────────────────────────────────────────────
    matched = not_found = no_inv = amount_mismatch = 0
    new_rows = []

    with statement_path.open(newline="", encoding="utf-8") as f:
        reader    = csv.DictReader(f)
        new_cols  = ["p21_invoice_amount", "p21_remaining", "p21_voucher_type",
                     "p21_vendor_id", "discrepancy", "match_status"]
        fieldnames = list(reader.fieldnames) + new_cols

        for row in reader:
            inv_no = normalize(str(row.get("invoice_number", "")))

            if not inv_no:
                row.update(p21_invoice_amount="", p21_remaining="", p21_voucher_type="",
                           p21_vendor_id="", discrepancy="", match_status="No invoice number")
                no_inv += 1

            elif inv_no in p21:
                rec         = p21[inv_no]
                p21_inv_amt = to_decimal(rec.get("invoice_amount"))
                p21_paid    = to_decimal(rec.get("amount_paid"))
                p21_remain  = (p21_inv_amt - p21_paid) if (p21_inv_amt is not None and p21_paid is not None) else None
                stmt_bal    = to_decimal(row.get("balance_amount"))
                stmt_inv    = to_decimal(row.get("invoice_amount"))

                row["p21_invoice_amount"] = str(p21_inv_amt) if p21_inv_amt is not None else ""
                row["p21_remaining"]      = str(p21_remain)  if p21_remain  is not None else ""
                row["p21_voucher_type"]   = rec.get("voucher_type", "")
                row["p21_vendor_id"]      = str(rec.get("vendor_id", ""))

                # Match priority:
                # 1. balance_amount == p21_remaining  → "Matched (remaining)"
                # 2. balance_amount == p21_invoice_amount → "Matched"
                # 3. invoice_amount (stmt) == p21_invoice_amount → "Partial payment"
                # 4. otherwise → "Amount mismatch"
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
                row.update(p21_invoice_amount="", p21_remaining="", p21_voucher_type="",
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
