from pathlib import Path
import pandas as pd
from app.common.utils import retry

BASE_DIR = Path(__file__).resolve().parents[2]
PRODUCTS_PATH = BASE_DIR / "data" / "products.csv"

@retry(max_attempts=3, delay=1, backoff=2)
def load_products():
    df = pd.read_csv(
        PRODUCTS_PATH,
        sep=";",
        usecols=["group_name", "product_id", "product_name"],
    )
    print("COLUMNS:", df.columns.tolist())
    print(df.head())
    return df