from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

PO_PATTERN = re.compile(r'\b(2[6-9]\d{5})\b')  # 7-digit, 2600000–2999999

# Date patterns to try against a filename stem (American format mm/dd/yyyy preferred)
_FN_PATTERNS = [
    (re.compile(r'(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)'), "%Y%m%d"),   # yyyymmdd
    (re.compile(r'(20\d{2})[_\-](\d{2})[_\-](\d{2})'), "%Y%m%d"),      # yyyy_mm_dd
    (re.compile(r'(\d{2})\.(\d{2})\.(\d{2})(?!\d)'), "%m%d%y"),        # mm.dd.yy
]
_FN_MMDDYY = re.compile(r'(?<!\d)(\d{6})(?!\d)')   # bare 6-digit mmddyy


def parse_date_from_filename(filename: str) -> date | None:
    from datetime import datetime as _dt
    stem = Path(filename).stem
    for pattern, fmt in _FN_PATTERNS:
        m = pattern.search(stem)
        if m:
            joined = "".join(m.groups())
            try:
                return _dt.strptime(joined, fmt).date()
            except ValueError:
                continue
    # Bare 6-digit mmddyy — validate month/day before accepting
    for m in _FN_MMDDYY.finditer(stem):
        s = m.group(1)
        try:
            d = _dt.strptime(s, "%m%d%y").date()
            if 2000 <= d.year <= 2099:
                return d
        except ValueError:
            continue
    return None


def parse_date(value) -> date | None:
    from datetime import datetime as _dt
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, _dt):
        return value
    if isinstance(value, _dt):
        return value.date()
    value = str(value).strip()
    if not value or value.lower() in ("none", "nat", ""):
        return None
    # Try numeric Excel serial date (shouldn't reach here via openpyxl data_only, but safeguard)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y-%m-%d",
                "%d-%m-%Y", "%m-%d-%Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return _dt.strptime(value, fmt).date()
        except ValueError:
            continue
    # Handle datetime strings like "2025-12-05 00:00:00" or ISO 8601 "2025-12-05T00:00:00"
    if " " in value or "T" in value:
        normalised = value.replace("T", " ")
        try:
            return _dt.strptime(normalised, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            pass
        try:
            return _dt.strptime(normalised.split(" ")[0], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def parse_decimal(value) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("$", "").replace(" ", "")
    if s in ("", "-", "N/A"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def validate_po(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    m = PO_PATTERN.search(s)
    if m:
        n = int(m.group(1))
        if 2600000 <= n <= 3000000:
            return m.group(1)
    return None


def assign_po(
    po_raw: str | None,
    tx_type: str,
    existing_notes: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (po_number, notes).

    Credit Memos skip pattern validation — the field may hold an RMA or other
    reference number.  For all other types, non-matching values are moved to
    the notes column so the data isn't silently discarded.
    """
    if not po_raw:
        return None, existing_notes
    if tx_type == "Credit Memo":
        return po_raw, existing_notes
    validated = validate_po(po_raw)
    if validated:
        return validated, existing_notes
    note = f"PO: {po_raw}"
    combined = f"{existing_notes}; {note}" if existing_notes else note
    return None, combined


@dataclass
class StatementLine:
    source_file: str
    vendor_name: str
    statement_date: date | None
    invoice_number: str
    invoice_date: date | None
    due_date: date | None
    po_number: str | None
    invoice_amount: Decimal | None
    balance_amount: Decimal | None
    transaction_type: str            # 'Invoice' | 'Credit Memo' | 'Payment'
    notes: str | None

    def to_csv_row(self) -> dict:
        def fmt_date(d): return d.isoformat() if d else ""
        def fmt_dec(d): return str(d) if d is not None else ""
        return {
            "source_file": self.source_file,
            "vendor_name": self.vendor_name,
            "statement_date": fmt_date(self.statement_date),
            "invoice_number": self.invoice_number,
            "invoice_date": fmt_date(self.invoice_date),
            "due_date": fmt_date(self.due_date),
            "po_number": self.po_number or "",
            "invoice_amount": fmt_dec(self.invoice_amount),
            "balance_amount": fmt_dec(self.balance_amount),
            "transaction_type": self.transaction_type,
            "notes": self.notes or "",
            "status": "",
            "comments": "",
        }


@dataclass
class ParseResult:
    lines: list[StatementLine] = field(default_factory=list)
    file_total: Decimal | None = None  # stated net open balance from the file


CSV_COLUMNS = [
    "source_file", "vendor_name", "statement_date", "invoice_number",
    "invoice_date", "due_date", "po_number", "invoice_amount",
    "balance_amount", "transaction_type", "notes", "status", "comments",
]


class BaseParser(ABC):
    def __init__(self, filepath: str | Path):
        self.filepath = Path(filepath)
        self.filename = self.filepath.name

    @abstractmethod
    def parse(self) -> ParseResult:
        ...
