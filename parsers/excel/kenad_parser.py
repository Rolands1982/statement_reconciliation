from __future__ import annotations
from datetime import timedelta
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Kenad SG Medical"


class KenadParser(BaseParser):
    """
    OCR scan output. Fixed column positions (1-based → 0-based):
      Doc#(0), Date(1), Type(5), PO(8), Amount(15)
    Footer row containing "TOTAL DUE" has the file total.
    Statement date in row 0.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        file_total = None
        statement_date = None
        lines = []

        for row in rows:
            if not row:
                continue
            row_text = " ".join(str(c) for c in row if c)

            # Header row with statement date
            if statement_date is None and "STATEMENT" in row_text.upper():
                for cell in row:
                    if cell and "/" in str(cell):
                        statement_date = parse_date(str(cell).strip())
                        if statement_date:
                            break

            # Total row
            if "TOTAL DUE" in row_text.upper():
                # Amount is the last non-empty cell
                for cell in reversed(row):
                    amt = parse_decimal(cell)
                    if amt is not None:
                        file_total = amt
                        break
                continue

            # Skip rows without a numeric doc number in position 0
            doc_no = str(row[0]).strip() if row[0] else ""
            if not doc_no or not doc_no.isdigit():
                continue

            date_val = str(row[1]).strip() if len(row) > 1 and row[1] else None
            inv_date = parse_date(date_val)
            if inv_date is None:
                continue

            type_val = str(row[5]).strip().upper() if len(row) > 5 and row[5] else "INVOICE"
            if "CREDIT" in type_val:
                tx_type = "Credit Memo"
            else:
                tx_type = "Invoice"

            po_raw = str(row[8]).strip() if len(row) > 8 and row[8] else None
            # PO field may look like "PO:2852216" — strip prefix
            if po_raw and ":" in po_raw:
                po_raw = po_raw.split(":")[-1].strip()

            amount = parse_decimal(row[15]) if len(row) > 15 and row[15] else None

            po_number, notes = assign_po(po_raw, tx_type)
            due_date = inv_date + timedelta(days=30) if inv_date else None
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=doc_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=amount,
                balance_amount=amount,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)
