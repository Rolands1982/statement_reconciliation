from __future__ import annotations
import re
from decimal import Decimal
import pdfplumber
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, validate_po

# Payer code → vendor name mapping
# Payer code appears on the header line: "04/30/26 0050229635 KCAS40000 ..."
_PAYER_VENDOR: dict[str, str] = {
    "KCAS40000": "Thuasne",
    "K10011100": "Knit Rite",
}
_DEFAULT_VENDOR = "Thuasne"

# Match the invoice/credit data pattern anchored at the end of the line.
# Does NOT require "Invoice"/"Credit" as an anchor — payer name text can overlap
# with the type word (e.g. "EXPERCIredit" or "SAInvoice"). Transaction type is
# inferred from amount sign: negative → Credit Memo, positive → Invoice.
_LINE_RE = re.compile(
    r"(\S+)\s+"                         # invoice_no
    r"(\d{2}/\d{2}/\d{2,4})\s+"        # inv_date
    r"(\d{2}/\d{2}/\d{2,4})\s+"        # due_date
    r"USD\s+"
    r"(-?[\d\s]+\.\d{2})\s*$"          # amount
)
_STMT_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{2,4})\s+\d+")
_PAYER_CODE_RE = re.compile(r"\d{2}/\d{2}/\d{2,4}\s+\S+\s+(\S+)\s+Thuasne")
_TOTAL_RE = re.compile(r"^Total\s+([\d\s]+\.\d{2})\s*$")


def _clean_amount(s: str) -> Decimal | None:
    return parse_decimal(s.replace(" ", ""))


class ThuasneParser(BaseParser):

    def parse(self) -> ParseResult:
        lines_out = []
        statement_date = None
        file_total = None
        vendor_name = _DEFAULT_VENDOR
        seen: set[str] = set()  # deduplicate by invoice_no (PDF is duplex — pages repeat)

        with pdfplumber.open(self.filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue

                    # Payer code + statement date from header line:
                    # "04/30/26 0050229635 KCAS40000 Thuasne Accounting Hotline ..."
                    if statement_date is None:
                        m = _PAYER_CODE_RE.search(line)
                        if m:
                            payer_code = m.group(1)
                            vendor_name = _PAYER_VENDOR.get(payer_code, _DEFAULT_VENDOR)
                            statement_date = parse_date(line.split()[0])

                    # Grand total line (appears once on the last page)
                    m = _TOTAL_RE.match(line)
                    if m:
                        t = _clean_amount(m.group(1))
                        if t is not None and (file_total is None or t > file_total):
                            file_total = t
                        continue

                    # Invoice / Credit data — search anywhere in the line so that
                    # long payer names concatenated with "Invoice"/"Credit" still match.
                    # Type is inferred from amount sign (credits are always negative).
                    m = _LINE_RE.search(line)
                    if not m:
                        continue

                    inv_no, inv_date_s, due_date_s, amount_s = (
                        m.group(1), m.group(2), m.group(3), m.group(4)
                    )

                    if inv_no in seen:
                        continue  # skip duplicate (duplex PDF pages repeat content)
                    seen.add(inv_no)

                    amount = _clean_amount(amount_s.strip())
                    tx_type = "Credit Memo" if amount is not None and amount < 0 else "Invoice"

                    lines_out.append(StatementLine(
                        source_file=self.filename,
                        vendor_name=vendor_name,
                        statement_date=statement_date,
                        invoice_number=inv_no,
                        invoice_date=parse_date(inv_date_s),
                        due_date=parse_date(due_date_s),
                        po_number=None,
                        invoice_amount=amount,
                        balance_amount=amount,
                        transaction_type=tx_type,
                        notes=None,
                    ))

        return ParseResult(lines=lines_out, file_total=file_total)
