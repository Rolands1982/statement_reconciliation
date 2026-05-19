from __future__ import annotations
from decimal import Decimal
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Aspen Medical Products"


class AspenParser(BaseParser):
    """
    Layout: rows 1-10 header block, row 11 column headers, data from row 12.
    Columns (1-based): InvoiceDate(1), InvoiceNo(2), OrderNo(3), CustomerPO(4),
                       InvoiceAmount(5), Balance(6), DueDate(7), DaysOverdue(8), Notes(9)
    Net Open Balance in row 1 col 12.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        file_total = self._extract_total(rows)
        statement_date = self._extract_statement_date(rows)
        lines = []

        for row in rows[11:]:  # data starts at row index 11 (row 12)
            if not row or not row[0]:
                continue
            inv_date = parse_date(str(row[0]).strip())
            if inv_date is None:
                continue  # skip non-data rows
            inv_no = str(row[1]).strip() if row[1] else ""
            if not inv_no:
                continue
            po_raw = str(row[3]).strip() if len(row) > 3 and row[3] else None
            inv_amt = parse_decimal(row[4] if len(row) > 4 else None)
            balance = parse_decimal(row[5] if len(row) > 5 else None)
            due_date = parse_date(str(row[6]).strip()) if len(row) > 6 and row[6] else None
            notes_val = str(row[8]).strip() if len(row) > 8 and row[8] else None

            # Determine transaction type from balance sign or invoice amount sign
            if inv_amt is not None and inv_amt < 0:
                tx_type = "Credit Memo"
            elif balance is not None and balance < 0:
                tx_type = "Credit Memo"
            else:
                tx_type = "Invoice"

            po_number, notes = assign_po(po_raw, tx_type, notes_val)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=inv_amt,
                balance_amount=balance,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)

    def _extract_total(self, rows):
        # Row 1 (index 0): "Net Open Balance:" in col 11, value in col 12 (index 11/12 -> 0-based 10/11)
        for row in rows[:10]:
            if not row:
                continue
            for i, cell in enumerate(row):
                if cell and "Net Open Balance" in str(cell):
                    val = row[i + 1] if i + 1 < len(row) else None
                    return parse_decimal(val)
        return None

    def _extract_statement_date(self, rows):
        for row in rows[:12]:
            if not row:
                continue
            for i, cell in enumerate(row):
                if cell and "Statement Date" in str(cell):
                    val = row[i + 1] if i + 1 < len(row) else None
                    return parse_date(str(val).strip()) if val else None
        return None
