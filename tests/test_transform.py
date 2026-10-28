import datetime
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from etl_pipeline.transform import (
    standardize_types,
    drop_invalid_rows,
    drop_duplicate_transactions,
    fill_product_category,
    fill_price,
    fill_quantity,
    compute_total_sale,
    fill_store_region,
    transform_sales_data,
)


def sample_data():
    return pd.DataFrame({
        "transaction_id": ["T1", "T2", "T3", "T4", "T5", "T1", "T6"],
        "transaction_date": ["2026-10-24"] * 7,
        "transaction_time": [
            "10:00:00", "11:00:00", "12:00:00", "13:00:00",
            "14:00:00", "10:00:00", "15:00:00",
        ],
        "day_of_week": ["Saturday"] * 7,
        "product_name": [
            "AirPods Pro 2", "AirPods Pro 2", "AirPods Pro 2", "iPhone 15",
            "iPhone 15", "AirPods Pro 2", "MacBook Air M3",
        ],
        "product_id": [
            "SKU-1014", "SKU-1014", "SKU-1014", "SKU-1003",
            "SKU-1003", "SKU-1014", "SKU-1010",
        ],
        "product_category": [
            "Accessories", None, "Accessories", "Smartphone",
            None, "Accessories", "Laptop",
        ],
        "price": [4299.0, 4299.0, None, 18999.0, None, 4299.0, 24999.0],
        "quantity_sold": [2.0, 1.0, 3.0, None, 4.0, 2.0, 1.0],
        "total_sale": [8598.0, 4299.0, None, None, None, 8598.0, 24999.0],
        "currency_code": ["ZAR"] * 7,
        "payment_method": ["Card", "EFT", "Cash", "Card", "Card", "Card", "Voucher"],
        "order_status": ["completed"] * 6 + ["refunded"],
        "store_location": [
            "Durban", "Durban", "Pretoria", "Pretoria",
            "Durban", "Durban", "Cape Town",
        ],
        "store_id": [
            "STR-DBN-01", "STR-DBN-01", "STR-PTA-01", "STR-PTA-01",
            "STR-DBN-01", "STR-DBN-01", "STR-CPT-01",
        ],
        "store_region": [
            "KwaZulu-Natal", None, "Gauteng", "Gauteng",
            "KwaZulu-Natal", "KwaZulu-Natal", "Western Cape",
        ],
        "customer_name": ["Sipho", "Sipho", "Lerato", "Lerato", None, "Sipho", "Anele"],
    })


def valid_rows():
    """Rows left after the identifier and duplicate guards."""
    return drop_duplicate_transactions(drop_invalid_rows(sample_data()))


def test_standardize_types():
    """Strips text and converts the typed columns to date, time and float."""
    df = pd.DataFrame({
        "transaction_id": [" a1 "],
        "transaction_date": ["2026-10-24"],
        "transaction_time": ["13:23:48"],
        "price": [" 4299 "],
        "quantity_sold": ["2"],
        "total_sale": ["8598"],
    })

    result = standardize_types(df)

    assert result["transaction_id"].iloc[0] == "a1"
    assert not pd.api.types.is_numeric_dtype(result["transaction_id"])
    assert result["transaction_date"].iloc[0] == datetime.date(2026, 10, 24)
    assert result["transaction_time"].iloc[0] == datetime.time(13, 23, 48)
    assert result["price"].iloc[0] == 4299.0
    assert result["quantity_sold"].iloc[0] == 2.0
    assert result["total_sale"].iloc[0] == 8598.0


def test_drop_invalid_rows():
    """Drops rows that have no transaction, product or customer key."""
    result = drop_invalid_rows(sample_data())

    assert len(result) == 6
    assert result["transaction_id"].notna().all()
    assert result["product_id"].notna().all()
    assert result["customer_name"].notna().all()


def test_drop_duplicate_transactions():
    """Keeps the first row per transaction_id so a sale is loaded once."""
    result = valid_rows()

    assert len(result) == 5
    assert result["transaction_id"].is_unique


def test_fill_product_category():
    """Fills a missing category from another row with the same product_id."""
    result = fill_product_category(valid_rows())

    assert result["product_category"].isnull().sum() == 0
    assert result.loc[result["product_id"] == "SKU-1014", "product_category"].eq("Accessories").all()
    assert result.loc[result["product_id"] == "SKU-1003", "product_category"].eq("Smartphone").all()


def test_fill_price():
    """Fills a missing price from another row with the same product_id."""
    result = fill_price(valid_rows())

    assert result["price"].isnull().sum() == 0
    assert result.loc[result["transaction_id"] == "T3", "price"].iloc[0] == 4299.0


def test_fill_quantity():
    """Fills a missing quantity with the rounded average of the column."""
    df = valid_rows()
    expected = round(df["quantity_sold"].mean())

    result = fill_quantity(df)

    assert result["quantity_sold"].isnull().sum() == 0
    assert result.loc[result["transaction_id"] == "T4", "quantity_sold"].iloc[0] == expected


def test_compute_total_sale():
    """Calculates total_sale as price times quantity wherever it is missing."""
    df = fill_quantity(fill_price(valid_rows()))

    result = compute_total_sale(df)

    assert result["total_sale"].isnull().sum() == 0
    for _, row in result.iterrows():
        assert abs(row["price"] * row["quantity_sold"] - row["total_sale"]) < 0.01


def test_fill_store_region():
    """Fills a missing store_region from another row with the same store_id."""
    result = fill_store_region(valid_rows())

    assert result["store_region"].isnull().sum() == 0
    assert result.loc[result["transaction_id"] == "T2", "store_region"].iloc[0] == "KwaZulu-Natal"


@patch("etl_pipeline.transform.get_run_logger")
def test_transform_sales_data(mock_get_logger):
    """Runs the whole clean-up: no nulls, unique transactions, source data untouched."""
    mock_get_logger.return_value = MagicMock()

    df_raw = sample_data()
    original = df_raw.copy()

    cleaned_df, raw_df = transform_sales_data(df_raw)

    assert cleaned_df.shape[0] == 5
    assert cleaned_df.isnull().sum().sum() == 0
    assert cleaned_df["transaction_id"].is_unique
    assert (cleaned_df["price"] * cleaned_df["quantity_sold"] - cleaned_df["total_sale"]).abs().max() < 0.01

    pd.testing.assert_frame_equal(df_raw, raw_df)
    pd.testing.assert_frame_equal(df_raw, original)

    mock_get_logger.assert_called()
