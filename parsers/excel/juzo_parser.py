from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Julius Zorn (Juzo)"


class JuzoExcelParser(BaseParser):
    """
    Row 6 (index 5): column headers
      Invoice(0), Invoice Date(1), Type(2), Balance-Local(3),
      Customer Purchase Order(4), Due Date(5), Ageing(6)
    Data from row 7 (index 6).
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        statement_date = self._extract_statement_date(rows)
        lines = []

        for row in rows[6:]:  # data from index 6 (row 7)
            if not row or not row[0]:
                continue
            inv_no = str(row[0]).strip()
            if not inv_no:
                continue

            # Use a parseable date in column 1 as the data-row indicator so that
            # invoice numbers like "_CR00005" (non-digit prefix) are not skipped.
            inv_date = parse_date(str(row[1]).strip()) if row[1] else None
            if inv_date is None:
                continue

            type_val = str(row[2]).strip().upper() if len(row) > 2 and row[2] else "INV"
            if type_val == "C/N":
                tx_type = "Credit Memo"
            else:
                tx_type = "Invoice"

            balance = parse_decimal(row[3] if len(row) > 3 else None)
            po_raw = str(row[4]).strip() if len(row) > 4 and row[4] else None
            due_date = parse_date(str(row[5]).strip()) if len(row) > 5 and row[5] else None

            # For Invoices strip "prefix:" notation to get the plain PO number.
            # For Credit Memos keep the full value (e.g. "RMA: 12345") as-is.
            if po_raw and ":" in po_raw and tx_type != "Credit Memo":
                po_raw = po_raw.split(":")[-1].strip()

            po_number, notes = assign_po(po_raw, tx_type)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=balance,   # single value column
                balance_amount=balance,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=None)

    def _extract_statement_date(self, rows):
        for row in rows[:6]:
            if not row:
                continue
            for cell in row:
                if cell and "/" in str(cell) and ":" in str(cell):
                    # Looks like a datetime string
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(str(cell).strip()[:10], "%m/%d/%Y")
                        return dt.date()
                    except ValueError:
                        pass
        return None
