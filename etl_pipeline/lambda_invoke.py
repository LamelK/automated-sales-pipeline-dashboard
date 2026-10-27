import boto3
import json
from prefect import task
from prefect.blocks.system import Secret

@task(name="Invoke AWS-Lambda to transfer data from S3 to RDS", retries=1, retry_delay_seconds=10)
def invoke_lambda_loader(function_name: str, payload: dict = None):
    # Load credentials from Prefect Secret block
    credentials = Secret.load("credentials").get()

    lambda_client = boto3.client(
        'lambda',
        region_name=credentials.get("AWS_REGION", "eu-north-1"),
        aws_access_key_id=credentials["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=credentials["AWS_SECRET_ACCESS_KEY"]
    )
    
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload or {})
    )
    
    result = json.loads(response['Payload'].read())

    if 'FunctionError' in response:
        raise Exception(f"Lambda invocation failed ({response['FunctionError']}): {result}")

    if response.get("StatusCode") != 200:
        raise Exception(f"Lambda invoke returned HTTP {response.get('StatusCode')}: {result}")

    # A handler that catches its own exceptions still returns 200, so inspect the payload
    if isinstance(result, dict):
        if "errorMessage" in result:
            raise Exception(f"Lambda reported an error: {result['errorMessage']}")

        status = result.get("status", result.get("statusCode"))
        if status is not None and str(status).lower() not in ("success", "200"):
            raise Exception(f"Lambda reported failure: {result}")

    return result
