import boto3
import time
from prefect import flow, get_run_logger, task
from prefect.states import Completed, Failed
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

@task(name="Confirm S3 Transfer Complete", retries=1, retry_delay_seconds=10)
def confirm_s3_landing_complete(
    customer_upload_future, #Future objects 
    product_upload_future,
    store_upload_future,
    sales_upload_future,
    raw_upload_future
):
    """
    This task confirms that all upstream S3 upload tasks have successfully completed.
    It explicitly receives and implicitly waits for the futures passed as arguments to resolve.
    """
    logger = get_run_logger()

    logger.info("-----------------------------------------------------")
    logger.info("Confirming all datasets have successfully landed in S3...")
    # The .result() call here ensures the futures are resolved before proceeding within *this* task.
    customer_path = customer_upload_future
    product_path = product_upload_future
    store_path = store_upload_future
    sales_path = sales_upload_future
    raw_path = raw_upload_future

    logger.info("-----------------------------------------------------")
    logger.info("All specified datasets have successfully landed in S3!")
    logger.info(f"  Customers uploaded to: {customer_path}")
    logger.info(f"  Products uploaded to: {product_path}")
    logger.info(f"  Stores uploaded to: {store_path}")
    logger.info(f"  Sales uploaded to: {sales_path}")
    logger.info(f"  Raw data uploaded to: {raw_path}")
    logger.info("-----------------------------------------------------")

    return True # Or any other success indicator

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

        # ETL Stage 2: Transform the raw dataframe into structured form
        start = time.time()
        transformed_df, raw_df = transform_sales_data(df_raw)
        logger.info(f"🔧 Transform phase completed in {round(time.time() - start, 2)}s.")

        # ETL Stage 3: Split transformed data into dimension/fact tables
        start = time.time()
        customers_df, products_df, stores_df, sales_df, raw_df = model_sales_data(transformed_df, raw_df)
        logger.info(f"🧩 Model/split phase completed in {round(time.time() - start, 2)}s.")

        # ETL Stage 4: Upload each dataset to S3 asynchronously
        start = time.time()
        customer_task_future = upload_customers_to_s3.submit(customers_df, bucket_name, s3=s3_client)
        product_task_future = upload_products_to_s3.submit(products_df, bucket_name, s3=s3_client)
        store_task_future = upload_stores_to_s3.submit(stores_df, bucket_name, s3=s3_client)
        sales_task_future = upload_sales_to_s3.submit(sales_df, bucket_name, s3=s3_client)
        raw_task_future = upload_raw_df_to_s3.submit(raw_df, bucket_name, s3=s3_client)

        logger.info(f"📦 S3 upload tasks submitted. Waiting for completion...")

        # Call the confirmation task to ensure all uploads completed
        confirm_s3_landing_complete.submit(
            customer_upload_future=customer_task_future,
            product_upload_future=product_task_future,
            store_upload_future=store_task_future,
            sales_upload_future=sales_task_future,
            raw_upload_future=raw_task_future
        ).result()

        logger.info(f"✅ S3 load/upload phase completed and confirmed.")

        # Invoke the AWS Lambda function to load data into database
        lambda_function_name = "mapDataFunction"  
        logger.info(f"⚡ Invoking Lambda loader function: {lambda_function_name}")
        
        lambda_response = invoke_lambda_loader.submit(lambda_function_name)
        response_result = lambda_response.result()
        logger.info(f"✅ Lambda loader response: {response_result}")

        # ✅ Done!
        total_duration = round(time.time() - overall_start, 2)
        logger.info(f"⏱️ Total ETL runtime: {total_duration} seconds.")

        # Return a Completed state with a custom message
        return Completed(message=f"🎯 Flow completed successfully in {total_duration} seconds.")

    except Exception as e:
        logger.error(f"ETL pipeline failed: {str(e)}")

        # Return a Failed state with a custom error message
        return Failed(message=f"❌ Flow failed: {str(e)}")