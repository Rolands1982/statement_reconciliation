from __future__ import annotations
import re
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po, assign_po

VENDOR = "Julius Zorn (Juzo)"

# Data line: InvoiceNo  InvDate  SalesOrder  PO/Ref  TransType  $Amount  $Balance
# Or payment line: (no inv no)  Date  type  $amount
_INV_RE = re.compile(
    r"^(\d{8})\s+"                          # invoice number (8 digits)
    r"(\d{2}/\d{2}/\d{4})\s+"              # invoice date
    r"(\S+)\s+"                              # sales order
    r"(\S+)\s+"                              # PO/reference
    r"(Invoice|Credit Note|Payment)\s+"     # type
    r"\$?([\d,]+\.\d{2})\s+"               # amount
    r"\$?([\d,]+\.\d{2})"                  # balance
)
_DATE_RE = re.compile(r"Date:\s+(\d{2}/\d{2}/\d{4})")
_TOTAL_RE = re.compile(r"Total\s+Due[:\s]+\$?([\d,]+\.\d{2})", re.IGNORECASE)


class JuzoPdfParser(BaseParser):

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None

        with pdfplumber.open(self.filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue

                    m = _DATE_RE.search(line)
                    if m and statement_date is None:
                        statement_date = parse_date(m.group(1))

                    m = _TOTAL_RE.search(line)
                    if m:
                        file_total = parse_decimal(m.group(1))
                        continue

                    m = _INV_RE.match(line)
                    if m:
                        inv_no, inv_date_s, _, po_ref, tx_raw, amount_s, balance_s = m.groups()
                        tx_map = {"Invoice": "Invoice", "Credit Note": "Credit Memo", "Payment": "Payment"}
                        tx_type = tx_map.get(tx_raw, "Invoice")
                        # po_ref may be an RMA or PO number
                        po_clean = po_ref.split(":")[-1] if ":" in po_ref else po_ref
                        po_number, notes = assign_po(po_clean, tx_type)
                        lines_out.append(StatementLine(
                            source_file=self.filename,
                            vendor_name=VENDOR,
                            statement_date=statement_date,
                            invoice_number=inv_no,
                            invoice_date=parse_date(inv_date_s),
                            due_date=None,
                            po_number=po_number,
                            invoice_amount=parse_decimal(amount_s),
                            balance_amount=parse_decimal(balance_s),
                            transaction_type=tx_type,
                            notes=notes,
                        ))

        return ParseResult(lines=lines_out, file_total=file_total)
