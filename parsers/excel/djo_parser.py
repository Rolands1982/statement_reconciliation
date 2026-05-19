from __future__ import annotations
import openpyxl
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "DJO Global"


class DjoParser(BaseParser):
    """
    Multi-sheet workbook, one sheet per customer account.
    Each sheet row 1 (index 0): headers
      Document Type(0), Document Number(1), Document Date(2), Due Date(3),
      Amount Due(4), Original Amount(5), Payment Terms(6), Customer Reference(7),
      Days Late(8), Purchase Order(9)
    Data from row 2 (index 1) on each sheet.
    """

    def parse(self) -> ParseResult:
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        lines = []
        file_total = None

        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            # Verify header
            header = [str(c).strip().upper() if c else "" for c in rows[0]]
            if "DOCUMENT NUMBER" not in header and "DOCUMENT TYPE" not in header:
                continue

            # Extract customer number from sheet name (e.g. "333324 - Statement" → "333324")
            customer_no = ws.title.split("-")[0].strip()

            for row in rows[1:]:
                if not row or not row[0]:
                    continue
                doc_type = str(row[0]).strip()
                if not doc_type or doc_type.upper() in ("DOCUMENT TYPE", "TOTAL"):
                    if "total" in doc_type.lower():
                        file_total = parse_decimal(row[4] if len(row) > 4 else None)
                    continue

                doc_no = str(row[1]).strip() if row[1] else ""
                if not doc_no:
                    continue

                inv_date = parse_date(str(row[2]).strip()) if row[2] else None
                due_date = parse_date(str(row[3]).strip()) if len(row) > 3 and row[3] else None
                amount_due = parse_decimal(row[4] if len(row) > 4 else None)
                orig_amount = parse_decimal(row[5] if len(row) > 5 else None)
                po_raw = str(row[9]).strip() if len(row) > 9 and row[9] else None

                d_type_up = doc_type.upper()
                if "CREDIT" in d_type_up:
                    tx_type = "Credit Memo"
                elif "PAYMENT" in d_type_up:
                    tx_type = "Payment"
                else:
                    tx_type = "Invoice"

                po_number, notes = assign_po(po_raw, tx_type, f"CustomerNo: {customer_no}")
                lines.append(StatementLine(
                    source_file=self.filename,
                    vendor_name=VENDOR,
                    statement_date=None,
                    invoice_number=doc_no,
                    invoice_date=inv_date,
                    due_date=due_date,
                    po_number=po_number,
                    invoice_amount=orig_amount,
                    balance_amount=amount_due,
                    transaction_type=tx_type,
                    notes=notes,
                ))

        wb.close()
        return ParseResult(lines=lines, file_total=file_total)
