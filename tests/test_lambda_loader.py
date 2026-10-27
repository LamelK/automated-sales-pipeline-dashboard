import importlib.util
import io
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

LOADER_PATH = Path(__file__).resolve().parents[1] / "lambda" / "lambda_function.py"


@pytest.fixture(scope="module")
def loader():
    spec = importlib.util.spec_from_file_location("lambda_function", LOADER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("RDS_HOST", "db.example")
    monkeypatch.setenv("RDS_USER", "admin")
    monkeypatch.setenv("RDS_PASSWORD", "secret")
    monkeypatch.setenv("RDS_DB", "electronics_shop")
    monkeypatch.setenv("BUCKET_NAME", "test-bucket")


class FakeS3:
    def __init__(self, bodies):
        self.bodies = bodies

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.bodies[Key].encode("utf-8"))}


class FakeCursor:
    """Records every statement and imitates MySQL's AUTO_INCREMENT for customers."""

    def __init__(self, known_customers=None):
        self.statements = []
        self.customers = dict(known_customers or {})
        self._next_id = max(self.customers.values(), default=0) + 1
        self._selected = []

    def executemany(self, sql, rows):
        rows = list(rows)
        self.statements.append((sql, rows))
        if "INSERT IGNORE INTO customers" in sql:
            for (name,) in rows:
                if name not in self.customers:
                    self.customers[name] = self._next_id
                    self._next_id += 1

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        if sql.startswith("SELECT customer_name"):
            self._selected = list(self.customers.items())

    def fetchall(self):
        return self._selected


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def staged_csvs(customers=("Sipho Ndlovu", "Lerato Mokoena"), sale_customers=("Sipho Ndlovu", "Lerato Mokoena")):
    products = pd.DataFrame({
        "product_id": ["SKU-1014", "SKU-1003"],
        "product_name": ["AirPods Pro 2", "iPhone 15"],
        "product_category": ["Accessories", "Smartphone"],
    })
    stores = pd.DataFrame({
        "store_id": ["STR-DBN-01", "STR-PTA-01"],
        "store_location": ["Durban", "Pretoria"],
        "store_region": ["KwaZulu-Natal", "Gauteng"],
    })
    customers_df = pd.DataFrame({"customer_name": list(customers)})
    sales = pd.DataFrame({
        "transaction_id": [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ],
        "transaction_date": ["2026-10-24", "2026-10-24"],
        "transaction_time": ["10:00:00", "11:00:00"],
        "day_of_week": ["Saturday", "Saturday"],
        "product_id": ["SKU-1014", "SKU-1003"],
        "price": [4299.0, 18999.0],
        "quantity_sold": [2.0, 1.0],
        "total_sale": [8598.0, 18999.0],
        "currency_code": ["ZAR", "ZAR"],
        "payment_method": ["Card", "EFT"],
        "order_status": ["completed", "completed"],
        "store_id": ["STR-DBN-01", "STR-PTA-01"],
        "customer_name": list(sale_customers),
    })
    return {
        "transformed_data/products.csv": products.to_csv(index=False),
        "transformed_data/stores.csv": stores.to_csv(index=False),
        "transformed_data/customers.csv": customers_df.to_csv(index=False),
        "transformed_data/sales.csv": sales.to_csv(index=False),
    }


def run_loader(loader, monkeypatch, bodies, cursor, event=None):
    connection = FakeConnection(cursor)

    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = FakeS3(bodies)
    monkeypatch.setattr(loader, "boto3", fake_boto3)

    fake_pymysql = MagicMock()
    fake_pymysql.connect.return_value = connection
    monkeypatch.setattr(loader, "pymysql", fake_pymysql)

    return loader.lambda_handler(event or {}, None), connection


def test_upserts_every_table_and_never_deletes(loader, monkeypatch):
    cursor = FakeCursor()

    result, connection = run_loader(loader, monkeypatch, staged_csvs(), cursor)

    assert result["status"] == "success"
    assert "products=2" in result["message"]
    assert "stores=2" in result["message"]
    assert "customers=2" in result["message"]
    assert "sales=2" in result["message"]

    sql = [statement for statement, _ in cursor.statements]
    assert any("INSERT INTO products" in s for s in sql)
    assert any("INSERT INTO stores" in s for s in sql)
    assert any("INSERT IGNORE INTO customers" in s for s in sql)
    assert any(s.startswith("SELECT customer_name") for s in sql)
    assert any("INSERT INTO sales" in s for s in sql)

    assert not any("DELETE" in s.upper() for s in sql)
    assert sum("ON DUPLICATE KEY UPDATE" in s for s in sql) == 3

    assert connection.commits == 1
    assert connection.closed is True


def test_sales_rows_are_complete_and_resolved(loader, monkeypatch):
    cursor = FakeCursor()

    run_loader(loader, monkeypatch, staged_csvs(), cursor)

    sales_rows = [rows for sql, rows in cursor.statements if "INSERT INTO sales" in sql][0]

    assert len(sales_rows) == 2
    assert all(len(row) == 13 for row in sales_rows)
    assert all(isinstance(row[5], int) for row in sales_rows)
    assert all(row[7] is not None and row[8] is not None and row[9] is not None for row in sales_rows)
    assert {row[5] for row in sales_rows} == {1, 2}


def test_customer_ids_survive_a_later_run(loader, monkeypatch):
    first_cursor = FakeCursor()
    run_loader(
        loader,
        monkeypatch,
        staged_csvs(
            customers=("Anele Dlamini", "Thabo Nkosi"),
            sale_customers=("Anele Dlamini", "Thabo Nkosi"),
        ),
        first_cursor,
    )
    day_one = dict(first_cursor.customers)

    second_cursor = FakeCursor(known_customers=day_one)
    run_loader(
        loader,
        monkeypatch,
        staged_csvs(
            customers=("Anele Dlamini", "Thabo Nkosi", "Zanele Dube"),
            sale_customers=("Anele Dlamini", "Thabo Nkosi"),
        ),
        second_cursor,
    )

    assert second_cursor.customers["Anele Dlamini"] == day_one["Anele Dlamini"]
    assert second_cursor.customers["Thabo Nkosi"] == day_one["Thabo Nkosi"]
    assert second_cursor.customers["Zanele Dube"] == max(day_one.values()) + 1


def test_connection_failure_is_raised_not_masked(loader, monkeypatch):
    fake_pymysql = MagicMock()
    fake_pymysql.connect.side_effect = RuntimeError("cannot reach RDS")
    monkeypatch.setattr(loader, "pymysql", fake_pymysql)

    with pytest.raises(RuntimeError, match="cannot reach RDS"):
        loader.lambda_handler({}, None)


def test_loads_the_files_named_in_the_event(loader, monkeypatch):
    """The Prefect flow passes timestamped keys; the loader must read those, not the old fixed names."""
    cursor = FakeCursor()
    stamp = "20261027T160522Z"
    bodies = {
        f"transformed_data/{stamp}/{key.split('/')[-1]}": body
        for key, body in staged_csvs().items()
    }
    event = {"keys": {name: f"transformed_data/{stamp}/{name}.csv"
                      for name in ("products", "stores", "customers", "sales")}}

    result, _ = run_loader(loader, monkeypatch, bodies, cursor, event=event)

    assert result["status"] == "success"
    assert "sales=2" in result["message"]


def test_unknown_customer_is_rejected(loader, monkeypatch):
    cursor = FakeCursor()
    bodies = staged_csvs(customers=("Sipho Ndlovu",))

    with pytest.raises(ValueError, match="Unknown customer"):
        run_loader(loader, monkeypatch, bodies, cursor)
