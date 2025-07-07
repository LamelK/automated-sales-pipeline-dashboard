from prefect import task, get_run_logger
import requests
import pandas as pd
from io import StringIO
from prefect.tasks import NO_CACHE

@task(retries=1, retry_delay_seconds=10, name="📥 Extract from Mockaroo", cache_policy=NO_CACHE)
def extract_from_mockaroo(api_key: str, save_path: str = "raw_sales_data.csv", count: int = 500) -> pd.DataFrame:
    """
    Fetches synthetic CSV data from Mockaroo, saves it locally, and returns it as a DataFrame.
    Retries on failure up to 3 times.
    """
    logger = get_run_logger()
    url = f"https://api.mockaroo.com/api/0935e020?key={api_key}&count={count}"
    logger.info(f"🔍 Starting data extraction from Mockaroo with {count} rows...")

    try:
        response = requests.get(url)
        response.raise_for_status()
        logger.info("✅ Data successfully retrieved from Mockaroo API.")

        # Convert response to DataFrame
        df = pd.read_csv(StringIO(response.text))
        logger.info(f"📊 Extracted DataFrame with shape: {df.shape[0]} rows × {df.shape[1]} columns.")
        return df

    except Exception as e:
        logger.error(f"❌ Extraction failed: {e}")
        raise e  # raise so Prefect knows to retry
