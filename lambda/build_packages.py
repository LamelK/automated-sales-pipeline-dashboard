"""Build the Lambda deployment packages that Terraform uploads.

Each package contains the handler, its dependencies (pymysql) and the RDS CA
bundle used for TLS. Run from anywhere:  python lambda/build_packages.py
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = ROOT / "lambda"
TERRAFORM_DIR = ROOT / "terraform"
CA_BUNDLE = "global-bundle.pem"

PACKAGES = {
    "lambda_deployment_package1.zip": "lambda_function.py",
    "lambda_schema_initializer1.zip": "lambda_schema_initializer.py",
}


def build_package(target, entrypoint, deps_dir):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(LAMBDA_DIR / entrypoint, arcname=entrypoint)
        archive.write(LAMBDA_DIR / CA_BUNDLE, arcname=CA_BUNDLE)
        for path in sorted(deps_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, arcname=str(path.relative_to(deps_dir)))


def main():
    if not (LAMBDA_DIR / CA_BUNDLE).exists():
        raise SystemExit(f"missing {LAMBDA_DIR / CA_BUNDLE}; download it from https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem")

    with tempfile.TemporaryDirectory() as tmp:
        deps_dir = Path(tmp) / "deps"
        deps_dir.mkdir()
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(deps_dir), "pymysql"]
        )
        for archive_name, entrypoint in PACKAGES.items():
            target = TERRAFORM_DIR / archive_name
            build_package(target, entrypoint, deps_dir)
            print(f"built {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
