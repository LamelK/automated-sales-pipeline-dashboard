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
        region_name='us-east-1',
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
        raise Exception(f"Lambda invocation failed: {result}")
    
    return result
