from __future__ import annotations
import re
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal

VENDOR = "Kinetic Research"

# Transaction line: Date  Type #Ref.  desc...  Amount  Balance
_TXN_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+"
    r"(INV|CREDMEM|PMT)\s*#?(\S+)\."
    r"(.*?)"
    r"(-?[\d,]+\.\d{2})\s+"
    r"(-?[\d,]+\.\d{2})\s*$"
)
# Due date embedded in description: "Due 02/01/2026"
_DUE_RE = re.compile(r"Due\s+(\d{2}/\d{2}/\d{4})")
# Orig amount: "Orig. Amount $696.50"
_ORIG_RE = re.compile(r"Orig\.\s+Amount\s+\$?([\d,]+\.\d{2})")
# Text after "Orig. Amount $X.XX." (patient name/code that spills onto the same line)
_AFTER_ORIG_RE = re.compile(r"Orig\.\s+Amount\s+\$?[\d,]+\.\d{2}\.\s*(.*)")
_STMT_DATE_RE = re.compile(r"Date\b[^\d]*(\d{1,2}/\d{1,2}/\d{4})", re.MULTILINE)
_TOTAL_RE = re.compile(r"Amount Due\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)

# Patterns that disqualify a line from being a patient-name continuation
_NOT_CONTINUATION = re.compile(
    r"^\d{2}/\d{2}/\d{4}"          # another transaction date
    r"|^\d"                          # line starts with a digit (footer amounts)
    r"|DAYS\s+PAST"                  # aging bucket headers
    r"|^CURRENT\b"                   # "CURRENT Amount Due" row
    r"|^DUE\s"                       # "DUE DUE DUE..." row
    r"|^Date\b",                     # header repeat
    re.IGNORECASE,
)


def _is_continuation(line: str) -> bool:
    """Return True if *line* looks like a patient-name/reference continuation."""
    s = line.strip()
    return bool(s) and not _NOT_CONTINUATION.search(s)


class KineticParser(BaseParser):

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None

        with pdfplumber.open(self.filepath) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        # Statement date
        m = _STMT_DATE_RE.search(full_text)
        if m:
            statement_date = parse_date(m.group(1))

        m = _TOTAL_RE.search(full_text)
        if m:
            file_total = parse_decimal(m.group(1))

        text_lines = full_text.split("\n")
        i = 0
        while i < len(text_lines):
            line = text_lines[i].strip()
            m = _TXN_RE.match(line)
            if not m:
                i += 1
                continue

            txn_date_s, txn_type, ref_no, desc, amount_s, _balance_s = m.groups()

            # Look ahead for a patient-name / reference continuation line
            continuation = ""
            if i + 1 < len(text_lines) and _is_continuation(text_lines[i + 1]):
                continuation = text_lines[i + 1].strip()

            due_date = None
            dm = _DUE_RE.search(desc)
            if dm:
                due_date = parse_date(dm.group(1))

            orig_amount = None
            om = _ORIG_RE.search(desc)
            if om:
                orig_amount = parse_decimal(om.group(1))

            amount = parse_decimal(amount_s)
            tx_type = {"INV": "Invoice", "CREDMEM": "Credit Memo", "PMT": "Payment"}.get(
                txn_type, "Invoice"
            )

            # Build notes
            notes: str | None = None
            if txn_type == "INV":
                # Collect any text that appears after "Orig. Amount $X.XX." on the same line
                am = _AFTER_ORIG_RE.search(desc)
                inline_extra = am.group(1).strip() if am else ""
                combined = " ".join(filter(None, [inline_extra, continuation])).strip()
                notes = combined or None
            elif txn_type == "CREDMEM":
                # Patient name is in desc (between CREDMEM #NUM. and the amounts)
                combined = " ".join(filter(None, [desc.strip(), continuation])).strip()
                notes = combined or None

            lines_out.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=statement_date,
                invoice_number=ref_no,
                invoice_date=parse_date(txn_date_s),
                due_date=due_date,
                po_number=None,
                invoice_amount=orig_amount or amount,
                balance_amount=amount,
                transaction_type=tx_type,
                notes=notes,
            ))

            i += 1

        return ParseResult(lines=lines_out, file_total=file_total)
