# Project status

_Last updated: 2026-10-27 — roughly 95% done: everything is built, the first end-to-end run has not happened yet._

The flow now fails loudly: S3 uploads are verified with `head_object`, the Lambda payload is inspected,
and errors are raised instead of being returned as a `Failed` state.

## Done

- Pipeline code: `etl_pipeline/transform.py`, `load.py`, `lambda_invoke.py`, `etl_flow.py`, `lambda/` loader.
- Tests: 21 passing (`python -m pytest -q`).
- Infrastructure (Terraform): VPC, RDS `electronics-shop-db`, S3 `etl-data-sales-pipeline`, Lambda `sales-pipeline-loader`, Metabase EC2 instance (`t3.medium`).
- Database schema created once by hand in MySQL Workbench (star schema, see [README.md](./README.md#database-schema)).
- Metabase connected to RDS and running (HTTP — the "not secure" badge is expected).

## Not done yet

1. Push the flow code to S3 and create the deployment:

   ```
   cd C:\Users\melak\Desktop\automated-sales-pipeline-dashboard
   prefect deploy --all
   ```

   `prefect deploy` is what uploads the flow code; the last run failed in the `pull_from_s3` step because
   `s3://etl-data-sales-pipeline/flows/` did not exist yet. As of 2026-10-27 the bucket still holds only the
   `raw_data/` and `transformed_data/` prefixes.

2. Trigger `etl-deployment` from the Prefect UI (Quick-run) or:

   ```
   prefect deployment run main/etl-deployment
   ```

3. Verify the run end to end: extract → transform → upload to S3 → Lambda → RDS, then confirm the data appears
   in a Metabase question.

## Known issues to clean up

- `terraform/terraform.tfstate` and `terraform/terraform.tfstate.backup` contain the RDS password in plaintext.
  They are ignored by `.gitignore`, along with the `terraform/metabase` SSH key pair — keep it that way.
- `terraform/lambda_deployment_package1.zip` is committed and must be rebuilt whenever `lambda/lambda_function.py`
  changes, or `terraform apply` will deploy the previous loader.
- Metabase is served over plain HTTP. Acceptable for the demo; put it behind TLS before any real use.
