from __future__ import annotations
from datetime import timedelta
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "KidSole"


class KidSoleParser(BaseParser):
    """
    PO/shipping list format. Row 1 headers:
      CASCADE PO#(0), KidSole Order#(1), Date Shipped(2), Tracking(3),
      Total Cost Due(4), Over 45 Days(5), Paid(6)
    Map: KidSole Order# → invoice_number, CASCADE PO# → po_number,
         ship date → invoice_date, Total Cost Due → balance_amount
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        lines = []

        for row in rows[1:]:  # skip header
            if not row or not row[0]:
                continue
            po_raw = str(row[0]).strip()
            if not po_raw or not po_raw[0].isdigit():
                continue

            kidsole_order = str(row[1]).strip() if len(row) > 1 and row[1] else ""
            ship_date = parse_date(str(row[2]).strip()) if len(row) > 2 and row[2] else None
            amount = parse_decimal(row[4] if len(row) > 4 else None)
            paid = str(row[6]).strip().upper() if len(row) > 6 and row[6] else "N"

            if paid == "Y":
                continue

            due_date = ship_date + timedelta(days=45) if ship_date else None
            po_number, notes = assign_po(po_raw, "Invoice")
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=None,
                invoice_number=kidsole_order,   # KidSole Order# matches P21 invoice_no
                invoice_date=ship_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=amount,
                balance_amount=amount,          # single value column
                transaction_type="Invoice",
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=None)
