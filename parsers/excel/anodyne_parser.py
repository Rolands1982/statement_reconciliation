from __future__ import annotations
import xml.etree.ElementTree as ET
from datetime import timedelta
from parsers.base_parser import BaseParser, ParseResult, StatementLine, parse_date, parse_decimal, assign_po

VENDOR = "Anodyne"

# SpreadsheetML namespace used in NetSuite .xls exports
_NS = "urn:schemas-microsoft-com:office:spreadsheet"


def _get_rows(filepath) -> list[list[str | None]]:
    """Parse SpreadsheetML XML and return all rows as lists of cell text values."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    ws = root.find(f"{{{_NS}}}Worksheet")
    table = ws.find(f"{{{_NS}}}Table")
    result = []
    for row_el in table.findall(f"{{{_NS}}}Row"):
        cells = []
        for cell in row_el.findall(f"{{{_NS}}}Cell"):
            data = cell.find(f"{{{_NS}}}Data")
            cells.append(data.text if data is not None else None)
        result.append(cells)
    return result


class AnodyneParser(BaseParser):
    """
    NetSuite SpreadsheetML export (.xls renamed from XML).
    Row 0: headers — *, Date, Period, Type, Document Number, Name,
                      Account, Memo, PO/Check Number, Amount, Status
    Data from row 1. Only 'Open' status rows are included.
    """

    def parse(self) -> ParseResult:
        rows = _get_rows(self.filepath)
        if not rows:
            return ParseResult()

        # Map header names to column indices
        header = [str(c).strip() if c else "" for c in rows[0]]
        col = {h.upper(): i for i, h in enumerate(header)}

        date_idx   = col.get("DATE",             1)
        type_idx   = col.get("TYPE",             3)
        doc_idx    = col.get("DOCUMENT NUMBER",  4)
        po_idx     = col.get("PO/CHECK NUMBER",  8)
        amt_idx    = col.get("AMOUNT",           9)
        status_idx = col.get("STATUS",          10)

        lines = []

        for row in rows[1:]:
            if not row:
                continue

            status = str(row[status_idx]).strip() if len(row) > status_idx and row[status_idx] else ""
            if status.upper() != "OPEN":
                continue

            doc_no = str(row[doc_idx]).strip() if len(row) > doc_idx and row[doc_idx] else ""
            if not doc_no:
                continue

            inv_date = parse_date(str(row[date_idx]).strip()) if len(row) > date_idx and row[date_idx] else None
            due_date = inv_date + timedelta(days=30) if inv_date else None
            tx_raw   = str(row[type_idx]).strip() if len(row) > type_idx and row[type_idx] else "Invoice"
            amount   = parse_decimal(row[amt_idx] if len(row) > amt_idx else None)

            # PO/Check Number holds "PO check_no" — keep only the leading token (the PO)
            po_full  = str(row[po_idx]).strip() if len(row) > po_idx and row[po_idx] else None
            po_raw   = po_full.split()[0] if po_full else None

            type_map = {"Invoice": "Invoice", "Credit Memo": "Credit Memo", "Payment": "Payment"}
            tx_type  = type_map.get(tx_raw, "Invoice")

            po_number, notes = assign_po(po_raw, tx_type)

            lines.append(StatementLine(
                source_file=self.filename,
                vendor_name=VENDOR,
                statement_date=None,
                invoice_number=doc_no,
                invoice_date=inv_date,
                due_date=due_date,
                po_number=po_number,
                invoice_amount=amount,
                balance_amount=amount,
                transaction_type=tx_type,
                notes=notes,
            ))

        return ParseResult(lines=lines, file_total=None)
