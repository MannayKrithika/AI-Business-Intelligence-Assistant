"""Project paths and constants shared across modules."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

DEFAULT_CSV_PATH = DATA_DIR / "sales.csv"
DEFAULT_DB_PATH = DATA_DIR / "sales.db"
DEFAULT_ISSUES_PATH = OUTPUT_DIR / "import_issues.csv"

# Column names exactly as they appear in the supplied CSV.
EXPECTED_COLUMNS = (
    "Transaction_Id",
    "Order_date",
    "Product",
    "Category",
    "Region",
    "Sales_channel",
    "Quantity",
    "Unit_price",
    "Discount_amount",
    "Status",
)
