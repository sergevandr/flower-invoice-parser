import pandas as pd
from utils import retry

@retry(max_attempts=3, delay=1, backoff=2)
def load_products():
    df = pd.read_csv(
        "products.csv",
        sep=";",
        usecols=["group_name", "product_id", "product_name"],
    )
    print("COLUMNS:", df.columns.tolist())
    print(df.head())
    return df