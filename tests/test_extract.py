# tests/test_extract.py
import pytest
from unittest.mock import Mock, patch
import pandas as pd
import requests
from etl_pipeline.extract import extract_from_mockaroo

TEST_CSV = """transaction_id,day_of_week,product_name,product_category,price,quantity_sold,total_sale,store_location,customer_name
1,Saturday,Apple Watch Ultra,Smartwatch,799.99,2,1599.98,Pretoria,Debby Salvatore
2,Thursday,Samsung Galaxy S23,Smartphone,899.99,1,899.99,Johannesburg,Ailsun Fowler"""

@pytest.fixture
def mock_logger():
    with patch('etl_pipeline.extract.get_run_logger') as mock:
        yield mock.return_value

def test_extract_success(mock_logger):
    """Fetches the CSV from Mockaroo and returns it as a dataframe."""
    with patch('requests.get') as mock_get:
        # Setup mock API response
        mock_resp = Mock()
        mock_resp.text = TEST_CSV
        mock_get.return_value = mock_resp

        # Execute
        result = extract_from_mockaroo.fn(api_key="test_key", count=2)

        # Verify DataFrame
        assert isinstance(result, pd.DataFrame)
        assert result.shape == (2, 9)
        assert result.iloc[0]['product_name'] == "Apple Watch Ultra"
        assert result.iloc[1]['customer_name'] == "Ailsun Fowler"
        
        # Verify logging
        mock_logger.info.assert_any_call("🔍 Starting data extraction from Mockaroo with 2 rows...")
        mock_logger.info.assert_any_call("✅ Data successfully retrieved from Mockaroo API.")

def test_extract_failure(mock_logger):
    """Passes the HTTP error up to Prefect and logs it."""
    with patch('requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.HTTPError("API Error")
        
        with pytest.raises(requests.exceptions.HTTPError):
            extract_from_mockaroo.fn(api_key="test_key")
            
        mock_logger.error.assert_called_with("❌ Extraction failed: API Error")