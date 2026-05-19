from __future__ import annotations
import re
from datetime import timedelta
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po

VENDOR = "Langer Biomechanics"

_TOTAL_RE = re.compile(r"Total\s+Due[:\s]+\$?([\d,]+\.\d{2})", re.IGNORECASE)
_DATE_RE = re.compile(r"Statement\s+Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)


class LangerParser(BaseParser):
    """
    Table columns: Ln. | Document Date | Document # | Code | Patient/Reference | Amount | Balance
    Code: SLS=Invoice, CR=Credit, RTN=Return, PMT=Payment
    Total Due in header.
    """

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None

        with pdfplumber.open(self.filepath) as pdf:
            full_text = ""
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

            # Extract statement date and total from text
            m = _DATE_RE.search(full_text)
            if m:
                statement_date = parse_date(m.group(1))
            m = _TOTAL_RE.search(full_text)
            if m:
                file_total = parse_decimal(m.group(1))

            # Use table extraction — pdfplumber finds rows cleanly
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or not row[0]:
                            continue
                        # Row: [line_no, date, doc_no, code, patient, '', amount, balance]
                        line_no = str(row[0]).strip()
                        if not line_no.isdigit():
                            continue
                        doc_no = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                        code = str(row[3]).strip().upper() if len(row) > 3 and row[3] else ""
                        inv_date = parse_date(str(row[1]).strip()) if row[1] else None
                        # Amount is normally at index 6; wire transfer rows shift it to index 4
                        amount = parse_decimal(row[6]) if len(row) > 6 and row[6] else None
                        is_wire = "WIRE" in doc_no.upper()
                        if amount is None:
                            raw4 = parse_decimal(row[4]) if len(row) > 4 and row[4] else None
                            # Only use index-4 fallback for wire/payment rows; for SLS rows index 4 is patient name
                            if is_wire or code in ("PMT",):
                                amount = raw4
                        patient_raw = str(row[4]).strip() if len(row) > 4 and row[4] and not is_wire else None

                        # Wire/payment rows are historical payments against prior statements;
                        # they don't contribute to "Total Due" so exclude them.
                        if is_wire or code == "PMT":
                            continue

                        code_map = {"SLS": "Invoice", "CR": "Credit Memo", "RTN": "Credit Memo"}
                        tx_type = code_map.get(code, "Invoice")

                        due_date = inv_date + timedelta(days=30) if inv_date else None
                        notes = f"Patient: {patient_raw}" if patient_raw else None

                        lines_out.append(StatementLine(
                            source_file=self.filename,
                            vendor_name=VENDOR,
                            statement_date=statement_date,
                            invoice_number=doc_no,
                            invoice_date=inv_date,
                            due_date=due_date,
                            po_number=None,
                            invoice_amount=amount,
                            balance_amount=amount,
                            transaction_type=tx_type,
                            notes=notes,
                        ))

        return ParseResult(lines=lines_out, file_total=file_total)
