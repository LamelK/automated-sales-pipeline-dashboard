import pandas as pd
import numpy as np
from prefect import task, get_run_logger
from prefect.tasks import NO_CACHE

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
    # is_string_dtype covers both the legacy object dtype and pandas 3's str dtype
    str_cols = [col for col in df.columns if pd.api.types.is_string_dtype(df[col])]
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
