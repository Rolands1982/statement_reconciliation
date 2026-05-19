from __future__ import annotations
import re
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po

VENDOR = "MD Orthopaedics"

# Data line: 30NET  2/23/2026  Invoice 275221  $100.00  $100.00  $100.00
_DATA_RE = re.compile(
    r"^(\w+)\s+"                        # terms
    r"(\d{1,2}/\d{1,2}/\d{4})\s+"      # invoice date
    r"(Invoice|Credit)\s+(\d+)\s+"     # type + number
    r"\$?([\d,]+\.?\d*)\s+"            # original balance
    r"(-?\$?[\d,]+\.?\d*)\s*"          # invoice balance (negative for credits)
)
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_STMT_DATE_RE = re.compile(rf"(\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}})", re.IGNORECASE)
_TOTAL_RE = re.compile(r"Amount Due\s+([\d,]+\.\d{2})", re.IGNORECASE)


class MdOrthoParser(BaseParser):

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None

        with pdfplumber.open(self.filepath) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # Statement date like "2 April 2026"
        m = _STMT_DATE_RE.search(full_text)
        if m:
            statement_date = parse_date(m.group(1))

        # Footer: "Amount Due" is a column header; value is last number on the following line
        # Pattern: "... Amount Due\n0.00 ... 17,537.15"
        m = re.search(r"Amount Due\s*\n[\d.,\s]+?([\d,]+\.\d{2})\s*$", full_text, re.MULTILINE)
        if m:
            file_total = parse_decimal(m.group(1))
        else:
            # Fallback: last dollar amount on a line that starts with digits (summary row)
            for line in reversed(full_text.split("\n")):
                nums = re.findall(r"([\d,]+\.\d{2})", line.strip())
                if len(nums) >= 5:  # summary row has many numbers
                    file_total = parse_decimal(nums[-1])
                    break

        for line in full_text.split("\n"):
            line = line.strip()
            m = _DATA_RE.match(line)
            if not m:
                continue
            terms, inv_date_s, tx_raw, inv_no, orig_s, bal_s = m.groups()
            tx_type = "Credit Memo" if tx_raw == "Credit" else "Invoice"

            # Due date = invoice date + 30 days for 30NET terms
            inv_date = parse_date(inv_date_s)
            due_date = None
            if inv_date and "30" in terms:
                from datetime import timedelta
                due_date = inv_date + timedelta(days=30)

            bal_clean = bal_s.replace("$", "")
            balance = parse_decimal(bal_clean)
            orig = parse_decimal(orig_s)

            lines_out.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=inv_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=None,
                invoice_amount=orig,
                balance_amount=balance,
                transaction_type=tx_type,
                notes=None,
            ))

        return ParseResult(lines=lines_out, file_total=file_total)
