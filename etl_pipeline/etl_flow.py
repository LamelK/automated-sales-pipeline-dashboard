import boto3
import time
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from prefect import flow, get_run_logger, task
from prefect.states import Completed
from etl_pipeline.extract import extract_from_mockaroo
from etl_pipeline.transform import transform_sales_data
from etl_pipeline.lambda_invoke import invoke_lambda_loader
from etl_pipeline.load import (
    model_sales_data,
    upload_customers_to_s3,
    upload_products_to_s3,
    upload_stores_to_s3,
    upload_sales_to_s3,
    upload_raw_df_to_s3
)
from prefect.blocks.system import Secret


def verify_s3_object(s3, path):
    """
    Confirms the object an upload task reported really exists and is not empty.

    Returns:
        tuple: (path, size in bytes)
    """
    if not path or not str(path).startswith("s3://"):
        raise RuntimeError(f"Upload task returned no S3 path: {path!r}")

    bucket, key = str(path)[len("s3://"):].split("/", 1)
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        raise RuntimeError(f"S3 object {path} is missing: {e}") from e

    size = head["ContentLength"]
    if size == 0:
        raise RuntimeError(f"S3 object {path} is empty")
    return path, size


@task(name="Confirm S3 Transfer Complete", retries=1, retry_delay_seconds=10)
def confirm_s3_landing_complete(
    customer_path,
    product_path,
    store_path,
    sales_path,
    raw_path,
    s3
):
    """
    Verifies that every dataset the upload tasks reported is actually present in S3.
    Raises if any object is missing or empty, so a bad upload cannot be reported as success.
    """
    logger = get_run_logger()

    logger.info("-----------------------------------------------------")
    logger.info("Confirming all datasets have successfully landed in S3...")

    paths = {
        "customers": customer_path,
        "products": product_path,
        "stores": store_path,
        "sales": sales_path,
        "raw": raw_path,
    }

    verified = {}
    for label, path in paths.items():
        verified[label], size = verify_s3_object(s3, path)
        logger.info(f"  {label} -> {path} ({size} bytes)")

    logger.info("All specified datasets have successfully landed in S3!")
    logger.info("-----------------------------------------------------")

    return verified

@flow(name="ETL Pipeline Flow")
def main():
    """
    Main ETL pipeline flow:
    1. Loads credentials from Prefect Secret block.
    2. Extracts mock data using Mockaroo API.
    3. Transforms raw data into structured dataframes.
    4. Splits data into dimension and fact tables.
    5. Uploads datasets asynchronously to S3.
    6. Confirms all uploads completed.
    7. Invokes Lambda function to load data into the target database.
    8. Logs runtime and returns success or failure state with custom message.
    """
    logger = get_run_logger()
    overall_start = time.time()
    logger.info("🚀 Starting ETL pipeline...")

    try:
        # Load stored secret block (contains API keys and AWS credentials)
        credentials = Secret.load("credentials").get()
        logger.info("🔐 Loaded secret block: 'credentials'")

        # Extract credentials from the loaded dictionary
        api_key = credentials["MOCKAROO_API_KEY"]
        aws_access_key = credentials["AWS_ACCESS_KEY_ID"]
        aws_secret_key = credentials["AWS_SECRET_ACCESS_KEY"]
        bucket_name = credentials["S3_BUCKET_NAME"]

        logger.info("✅ All secrets loaded successfully.")

        # One stamp per run. Every file this run writes goes in its own S3
        # folder, so runs never overwrite each other.
        run_started = datetime.now(timezone.utc)
        run_stamp = run_started.strftime("%Y%m%dT%H%M%SZ")
        logger.info(f"🗂️ Run folder: {run_stamp}")

        # Initialize the boto3 S3 client for use in the load tasks
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )
        logger.info("✅ boto3 S3 client initialized.")

        # ETL Stage 1: Extract mock data
        start = time.time()
        df_raw = extract_from_mockaroo(api_key=api_key)
        logger.info(f"Extract phase completed in {round(time.time() - start, 2)}s.")

        if df_raw.empty:
            raise RuntimeError("Extraction returned no rows; skipping transform.")

        # ETL Stage 2: Transform the raw dataframe into structured form
        start = time.time()
        transformed_df, raw_df = transform_sales_data(df_raw)
        logger.info(f"🔧 Transform phase completed in {round(time.time() - start, 2)}s.")

        if transformed_df.empty:
            raise RuntimeError("Transformation produced no rows; skipping load.")

        # ETL Stage 3: Split transformed data into dimension/fact tables
        start = time.time()
        customers_df, products_df, stores_df, sales_df, raw_df = model_sales_data(transformed_df, raw_df)
        logger.info(f"🧩 Model/split phase completed in {round(time.time() - start, 2)}s.")

        # ETL Stage 4: Upload each dataset to S3 asynchronously
        start = time.time()
        customer_task_future = upload_customers_to_s3.submit(customers_df, bucket_name, run_stamp, s3=s3_client)
        product_task_future = upload_products_to_s3.submit(products_df, bucket_name, run_stamp, s3=s3_client)
        store_task_future = upload_stores_to_s3.submit(stores_df, bucket_name, run_stamp, s3=s3_client)
        sales_task_future = upload_sales_to_s3.submit(sales_df, bucket_name, run_stamp, s3=s3_client)
        raw_task_future = upload_raw_df_to_s3.submit(raw_df, bucket_name, run_stamp, s3=s3_client)

        logger.info(f"📦 S3 upload tasks submitted. Waiting for completion...")

        # .result() surfaces any upload failure here instead of letting the flow continue
        upload_paths = {
            "customers": customer_task_future.result(),
            "products": product_task_future.result(),
            "stores": store_task_future.result(),
            "sales": sales_task_future.result(),
            "raw": raw_task_future.result(),
        }

        verified = confirm_s3_landing_complete(
            customer_path=upload_paths["customers"],
            product_path=upload_paths["products"],
            store_path=upload_paths["stores"],
            sales_path=upload_paths["sales"],
            raw_path=upload_paths["raw"],
            s3=s3_client
        )

        logger.info(f"✅ S3 load/upload phase completed and confirmed: {sorted(verified)}")

        # Turn the verified s3:// paths into keys, and tell the Lambda exactly
        # which files to load. Without this it would fall back to the old
        # fixed file names, which no longer exist.
        key_prefix = f"s3://{bucket_name}/"
        s3_keys = {name: path.replace(key_prefix, "", 1) for name, path in upload_paths.items()}

        # Invoke the AWS Lambda function to load data into database
        lambda_function_name = "sales-pipeline-loader"
        logger.info(f"⚡ Invoking Lambda loader function: {lambda_function_name}")
        logger.info(f"📄 Files to load: {s3_keys}")

        lambda_response = invoke_lambda_loader.submit(lambda_function_name, payload={"keys": s3_keys})
        response_result = lambda_response.result()
        logger.info(f"✅ Lambda loader response: {response_result}")

        # ✅ Done!
        total_duration = round(time.time() - overall_start, 2)
        logger.info(f"⏱️ Total ETL runtime: {total_duration} seconds.")

        # Return a Completed state with a custom message
        return Completed(message=f"🎯 Flow completed successfully in {total_duration} seconds.")

    except Exception as e:
        # Re-raise so Prefect marks the run Failed with a real traceback
        logger.exception(f"ETL pipeline failed: {str(e)}")
        raise