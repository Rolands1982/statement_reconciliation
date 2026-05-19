from __future__ import annotations
import re
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "JMS Plastics"


class JmsParser(BaseParser):
    """
    Row 2: column headers (Customer/Invoice No, Invoice Date, Due Date, Balance, ...)
    Data rows: col1=PO#, col2=Invoice#, col3=InvoiceDate, col4=DueDate, col5=Balance(open)
    No original invoice amount column — single value copied to both fields.
    Run date in last rows: "Run Date: 1/22/2026"
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        lines = []
        file_total = None
        statement_date = None

        # Extract run date from last rows
        for row in rows[-5:]:
            if row and row[0] and "Run Date" in str(row[0]):
                m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", str(row[0]))
                if m:
                    statement_date = parse_date(m.group(1))
                break

        for row in rows[4:]:  # data from row 5 (index 4)
            if not row or not row[0]:
                continue
            po_raw = str(row[0]).strip()
            inv_no_raw = str(row[1]).strip() if len(row) > 1 and row[1] else ""

            if not inv_no_raw or not inv_no_raw[0].isdigit():
                if "total" in po_raw.lower():
                    # Total row layout: col index 2 has the sum
                    file_total = parse_decimal(row[2] if len(row) > 2 else None)
                continue

            inv_date = parse_date(row[2] if len(row) > 2 else None)
            due_date = parse_date(row[3] if len(row) > 3 else None)
            balance = parse_decimal(row[4] if len(row) > 4 else None)

            tx_type = "Credit Memo" if (balance is not None and balance < 0) else "Invoice"

            po_number, notes = assign_po(po_raw, tx_type)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=inv_no_raw,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=balance,   # single value column
                balance_amount=balance,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)
