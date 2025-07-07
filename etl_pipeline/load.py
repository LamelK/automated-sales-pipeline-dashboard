import pandas as pd
import boto3
import io
import logging
from prefect import get_run_logger, task
from prefect.tasks import NO_CACHE


@task(name="Data modeling")
def model_sales_data(df: pd.DataFrame, raw_df: pd.DataFrame):
    """
    Splits the cleaned dataframe into four dimension/fact tables:
    customers, products, stores, and sales.
    Ensures ID columns are present or generates them.
    
    Returns:
        tuple: (customers_df, products_df, stores_df, sales_df, raw_df)
    """
    # Generate IDs if not present
    if 'customer_id' not in df.columns:
        df['customer_id'] = pd.factorize(df['customer_name'])[0] + 1
    if 'product_id' not in df.columns:
        df['product_id'] = pd.factorize(df['product_name'])[0] + 1
    if 'store_id' not in df.columns:
        df['store_id'] = pd.factorize(df['store_location'])[0] + 1

    # Create dimension tables
    customers = df[['customer_id', 'customer_name']].drop_duplicates().reset_index(drop=True)
    products = df[['product_id', 'product_name', 'product_category']].drop_duplicates().reset_index(drop=True)
    stores = df[['store_id', 'store_location']].drop_duplicates().reset_index(drop=True)

    # Create fact table
    sales = df.drop(columns=['customer_name', 'product_name', 'product_category', 'store_location']).copy()

    return customers, products, stores, sales, raw_df


def upload_df_to_s3(df: pd.DataFrame, bucket: str, key: str, s3):
    """
    Uploads a pandas DataFrame as a CSV file to an S3 bucket.
    """

    logger = get_run_logger()

    try:
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        s3.put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        logger.info(f"✅ Successfully uploaded {key} to s3 bucket")
        return f"s3://{bucket}/{key}"
    except Exception as e:
        logger.error(f"❌ Failed to upload {key} to s3 bucket")
        raise


@task(name="Load Customers to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_customers_to_s3(customers_df: pd.DataFrame, bucket: str, s3):
    return upload_df_to_s3(customers_df, bucket, "transformed_data/customers.csv", s3)


@task(name="Load Products to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_products_to_s3(products_df: pd.DataFrame, bucket: str, s3):
    return upload_df_to_s3(products_df, bucket, "transformed_data/products.csv", s3)


@task(name="Load Stores to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_stores_to_s3(stores_df: pd.DataFrame, bucket: str, s3):
    return upload_df_to_s3(stores_df, bucket, "transformed_data/stores.csv", s3)


@task(name="Load Sales to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_sales_to_s3(sales_df: pd.DataFrame, bucket: str, s3):
    return upload_df_to_s3(sales_df, bucket, "transformed_data/sales.csv", s3)


@task(name="Load Raw Data to S3-Bucket", retries=1, retry_delay_seconds=10, cache_policy=NO_CACHE)
def upload_raw_df_to_s3(raw_df: pd.DataFrame, bucket: str, s3):
    return upload_df_to_s3(raw_df, bucket, "raw_data/raw_sales_data.csv", s3)
