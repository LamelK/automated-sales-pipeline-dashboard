import os
import csv
import time
import boto3
import pymysql
from io import StringIO

# MySQL 8.4 dropped mysql_native_password, so caching_sha2_password needs a TLS channel
CA_BUNDLE = os.path.join(os.path.dirname(__file__), "global-bundle.pem")

# Keys used when the caller does not say which files to load (e.g. a manual invoke).
# The Prefect flow always passes the exact files it uploaded for that run.
DEFAULT_KEYS = {
    "products": "transformed_data/products.csv",
    "stores": "transformed_data/stores.csv",
    "customers": "transformed_data/customers.csv",
    "sales": "transformed_data/sales.csv",
}


def get_csv_from_s3(s3, bucket_name, file_key):
    print(f"📥 Reading: {file_key}")
    obj = s3.get_object(Bucket=bucket_name, Key=file_key)
    return list(csv.DictReader(StringIO(obj["Body"].read().decode("utf-8"))))


def to_number(value):
    return float(value) if value not in ("", None) else None


def upsert_products(cursor, rows):
    values = [(r["product_id"], r["product_name"], r["product_category"] or None) for r in rows]
    cursor.executemany(
        """INSERT INTO products (product_id, product_name, product_category)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE
               product_name = VALUES(product_name),
               product_category = VALUES(product_category)""",
        values,
    )
    print(f"✅ Upserted {len(values)} products.")


def upsert_stores(cursor, rows):
    values = [(r["store_id"], r["store_location"], r["store_region"] or None) for r in rows]
    cursor.executemany(
        """INSERT INTO stores (store_id, store_location, store_region)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE
               store_location = VALUES(store_location),
               store_region = VALUES(store_region)""",
        values,
    )
    print(f"✅ Upserted {len(values)} stores.")


def insert_customers(cursor, rows):
    values = [(r["customer_name"],) for r in rows]
    cursor.executemany("INSERT IGNORE INTO customers (customer_name) VALUES (%s)", values)
    cursor.execute("SELECT customer_name, customer_id FROM customers")
    customer_ids = {name: customer_id for name, customer_id in cursor.fetchall()}
    print(f"✅ Upserted {len(values)} customers, {len(customer_ids)} known in RDS.")
    return customer_ids


def insert_sales(cursor, rows, customer_ids):
    values = []
    for r in rows:
        customer_id = customer_ids.get(r["customer_name"])
        if customer_id is None:
            raise ValueError(f"Unknown customer '{r['customer_name']}' for transaction {r['transaction_id']}")

        values.append((
            r["transaction_id"],
            r["transaction_date"],
            r["transaction_time"],
            r["day_of_week"],
            r["product_id"],
            customer_id,
            r["store_id"],
            to_number(r["price"]),
            to_number(r["quantity_sold"]),
            to_number(r["total_sale"]),
            r["currency_code"],
            r["payment_method"],
            r["order_status"],
        ))

    cursor.executemany(
        """INSERT INTO sales (
               transaction_id, transaction_date, transaction_time, day_of_week,
               product_id, customer_id, store_id, price, quantity_sold, total_sale,
               currency_code, payment_method, order_status
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
               day_of_week = VALUES(day_of_week),
               price = VALUES(price),
               quantity_sold = VALUES(quantity_sold),
               total_sale = VALUES(total_sale),
               currency_code = VALUES(currency_code),
               payment_method = VALUES(payment_method),
               order_status = VALUES(order_status)""",
        values,
    )
    print(f"✅ Upserted {len(values)} sales.")
    return len(values)


def lambda_handler(event, context):
    bucket_name = os.environ["BUCKET_NAME"]

    # event looks like {"keys": {"sales": "transformed_data/<stamp>/sales.csv", ...}}
    keys = {**DEFAULT_KEYS, **(event or {}).get("keys", {})}
    print(f"📄 Loading files: {keys}")

    conn = None

    try:
        print("🔌 Connecting to RDS...")
        conn = pymysql.connect(
            host=os.environ["RDS_HOST"],
            user=os.environ["RDS_USER"],
            password=os.environ["RDS_PASSWORD"],
            db=os.environ["RDS_DB"],
            port=3306,
            connect_timeout=10,
            ssl_ca=CA_BUNDLE,
            ssl_verify_cert=True,
        )
        cursor = conn.cursor()

        s3 = boto3.client("s3")
        products = get_csv_from_s3(s3, bucket_name, keys["products"])
        stores = get_csv_from_s3(s3, bucket_name, keys["stores"])
        customers = get_csv_from_s3(s3, bucket_name, keys["customers"])
        sales = get_csv_from_s3(s3, bucket_name, keys["sales"])

        start = time.time()
        upsert_products(cursor, products)
        upsert_stores(cursor, stores)
        customer_ids = insert_customers(cursor, customers)
        inserted = insert_sales(cursor, sales, customer_ids)
        conn.commit()

        print(f"⏱️ Loaded in {round(time.time() - start, 2)}s.")

        return {
            "status": "success",
            "message": f"products={len(products)}, stores={len(stores)}, customers={len(customers)}, sales={inserted}",
        }

    except Exception as e:
        print(f"❌ Load failed: {e}")
        raise

    finally:
        if conn is not None:
            print("🔌 Closing connection...")
            conn.close()
