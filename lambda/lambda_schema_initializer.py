import os
import pymysql

# MySQL 8.4 dropped mysql_native_password, so caching_sha2_password needs a TLS channel
CA_BUNDLE = os.path.join(os.path.dirname(__file__), "global-bundle.pem")

DDL = [
    """
    CREATE TABLE IF NOT EXISTS products (
        product_id       VARCHAR(20)  NOT NULL,
        product_name     VARCHAR(255) NOT NULL,
        product_category VARCHAR(100),
        PRIMARY KEY (product_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stores (
        store_id       VARCHAR(20)  NOT NULL,
        store_location VARCHAR(255) NOT NULL,
        store_region   VARCHAR(100),
        PRIMARY KEY (store_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        customer_id   INT          NOT NULL AUTO_INCREMENT,
        customer_name VARCHAR(255) NOT NULL,
        PRIMARY KEY (customer_id),
        UNIQUE KEY uq_customer_name (customer_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sales (
        transaction_id   CHAR(36)     NOT NULL,
        transaction_date DATE         NOT NULL,
        transaction_time TIME         NOT NULL,
        day_of_week      VARCHAR(15),
        product_id       VARCHAR(20)  NOT NULL,
        customer_id      INT          NOT NULL,
        store_id         VARCHAR(20)  NOT NULL,
        price            DECIMAL(10,2),
        quantity_sold    INT,
        total_sale       DECIMAL(10,2),
        currency_code    CHAR(3),
        payment_method   VARCHAR(20),
        order_status     VARCHAR(20),
        PRIMARY KEY (transaction_id),
        KEY idx_sales_date (transaction_date),
        KEY idx_sales_product (product_id),
        KEY idx_sales_store (store_id),
        KEY idx_sales_customer (customer_id),
        CONSTRAINT fk_sales_product  FOREIGN KEY (product_id)  REFERENCES products(product_id),
        CONSTRAINT fk_sales_customer FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
        CONSTRAINT fk_sales_store    FOREIGN KEY (store_id)    REFERENCES stores(store_id)
    )
    """,
]


def handler(event, context):
    """
    Creates the tables.

    Send {"action": "reset"} to empty the sales table first — useful when the
    dataset should start from a clean, single run.
    """
    action = (event or {}).get("action", "create")

    conn = pymysql.connect(
        host=os.environ["RDS_HOST"],
        user=os.environ["RDS_USER"],
        password=os.environ["RDS_PASSWORD"],
        database=os.environ["RDS_DB"],
        connect_timeout=10,
        ssl_ca=CA_BUNDLE,
        ssl_verify_cert=True,
    )

    try:
        with conn.cursor() as cur:
            if action == "reset":
                cur.execute("DELETE FROM sales")
                conn.commit()
                print("Sales table cleared.")
                return {"status": "success", "message": "sales table cleared"}

            for statement in DDL:
                cur.execute(statement)
        conn.commit()
        print("Tables created successfully.")
        return {"status": "success", "message": f"{len(DDL)} statements executed"}
    finally:
        conn.close()
