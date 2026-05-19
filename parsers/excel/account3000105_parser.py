from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, assign_po

_VENDOR_FALLBACK = "3000105"


def _vendor_from_filename(stem: str) -> str:
    """Extract vendor name from filename stem: text after the last '_', else fallback."""
    if "_" in stem:
        return stem.rsplit("_", 1)[-1].strip()
    return _VENDOR_FALLBACK


class Account3000105Parser(BaseParser):
    """
    Simple SAP-style open-items export.
    Row 0: headers — Account, Terms of Payment, Document Number,
                     Document Date, Net due date, Amount in local currency, Reference
    Data from row 1.  Last row has empty Document Number and holds the total.
    Vendor name is read from the filename stem (text after the last underscore).
    """

    def parse(self) -> ParseResult:
        vendor = _vendor_from_filename(self.filepath.stem)
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return ParseResult()

        # Resolve columns from header row
        header = [str(c).strip().upper() if c else "" for c in rows[0]]
        col = {h: i for i, h in enumerate(header)}

        doc_idx  = col.get("DOCUMENT NUMBER",         2)
        date_idx = col.get("DOCUMENT DATE",           3)
        due_idx  = col.get("NET DUE DATE",            4)
        amt_idx  = col.get("AMOUNT IN LOCAL CURRENCY", 5)
        ref_idx  = col.get("REFERENCE",               6)

        lines = []
        file_total = None

        for row in rows[1:]:
            if not row:
                continue

            doc_no = str(row[doc_idx]).strip() if len(row) > doc_idx and row[doc_idx] else ""

            # Empty document number = total / summary row
            if not doc_no:
                amt = parse_decimal(row[amt_idx] if len(row) > amt_idx else None)
                if amt is not None:
                    file_total = amt
                continue

            inv_date = parse_date(row[date_idx]) if len(row) > date_idx else None
            due_date = parse_date(row[due_idx])  if len(row) > due_idx  else None
            amount   = parse_decimal(row[amt_idx] if len(row) > amt_idx else None)
            po_raw   = str(row[ref_idx]).strip() if len(row) > ref_idx and row[ref_idx] else None

            po_number, notes = assign_po(po_raw, "Invoice")

            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=vendor,
                statement_date=None,
                invoice_number=doc_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=amount,
                balance_amount=amount,
                transaction_type="Invoice",
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)
