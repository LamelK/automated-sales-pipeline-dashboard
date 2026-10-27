import pandas as pd
import numpy as np
import random
from prefect import task, get_run_logger
from prefect.tasks import NO_CACHE

# Names used to replace the source's fixed customer list. 10 x 10 = 100
# combinations, comfortably more than the ~36 customers renamed per run.
FIRST_NAMES = [
    "Thandiwe", "Sipho", "Lerato", "Naledi", "Tshepo",
    "Zanele", "Kagiso", "Palesa", "Andile", "Refilwe",
]
LAST_NAMES = [
    "Mokoena", "Nkosi", "Dlamini", "Khumalo", "Mahlangu",
    "Ndlovu", "Zulu", "Sithole", "Mabaso", "Botha",
]

# How many customers keep the name the source gave them. They are the first
# few names in sorted order, so the same people stay recognisable across runs
# and their orders build up a history in the dashboard.
KEEP_ORIGINAL_NAMES = 4


def randomize_customer_names(df, keep=KEEP_ORIGINAL_NAMES):
    """
    Replaces the source's fixed customer names with generated ones.

    Every original name maps to exactly one new name, so a customer who placed
    12 orders still has 12 orders - just under a different name. The first
    `keep` names (sorted, so stable between runs) are left alone.
    """
    originals = sorted(df["customer_name"].dropna().unique())
    to_rename = originals[keep:]

    combinations = [
        f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES
    ]
    combinations = [name for name in combinations if name not in originals]
    if len(to_rename) > len(combinations):
        raise ValueError(
            f"{len(to_rename)} customers to rename but only "
            f"{len(combinations)} name combinations available"
        )

    # sample() takes without replacement, so two people never share a name.
    rename = dict(zip(to_rename, random.sample(combinations, len(to_rename))))
    df["customer_name"] = df["customer_name"].map(
        lambda name: rename.get(name, name)
    )
    return df

def log_summary(df, label, logger):
    """Logs dataset summary: shape, missing values, duplicates."""
    logger.info(f"📋 Summary: {label}")
    logger.info(f"Shape: {df.shape[0]} rows × {df.shape[1]} columns")
    logger.info("Missing values:")
    logger.info(df.isnull().sum().to_string())
    logger.info(f"Duplicate rows: {df.duplicated().sum()}")

def drop_invalid_rows(df):
    # Drop rows missing the identifiers the target tables need
    return df.dropna(subset=["transaction_id", "product_id", "customer_name"])

def drop_duplicate_transactions(df):
    # transaction_id is the primary key of the sales table
    return df.drop_duplicates(subset=["transaction_id"], keep="first")

def fill_product_category(df):
    # product_category is 1:1 with product_id, so any known row can fill a missing one
    known = df.dropna(subset=["product_category"]).drop_duplicates("product_id")
    lookup = known.set_index("product_id")["product_category"]
    df["product_category"] = df["product_category"].fillna(df["product_id"].map(lookup))
    return df

def fill_price(df):
    # price is 1:1 with product_id
    known = df.dropna(subset=["price"]).drop_duplicates("product_id")
    lookup = known.set_index("product_id")["price"]
    df["price"] = df["price"].fillna(df["product_id"].map(lookup))
    return df

def fill_quantity(df):
    # quantity_sold varies per sale, so fall back to the rounded mean
    mean_quantity = round(df["quantity_sold"].mean())
    df["quantity_sold"] = df["quantity_sold"].fillna(mean_quantity)
    return df

def compute_total_sale(df):
    # Compute total_sale where missing using price × quantity
    mask = df["total_sale"].isnull()
    df.loc[mask, "total_sale"] = df.loc[mask, "price"] * df.loc[mask, "quantity_sold"]
    return df

def fill_store_region(df):
    # store_region is 1:1 with store_id
    known = df.dropna(subset=["store_region"]).drop_duplicates("store_id")
    lookup = known.set_index("store_id")["store_region"]
    df["store_region"] = df["store_region"].fillna(df["store_id"].map(lookup))
    return df

def standardize_types(df):
    # Strip strings and convert specific columns to numeric/date/time
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda x: x.str.strip())
    df["price"] = pd.to_numeric(df["price"], errors='coerce')
    df["quantity_sold"] = pd.to_numeric(df["quantity_sold"], errors='coerce')
    df["total_sale"] = pd.to_numeric(df["total_sale"], errors='coerce')
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors='coerce').dt.date
    df["transaction_time"] = pd.to_datetime(df["transaction_time"], format="%H:%M:%S", errors='coerce').dt.time
    return df

@task(name="🧼 Transform Sales Data", cache_policy=NO_CACHE)
def transform_sales_data(df_raw):
    """
    Cleans the raw data and returns (transformed_df, raw_df).

    The sale date and weekday are taken from the source as-is: the Mockaroo
    schema already returns the trading day (yesterday's date), so rewriting
    them here would only duplicate that logic.
    """
    logger = get_run_logger()
    logger.info("🔧 Starting transformation...")

    # Create working copies
    df = df_raw.copy()
    raw_df = df.copy()

    log_summary(df, "Before Cleaning", logger)

    df = standardize_types(df)
    logger.info("✔️ Standardized data types.")

    df = randomize_customer_names(df)
    logger.info("✔️ Randomized customer names (4 kept as-is).")

    df = drop_invalid_rows(df)
    logger.info("✔️ Dropped invalid rows.")

    df = drop_duplicate_transactions(df)
    logger.info("✔️ Dropped duplicate transactions.")

    df = fill_product_category(df)
    logger.info("✔️ Filled missing product_category.")

    df = fill_price(df)
    logger.info("✔️ Filled missing price.")

    df = fill_quantity(df)
    logger.info("✔️ Filled missing quantity_sold.")

    df = compute_total_sale(df)
    logger.info("✔️ Computed missing total_sale.")

    df = fill_store_region(df)
    logger.info("✔️ Filled missing store_region.")

    log_summary(df, "After Cleaning", logger)
    logger.info("✅ Transformation completed.")

    return df, raw_df
