from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Kingsley"


class KingsleyParser(BaseParser):
    """
    QuickBooks export format. Data in even-indexed columns only (odd indices are spacers).
    Sheet "Sheet1", headers in row 1, customer name in row 2, data from row 3.
    Column positions vary by export version — resolved dynamically from the header row.
    Known columns: Type, Date, Num, P. O. #, Due Date, Aging, Open Balance.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)

        # Use Sheet1; skip informational sheets
        ws = None
        for sheet in wb.worksheets:
            if sheet.title.lower() == "sheet1":
                ws = sheet
                break
        if ws is None:
            ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        # Resolve column indices from header row (row index 0)
        col = {}
        if rows:
            for i, cell in enumerate(rows[0]):
                if cell:
                    col[str(cell).strip().upper()] = i

        type_idx    = col.get("TYPE",         4)
        date_idx    = col.get("DATE",         6)
        num_idx     = col.get("NUM",          8)
        po_idx      = col.get("P. O. #",     10)
        due_idx     = col.get("DUE DATE",    14)
        balance_idx = col.get("OPEN BALANCE", 20)

        lines = []
        file_total = None

        for row in rows[2:]:  # data from index 2 (row 3); row 1 = customer name
            if not row or len(row) <= type_idx or not row[type_idx]:
                continue
            type_val = str(row[type_idx]).strip()
            if not type_val or type_val.upper() in ("TYPE", "TOTAL"):
                if "total" in type_val.lower():
                    file_total = parse_decimal(row[balance_idx] if len(row) > balance_idx else None)
                continue

            inv_no = str(row[num_idx]).strip() if len(row) > num_idx and row[num_idx] else ""
            if not inv_no:
                continue

            inv_date = parse_date(str(row[date_idx]).strip()) if len(row) > date_idx and row[date_idx] else None
            due_date = parse_date(str(row[due_idx]).strip()) if len(row) > due_idx and row[due_idx] else None
            po_raw   = str(row[po_idx]).strip() if len(row) > po_idx and row[po_idx] else None
            balance  = parse_decimal(row[balance_idx] if len(row) > balance_idx else None)

            type_up = type_val.upper()
            if "CREDIT" in type_up:
                tx_type = "Credit Memo"
            elif "PAYMENT" in type_up:
                tx_type = "Payment"
            else:
                tx_type = "Invoice"

            po_number, notes = assign_po(po_raw, tx_type)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=None,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=balance,   # single value column (open balance)
                balance_amount=balance,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)
