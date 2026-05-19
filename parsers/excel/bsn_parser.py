from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "BSN Medical"


class BsnParser(BaseParser):
    """
    Row 1 (index 0): column headers
      Document number(0), Document Date(1), Net due date(2), Net due date symbol(3),
      Amount in local currency(4), Local Currency(5), Arrears after net due date(6),
      Dunning level(7), Text(8), Reference key 3(9)=PO, Account(10)
    Data from row 2 (index 1).
    Positive amount = Invoice, negative = Credit/Payment.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        lines = []

        for row in rows[1:]:  # skip header row
            if not row or not row[0]:
                continue
            doc_no = str(row[0]).strip()
            if not doc_no or not doc_no[0].isdigit():
                continue

            inv_date = parse_date(str(row[1]).strip()) if row[1] else None
            due_date = parse_date(str(row[2]).strip()) if len(row) > 2 and row[2] else None
            amount = parse_decimal(row[4] if len(row) > 4 else None)
            text_val = str(row[8]).strip() if len(row) > 8 and row[8] else None
            po_raw = str(row[9]).strip() if len(row) > 9 and row[9] else None

            if amount is not None and amount < 0:
                tx_type = "Credit Memo"
            else:
                tx_type = "Invoice"

            po_number, notes = assign_po(po_raw, tx_type, text_val)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=None,
                invoice_number=doc_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=amount,
                balance_amount=amount,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=None)
