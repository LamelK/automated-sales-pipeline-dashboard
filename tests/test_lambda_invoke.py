import json
from unittest.mock import MagicMock, patch

import pytest

from etl_pipeline.lambda_invoke import invoke_lambda_loader

SECRETS = {
    "AWS_ACCESS_KEY_ID": "fake_key",
    "AWS_SECRET_ACCESS_KEY": "fake_secret",
    "MOCKAROO_API_KEY": "fake_mockaroo",
    "S3_BUCKET_NAME": "fake_bucket",
}


def invoke_with(payload, function_error=None, status_code=200):
    class FakePayload:
        def read(self):
            return json.dumps(payload).encode("utf-8")

    response = {"StatusCode": status_code, "Payload": FakePayload()}
    if function_error:
        response["FunctionError"] = function_error

    client = MagicMock()
    client.invoke.return_value = response

    with patch("etl_pipeline.lambda_invoke.Secret.load") as load, \
            patch("etl_pipeline.lambda_invoke.boto3.client", return_value=client):
        load.return_value.get.return_value = SECRETS
        return invoke_lambda_loader.fn("sales-pipeline-loader")


def test_returns_payload_when_lambda_succeeds():
    payload = {"status": "success", "message": "sales=2"}

    assert invoke_with(payload) == payload


def test_function_error_is_raised():
    with pytest.raises(Exception, match="Lambda invocation failed"):
        invoke_with({"errorMessage": "boom"}, function_error="Unhandled")


def test_error_message_in_body_is_raised():
    with pytest.raises(Exception, match="reported an error"):
        invoke_with({"errorMessage": "could not reach RDS"})


def test_non_success_status_in_body_is_raised():
    with pytest.raises(Exception, match="reported failure"):
        invoke_with({"status": "error", "message": "0 rows loaded"})


def test_non_200_invoke_status_is_raised():
    with pytest.raises(Exception, match="HTTP 500"):
        invoke_with({"status": "success"}, status_code=500)
