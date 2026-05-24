from dotenv import load_dotenv
import os

load_dotenv()

STATEMENTS_FOLDER = os.getenv("STATEMENTS_FOLDER", "statements")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "output")

# --- Phase 2: P21 API ---
P21_BASE_URL = os.getenv("P21_BASE_URL", "")
P21_USERNAME  = os.getenv("P21_USERNAME", "")
P21_PASSWORD  = os.getenv("P21_PASSWORD", "")

# vendor_name (exactly as Phase 1 writes it) -> P21 vendor_id string, or list of strings
# Use a list when a vendor's invoices are split across multiple P21 vendor IDs.
VENDOR_P21_IDS: dict[str, str | list[str]] = {
    "Anodyne":               "125038",
    "Aspen Medical Products": "100470",
    "BSN Medical":           ["100211", "104376"],  # BSN Medical + Jobst
    "Burten Distribution":   "100050",
    "DJO Global":            ["100329", "109833"],  # DJO Global + Dr Comfort
    "JMS Plastics":          "100421",
    "Julius Zorn (Juzo)":    "102388",
    "Justin Blair & Co.":    "115157",
    "Kenad SG Medical":      "100523",
    "KidSole":               "126139",
    "Kinetic Research":      "125300",
    "Kingsley":              "100331",
    "Langer Biomechanics":   "100249",
    "MD Orthopaedics":       "120482",
    "Medical Action":        "100228",
    "Spinal Technology":     "124974",
    "Knit Rite":             "100216",  # CASCADE ORTHOPEDIC SUPPLY account (K10011100)
    "Thuasne":               "103143",  # CASCADE main account (KCAS40000)
}
