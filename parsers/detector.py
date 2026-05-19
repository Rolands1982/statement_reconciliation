from __future__ import annotations
from pathlib import Path

from parsers.base_parser import BaseParser
from parsers.excel.aspen_parser import AspenParser
from parsers.excel.bsn_parser import BsnParser
from parsers.excel.djo_parser import DjoParser
from parsers.excel.jms_parser import JmsParser
from parsers.excel.juzo_parser import JuzoExcelParser
from parsers.excel.kenad_parser import KenadParser
from parsers.excel.kidsole_parser import KidSoleParser
from parsers.excel.kingsley_parser import KingsleyParser
from parsers.excel.spinal_parser import SpinalParser
from parsers.pdf.thuasne_parser import ThuasneParser
from parsers.pdf.langer_parser import LangerParser
from parsers.pdf.juzo_pdf_parser import JuzoPdfParser
from parsers.pdf.kinetic_parser import KineticParser
from parsers.pdf.justin_blair_parser import JustinBlairParser
from parsers.pdf.md_ortho_parser import MdOrthoParser
from parsers.excel.anodyne_parser import AnodyneParser
from parsers.excel.account3000105_parser import Account3000105Parser
from parsers.pdf.burten_parser import BurtenParser

# (name_fragment, extension_or_None, parser_class)
# First match wins. Extension None means any extension.
_REGISTRY: list[tuple[str, str | None, type[BaseParser]]] = [
    ("CASCA001",     ".xlsx", AspenParser),
    ("JMS",          ".xlsx", JmsParser),
    ("Spinal",       ".xlsx", SpinalParser),
    ("Kenad",        ".xlsx", KenadParser),
    ("Juzo",         ".xlsx", JuzoExcelParser),
    ("BSN",          ".xlsx", BsnParser),
    ("KidSole",      ".xlsx", KidSoleParser),
    ("DJO",          ".xlsx", DjoParser),
    ("Kingsley",     ".xlsx", KingsleyParser),
    ("Thuasne",      ".pdf",  ThuasneParser),
    ("Langer",       ".pdf",  LangerParser),
    ("Juzo",         ".pdf",  JuzoPdfParser),
    ("KINETIC",      ".pdf",  KineticParser),
    ("Justin Blair", ".pdf",  JustinBlairParser),
    ("Justin_Blair", ".pdf",  JustinBlairParser),
    ("MD Ortho",     ".pdf",  MdOrthoParser),
    ("MD_Ortho",     ".pdf",  MdOrthoParser),
    ("Anodyne",      ".xls",  AnodyneParser),
    ("3000105",      ".xlsx", Account3000105Parser),
    ("CASC.STMT",    ".pdf",  BurtenParser),
]


def get_parser(filepath: str | Path) -> BaseParser | None:
    p = Path(filepath)
    name_upper = p.name.upper()
    ext = p.suffix.lower()
    for fragment, required_ext, cls in _REGISTRY:
        if required_ext and ext != required_ext:
            continue
        if fragment.upper() in name_upper:
            return cls(filepath)
    return None
