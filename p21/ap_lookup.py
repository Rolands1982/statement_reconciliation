"""
AP invoice lookup against P21's apinv_hdr table.

Confirmed table/column mapping (verified via Postman against live instance):
  Table  : apinv_hdr
  vendor_id      → integer column (filter WITHOUT quotes)
  invoice_no     → string
  invoice_amount → decimal (original invoice amount; negative = credit/debit memo)
  amount_paid    → decimal (what has been paid; None if not yet paid)
  voucher_type   → 'V' = invoice, 'D' = debit/credit memo
  reverse_flag   → 'Y' = voided/reversed (always excluded)
  invoice_date   → datetime (used as date range lower bound)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from p21.client import P21Client

AP_TABLE = "table/apinv_hdr"

_SELECT = [
    "invoice_no",
    "vendor_id",
    "invoice_amount",
    "amount_paid",
    "voucher_type",
    "reverse_flag",
    "invoice_date",
    "net_due_date",
    "paid_in_full",
    "po_no",
]


def _to_decimal(val) -> Decimal | None:
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


@dataclass
class ApRecord:
    invoice_no: str          # normalized (stripped, leading zeros removed, upper)
    invoice_no_raw: str      # original as stored in P21
    vendor_id: int
    invoice_amount: Decimal | None
    amount_paid: Decimal | None
    remaining: Decimal | None  # invoice_amount − amount_paid; None if either is absent
    voucher_type: str | None   # 'V' = invoice, 'D' = credit/debit memo
    paid_in_full: str | None   # 'Y' / 'N'
    invoice_date: str | None
    po_no: str | None
    raw: dict


def _normalize(inv: str) -> str:
    return inv.strip().lstrip("0").upper()


def _build_filter(vendor_id: int, min_date: date, invoice_no: str | None = None) -> str:
    """Build OData $filter expression for apinv_hdr."""
    date_str = min_date.strftime("%Y-%m-%dT00:00:00Z")
    parts = [
        f"vendor_id eq {vendor_id}",
        "reverse_flag ne 'Y'",
        f"invoice_date ge {date_str}",
    ]
    if invoice_no:
        parts.append(f"invoice_no eq '{invoice_no}'")
    return " and ".join(parts)


def fetch_ap_records(
    client: P21Client,
    vendor_id: str,
    min_invoice_date: date,
    invoice_no: str | None = None,
) -> list[ApRecord]:
    """
    Fetch AP voucher records from apinv_hdr for a single vendor.

    Args:
        client:           Authenticated P21Client
        vendor_id:        String from config (e.g. "100329") — cast to int internally
        min_invoice_date: Lower bound for invoice_date filter
                          (typically min invoice_date from the statement lines)
        invoice_no:       Optional — restricts to a single invoice (for testing)

    Returns:
        List of ApRecord, one per unique invoice_no.
        If the same invoice_no appears twice only the first is kept.
    """
    vid_int = int(vendor_id)
    filter_expr = _build_filter(vid_int, min_invoice_date, invoice_no)

    raw_records = client.odata_get(AP_TABLE, filter_expr, select=_SELECT)

    seen: set[str] = set()
    results: list[ApRecord] = []

    for rec in raw_records:
        raw_no  = str(rec.get("invoice_no") or "").strip()
        norm_no = _normalize(raw_no)
        if not norm_no or norm_no in seen:
            continue
        seen.add(norm_no)

        inv_amt  = _to_decimal(rec.get("invoice_amount"))
        paid_amt = _to_decimal(rec.get("amount_paid"))
        remaining = (inv_amt - paid_amt) if (inv_amt is not None and paid_amt is not None) else None

        results.append(ApRecord(
            invoice_no      = norm_no,
            invoice_no_raw  = raw_no,
            vendor_id       = vid_int,
            invoice_amount  = inv_amt,
            amount_paid     = paid_amt,
            remaining       = remaining,
            voucher_type    = rec.get("voucher_type"),
            paid_in_full    = rec.get("paid_in_full"),
            invoice_date    = str(rec.get("invoice_date") or "")[:10] or None,
            po_no           = str(rec.get("po_no") or "").strip() or None,
            raw             = rec,
        ))

    return results
