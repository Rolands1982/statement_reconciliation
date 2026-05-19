from __future__ import annotations
import re
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal

_VENDOR_FALLBACK = "Burten Distribution"


def _vendor_from_filename(stem: str) -> str:
    """Extract vendor name from filename stem: text after the last '_', else fallback."""
    if "_" in stem:
        return stem.rsplit("_", 1)[-1].strip()
    return _VENDOR_FALLBACK

# Data row: inv_date  inv_no  inv_amount  Terms N  due_date  payment  due  running  [aging_days]
_LINE_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4})\s+"      # invoice date
    r"(\d+)\s+"                           # invoice number
    r"([\d,]+\.\d{2})\s+"                # invoice amount
    r"\S+\s+\d+\s+"                      # terms (e.g. "Net 30")
    r"(\d{1,2}/\d{1,2}/\d{4})\s+"        # due date
    r"([\d,]+\.\d{2})\s+"                # payment / return
    r"([\d,]+\.\d{2})\s+"                # balance due
    r"([\d,]+\.\d{2})"                   # running statement total
    r"(?:\s+\d+)?$"                       # optional aging days
)
_STMT_DATE_RE = re.compile(r"Statement Ended:\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
_TOTAL_RE     = re.compile(r"Total Statement Amount:\s+([\d,]+\.\d{2})", re.IGNORECASE)


class BurtenParser(BaseParser):
    """
    Burten Distribution customer statement PDF.
    Columns: Invoice Date | Invoice | Invoice Amount | Terms | Due Date |
             Payment/Return | Due | Statement Due | Aging Days (optional)
    """

    def parse(self) -> ParseResult:
        vendor = _vendor_from_filename(self.filepath.stem)
        lines_out = []
        statement_date = None
        file_total = None

        with pdfplumber.open(self.filepath) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        m = _STMT_DATE_RE.search(full_text)
        if m:
            statement_date = parse_date(m.group(1))

        m = _TOTAL_RE.search(full_text)
        if m:
            file_total = parse_decimal(m.group(1))

        seen: set[str] = set()
        for line in full_text.split("\n"):
            line = line.strip()
            m = _LINE_RE.match(line)
            if not m:
                continue
            inv_date_s, inv_no, inv_amt_s, due_date_s, _payment_s, balance_s, _running_s = m.groups()

            if inv_no in seen:
                continue
            seen.add(inv_no)

            lines_out.append(StatementLine(
                source_file=self.filename,
                vendor_name=vendor,
                statement_date=statement_date,
                invoice_number=inv_no,
                invoice_date=parse_date(inv_date_s),
                due_date=parse_date(due_date_s),
                po_number=None,
                invoice_amount=parse_decimal(inv_amt_s),
                balance_amount=parse_decimal(balance_s),
                transaction_type="Invoice",
                notes=None,
            ))

        return ParseResult(lines=lines_out, file_total=file_total)
