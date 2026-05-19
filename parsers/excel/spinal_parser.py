from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Spinal Technology"


class SpinalParser(BaseParser):
    """
    Row 1: headers by name — Cust ID, Cust Name, Inv #, PO #, Inv Date, Due Date, Total
    Data from row 2. Total column = open balance.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            return ParseResult()

        # Map column names to indices from header row
        header = [str(c).strip() if c else "" for c in rows[0]]
        col = {h.upper(): i for i, h in enumerate(header)}

        def idx(key): return col.get(key.upper())

        lines = []
        file_total = None

        for row in rows[1:]:
            if not row:
                continue
            inv_no_idx = idx("INV #") or idx("INV#") or idx("INVOICE #")
            if inv_no_idx is None:
                continue
            inv_no = str(row[inv_no_idx]).strip() if row[inv_no_idx] else ""
            if not inv_no or inv_no.upper() in ("", "NONE", "TOTAL"):
                if "total" in str(row[0] or "").lower():
                    tot_idx = idx("TOTAL")
                    if tot_idx is not None:
                        file_total = parse_decimal(row[tot_idx])
                continue

            po_idx = idx("PO #") or idx("PO#")
            po_raw = str(row[po_idx]).strip() if po_idx is not None and row[po_idx] else None

            inv_date_idx = idx("INV DATE") or idx("INVOICE DATE")
            inv_date = parse_date(str(row[inv_date_idx]).strip()) if inv_date_idx is not None and row[inv_date_idx] else None

            due_idx = idx("DUE DATE")
            due_date = parse_date(str(row[due_idx]).strip()) if due_idx is not None and row[due_idx] else None

            tot_idx = idx("TOTAL") or idx(" TOTAL ")
            balance = parse_decimal(row[tot_idx]) if tot_idx is not None and row[tot_idx] else None

            tx_type = "Credit Memo" if (balance is not None and balance < 0) else "Invoice"

            po_number, notes = assign_po(po_raw, tx_type)
            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=None,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=balance,   # single value column
                balance_amount=balance,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=file_total)
