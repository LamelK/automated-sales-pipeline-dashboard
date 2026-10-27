import datetime
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from etl_pipeline.load import model_sales_data, upload_df_to_s3


def transformed_data():
    """Cleaned data as it leaves the transform stage: 17 columns, no nulls."""
    return pd.DataFrame({
        "transaction_id": ["T1", "T2", "T3"],
        "transaction_date": [datetime.date(2026, 10, 24)] * 3,
        "transaction_time": [datetime.time(10, 0, 0)] * 3,
        "day_of_week": ["Saturday"] * 3,
        "product_name": ["AirPods Pro 2", "iPhone 15", "AirPods Pro 2"],
        "product_id": ["SKU-1014", "SKU-1003", "SKU-1014"],
        "product_category": ["Accessories", "Smartphone", "Accessories"],
        "price": [4299.0, 18999.0, 4299.0],
        "quantity_sold": [2.0, 1.0, 3.0],
        "total_sale": [8598.0, 18999.0, 12897.0],
        "currency_code": ["ZAR"] * 3,
        "payment_method": ["Card", "EFT", "Cash"],
        "order_status": ["completed"] * 3,
        "store_location": ["Durban", "Pretoria", "Durban"],
        "store_id": ["STR-DBN-01", "STR-PTA-01", "STR-DBN-01"],
        "store_region": ["KwaZulu-Natal", "Gauteng", "KwaZulu-Natal"],
        "customer_name": ["Sipho Ndlovu", "Lerato Mokoena", "Sipho Ndlovu"],
    })


def test_model_sales_data():
    df = transformed_data()
    raw = df.copy()

    customers, products, stores, sales, raw_df = model_sales_data(df, raw)

    # --- customers: names only, MySQL assigns customer_id ---
    assert list(customers.columns) == ["customer_name"]
    assert len(customers) == 2
    assert customers["customer_name"].is_unique
    assert list(customers["customer_name"]) == sorted(customers["customer_name"])

    # --- products: product_id is the source SKU, not a generated id ---
    assert list(products.columns) == ["product_id", "product_name", "product_category"]
    assert len(products) == 2
    assert products["product_id"].is_unique
    assert set(products["product_id"]) == {"SKU-1014", "SKU-1003"}

    # --- stores: store_id is the source code, region included ---
    assert list(stores.columns) == ["store_id", "store_location", "store_region"]
    assert len(stores) == 2
    assert stores["store_id"].is_unique
    assert set(stores["store_id"]) == {"STR-DBN-01", "STR-PTA-01"}

    # --- sales: one row per transaction, 13 columns, ids left as keys ---
    assert len(sales) == len(df)
    assert len(sales.columns) == 13
    assert "customer_id" not in sales.columns
    assert "customer_name" in sales.columns
    for col in ["product_name", "product_category", "store_location", "store_region"]:
        assert col not in sales.columns

    # --- raw data is passed through untouched ---
    pd.testing.assert_frame_equal(raw_df, raw)


def test_model_sales_data_does_not_mutate_input():
    df = transformed_data()
    before = df.copy()

    model_sales_data(df, before.copy())

    pd.testing.assert_frame_equal(df, before)


@patch("etl_pipeline.load.get_run_logger")
def test_upload_df_to_s3(mock_get_logger):
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    mock_s3 = MagicMock()
    df = transformed_data()
    bucket = "test-bucket"
    key = "test/key.csv"

    result = upload_df_to_s3(df, bucket, key, mock_s3)

    mock_s3.put_object.assert_called_once()
    args, kwargs = mock_s3.put_object.call_args
    assert kwargs["Bucket"] == bucket
    assert kwargs["Key"] == key
    assert isinstance(kwargs["Body"], str)
    assert "T1" in kwargs["Body"]

    mock_logger.info.assert_any_call(f"✅ Successfully uploaded {key} to s3 bucket")

    assert result == f"s3://{bucket}/{key}"


@patch("etl_pipeline.load.get_run_logger")
def test_upload_df_to_s3_failure(mock_get_logger):
    mock_logger = MagicMock()
    mock_get_logger.return_value = mock_logger

    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = Exception("Upload failed")

    df = transformed_data()
    bucket = "test-bucket"
    key = "test/key.csv"

    with pytest.raises(Exception, match="Upload failed"):
        upload_df_to_s3(df, bucket, key, mock_s3)

    mock_logger.error.assert_any_call(f"❌ Failed to upload {key} to s3 bucket")


@patch("etl_pipeline.load.get_run_logger")
def test_upload_df_to_s3_rejects_empty_dataframe(mock_get_logger):
    mock_get_logger.return_value = MagicMock()
    mock_s3 = MagicMock()

    with pytest.raises(ValueError, match="Refusing to upload an empty dataset"):
        upload_df_to_s3(pd.DataFrame(columns=["a"]), "test-bucket", "test/key.csv", mock_s3)

    mock_s3.put_object.assert_not_called()
