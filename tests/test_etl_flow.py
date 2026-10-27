import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from botocore.exceptions import ClientError
from etl_pipeline.etl_flow import main, verify_s3_object

@pytest.fixture
def dummy_df():
    return pd.DataFrame({"col": [1, 2, 3]})

@patch("etl_pipeline.etl_flow.invoke_lambda_loader.submit")
@patch("etl_pipeline.etl_flow.confirm_s3_landing_complete")
@patch("etl_pipeline.etl_flow.upload_raw_df_to_s3.submit")
@patch("etl_pipeline.etl_flow.upload_sales_to_s3.submit")
@patch("etl_pipeline.etl_flow.upload_stores_to_s3.submit")
@patch("etl_pipeline.etl_flow.upload_products_to_s3.submit")
@patch("etl_pipeline.etl_flow.upload_customers_to_s3.submit")
@patch("etl_pipeline.etl_flow.model_sales_data")
@patch("etl_pipeline.etl_flow.transform_sales_data")
@patch("etl_pipeline.etl_flow.extract_from_mockaroo")
@patch("etl_pipeline.etl_flow.boto3.client")
@patch("etl_pipeline.etl_flow.Secret.load")
def test_etl_process(
    mock_secret_load,
    mock_boto3_client,
    mock_extract_from_mockaroo,
    mock_transform_sales_data,
    mock_model_sales_data,
    mock_upload_customers_submit,
    mock_upload_products_submit,
    mock_upload_stores_submit,
    mock_upload_sales_submit,
    mock_upload_raw_submit,
    mock_confirm,
    mock_lambda_submit,
    dummy_df
):
    # 🔐 Mock Secret block
    mock_secret_instance = MagicMock()
    mock_secret_instance.get.return_value = {
        "MOCKAROO_API_KEY": "fake_api_key",
        "AWS_ACCESS_KEY_ID": "fake_aws_key",
        "AWS_SECRET_ACCESS_KEY": "fake_secret",
        "S3_BUCKET_NAME": "fake_bucket"
    }
    mock_secret_load.return_value = mock_secret_instance

    # 🪣 Mock boto3 S3 client
    mock_boto3_client.return_value = MagicMock()

    # 🧪 Mock ETL steps
    mock_extract_from_mockaroo.return_value = dummy_df
    mock_transform_sales_data.return_value = (dummy_df, dummy_df)
    mock_model_sales_data.return_value = (dummy_df, dummy_df, dummy_df, dummy_df, dummy_df)

    # 📤 Mock S3 upload tasks: each future resolves to the S3 path it uploaded to
    uploaded = {
        mock_upload_customers_submit: "s3://fake_bucket/transformed_data/customers.csv",
        mock_upload_products_submit: "s3://fake_bucket/transformed_data/products.csv",
        mock_upload_stores_submit: "s3://fake_bucket/transformed_data/stores.csv",
        mock_upload_sales_submit: "s3://fake_bucket/transformed_data/sales.csv",
        mock_upload_raw_submit: "s3://fake_bucket/raw_data/raw_sales_data.csv",
    }
    for mock_submit, path in uploaded.items():
        future = MagicMock()
        future.result.return_value = path
        mock_submit.return_value = future

    # ✅ Mock confirm_s3_landing_complete
    mock_confirm.return_value = {label: path for label, path in zip(
        ["customers", "products", "stores", "sales", "raw"], uploaded.values()
    )}

    # ⚡ Mock Lambda invoke
    mock_lambda_response = MagicMock()
    mock_lambda_response.result.return_value = {"statusCode": 200, "body": "Success"}
    mock_lambda_submit.return_value = mock_lambda_response

    # 🚀 Run the flow
    main()

    # ✅ Assertions
    assert mock_secret_load.call_count >= 1
    mock_boto3_client.assert_called_once()
    mock_extract_from_mockaroo.assert_called_once()
    mock_transform_sales_data.assert_called_once()
    mock_model_sales_data.assert_called_once()

    mock_upload_customers_submit.assert_called_once()
    mock_upload_products_submit.assert_called_once()
    mock_upload_stores_submit.assert_called_once()
    mock_upload_sales_submit.assert_called_once()
    mock_upload_raw_submit.assert_called_once()

    mock_confirm.assert_called_once()
    confirm_kwargs = mock_confirm.call_args.kwargs
    assert confirm_kwargs["customer_path"] == "s3://fake_bucket/transformed_data/customers.csv"
    assert confirm_kwargs["sales_path"] == "s3://fake_bucket/transformed_data/sales.csv"
    assert confirm_kwargs["s3"] is mock_boto3_client.return_value

    mock_lambda_submit.assert_called_once_with("sales-pipeline-loader")
    mock_lambda_response.result.assert_called_once()


@patch("etl_pipeline.etl_flow.boto3.client")
@patch("etl_pipeline.etl_flow.Secret.load")
@patch("etl_pipeline.etl_flow.extract_from_mockaroo")
def test_flow_raises_when_extraction_returns_no_rows(
    mock_extract_from_mockaroo,
    mock_secret_load,
    mock_boto3_client
):
    mock_secret_load.return_value.get.return_value = {
        "MOCKAROO_API_KEY": "fake_api_key",
        "AWS_ACCESS_KEY_ID": "fake_aws_key",
        "AWS_SECRET_ACCESS_KEY": "fake_secret",
        "S3_BUCKET_NAME": "fake_bucket"
    }
    mock_extract_from_mockaroo.return_value = pd.DataFrame()

    with pytest.raises(RuntimeError, match="Extraction returned no rows"):
        main()


def test_verify_s3_object_rejects_missing_object():
    s3 = MagicMock()
    s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )

    with pytest.raises(RuntimeError, match="is missing"):
        verify_s3_object(s3, "s3://fake_bucket/transformed_data/sales.csv")


def test_verify_s3_object_rejects_empty_object():
    s3 = MagicMock()
    s3.head_object.return_value = {"ContentLength": 0}

    with pytest.raises(RuntimeError, match="is empty"):
        verify_s3_object(s3, "s3://fake_bucket/transformed_data/sales.csv")


def test_verify_s3_object_rejects_missing_path():
    with pytest.raises(RuntimeError, match="returned no S3 path"):
        verify_s3_object(MagicMock(), None)
