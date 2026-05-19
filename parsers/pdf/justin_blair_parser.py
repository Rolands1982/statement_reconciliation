from __future__ import annotations
import re
from datetime import timedelta
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po

VENDOR = "Justin Blair & Co."

# Lines with an open balance have the full format:
#   InvoiceNo  TransDate  [AgingDate]  Type  Amount  AgeDays  OpenAmount  [InvoiceNo  OpenAmount]
# Paid lines only have:
#   InvoiceNo  TransDate  [AgingDate]  Type  Amount
# AgeDays + OpenAmount being present is what distinguishes open lines; AgingDate is optional/ignored.
# Due date is calculated as invoice date + 30 days (Net 30 terms).
_LINE_RE = re.compile(
    r"^(\d{6})\s+"                          # invoice number
    r"(\d{2}/\d{2}/\d{2})\s+"              # trans date (invoice date)
    r"(?:\d{2}/\d{2}/\d{2}\s+)?"           # aging date — optional, not captured
    r"(INV|PMT|CR|C/M)\s+"                 # type
    r"([\d,]+\.\d{2}-?)\s+"               # original amount
    r"(?:\d+\s+)?"                          # age days — absent when age=0
    r"([\d,]+\.\d{2}-?)"                   # open amount
)
_DATE_RE = re.compile(r"DATE\s+(\d{2}/\d{2}/\d{2})", re.IGNORECASE)
_TOTAL_RE = re.compile(r"TOTAL[^$\d]*([\d,]+\.\d{2})", re.IGNORECASE)


def _parse_jb_amount(s: str):
    """Justin Blair uses trailing '-' for negatives: '78.00-'"""
    s = s.strip()
    negative = s.endswith("-")
    val = parse_decimal(s.rstrip("-"))
    if val is not None and negative:
        val = -val
    return val


class JustinBlairParser(BaseParser):

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None
        seen_invoices: dict[str, StatementLine] = {}  # invoice_no → last open amount line

        with pdfplumber.open(self.filepath) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        m = _DATE_RE.search(full_text)
        if m:
            statement_date = parse_date(m.group(1))

        m = _TOTAL_RE.search(full_text)
        if m:
            file_total = parse_decimal(m.group(1))

        for line in full_text.split("\n"):
            line = line.strip()
            m = _LINE_RE.match(line)
            if not m:
                continue

            inv_no, txn_date_s, txn_type, amount_s, open_amount_s = m.groups()

            inv_amount = _parse_jb_amount(amount_s)
            open_amount = _parse_jb_amount(open_amount_s)
            inv_date = parse_date(txn_date_s)
            due_date = inv_date + timedelta(days=30) if inv_date else None

            type_map = {"INV": "Invoice", "PMT": "Payment", "CR": "Credit Memo", "C/M": "Credit Memo"}
            tx_type = type_map.get(txn_type, "Invoice")

            line_obj = StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=None,
                invoice_amount=inv_amount,
                balance_amount=open_amount,
                transaction_type=tx_type,
                notes=None,
            )
            seen_invoices[inv_no] = line_obj

        lines_out = list(seen_invoices.values())
        return ParseResult(lines=lines_out, file_total=file_total)
