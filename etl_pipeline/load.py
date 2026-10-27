import pandas as pd
import boto3
import io
import logging
from prefect import get_run_logger, task
from prefect.tasks import NO_CACHE


@task(name="Data modeling")
def model_sales_data(df: pd.DataFrame, raw_df: pd.DataFrame):
    """
    Splits the cleaned dataframe into three dimension tables and one fact table:
    customers, products, stores, and sales.

    product_id and store_id arrive from the source as stable business keys. customer_id
    is assigned by MySQL and resolved by the loader, so rows in the sales table keep
    pointing at the same customer as history accumulates.

    Returns:
        tuple: (customers_df, products_df, stores_df, sales_df, raw_df)
    """
    df = df.copy()

    # Create dimension tables
    customers = df[["customer_name"]].drop_duplicates().sort_values("customer_name").reset_index(drop=True)
    products = df[["product_id", "product_name", "product_category"]].drop_duplicates().sort_values("product_id").reset_index(drop=True)
    stores = df[["store_id", "store_location", "store_region"]].drop_duplicates().sort_values("store_id").reset_index(drop=True)

    # Create fact table; customer_name is resolved to customer_id by the loader
    sales = df.drop(columns=["product_name", "product_category", "store_location", "store_region"]).copy()

    return customers, products, stores, sales, raw_df


def upload_df_to_s3(df: pd.DataFrame, bucket: str, key: str, s3):
    """
    Uploads a pandas DataFrame as a CSV file to an S3 bucket.
    """

    logger = get_run_logger()

    if df.empty:
        raise ValueError(f"Refusing to upload an empty dataset to s3://{bucket}/{key}")

    try:
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        s3.put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        logger.info(f"✅ Successfully uploaded {key} to s3 bucket")
        return f"s3://{bucket}/{key}"
    except Exception as e:
        logger.error(f"❌ Failed to upload {key} to s3 bucket")
        raise


def data_key(folder: str, filename: str, run_stamp: str) -> str:
    """
    Builds the S3 key for one file of one run.

    Each run gets its own folder, e.g. transformed_data/20261027T160522Z/sales.csv,
    so a later run never overwrites the files an earlier run produced.
    """
    return f"{folder}/{run_stamp}/{filename}"


@task(name="Load Customers to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_customers_to_s3(customers_df: pd.DataFrame, bucket: str, run_stamp: str, s3):
    key = data_key("transformed_data", "customers.csv", run_stamp)
    return upload_df_to_s3(customers_df, bucket, key, s3)


@task(name="Load Products to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_products_to_s3(products_df: pd.DataFrame, bucket: str, run_stamp: str, s3):
    key = data_key("transformed_data", "products.csv", run_stamp)
    return upload_df_to_s3(products_df, bucket, key, s3)


@task(name="Load Stores to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_stores_to_s3(stores_df: pd.DataFrame, bucket: str, run_stamp: str, s3):
    key = data_key("transformed_data", "stores.csv", run_stamp)
    return upload_df_to_s3(stores_df, bucket, key, s3)


@task(name="Load Sales to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_sales_to_s3(sales_df: pd.DataFrame, bucket: str, run_stamp: str, s3):
    key = data_key("transformed_data", "sales.csv", run_stamp)
    return upload_df_to_s3(sales_df, bucket, key, s3)


@task(name="Load Raw Data to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_raw_df_to_s3(raw_df: pd.DataFrame, bucket: str, run_stamp: str, s3):
    key = data_key("raw_data", "raw_sales_data.csv", run_stamp)
    return upload_df_to_s3(raw_df, bucket, key, s3)
