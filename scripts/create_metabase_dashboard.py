"""Create the "Sales Overview" Metabase dashboard through the Metabase API.

Everything is idempotent: re-running updates the existing collection, cards and
dashboard instead of creating duplicates.

Environment variables (never commit credentials):
    METABASE_URL       e.g. https://lamelsmetabase.fyi
    METABASE_EMAIL     admin email
    METABASE_PASSWORD  admin password
"""
import os
import sys
import uuid

import requests

BASE = os.environ["METABASE_URL"].rstrip("/")
DB_NAME = "sales-dashboard"          # the Metabase name for the MySQL connection
COLLECTION_NAME = "Sales Overview"
DASHBOARD_NAME = "Sales Overview"

# sales.store_id — used by the dashboard's Store filter
STORE_FIELD_ID = 83

# Every query ignores cancelled orders so totals reflect real revenue.
EXCLUDE_CANCELLED = "s.order_status <> 'cancelled'"

# Cards that accept the Store filter. They only expose sales.store_id once, so the
# field filter expands without an ambiguous column.
STORE_FILTERED = True


def session():
    """Log in and return a requests session carrying the Metabase session token."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    resp = s.post(
        f"{BASE}/api/session",
        json={"username": os.environ["METABASE_EMAIL"], "password": os.environ["METABASE_PASSWORD"]},
        timeout=30,
    )
    resp.raise_for_status()
    s.headers["X-Metabase-Session"] = resp.json()["id"]
    return s


def database_id(s, name):
    """Find the Metabase database id for the MySQL connection."""
    for db in s.get(f"{BASE}/api/database", timeout=30).json()["data"]:
        if db["name"] == name:
            return db["id"]
    raise SystemExit(f"database {name!r} not found in Metabase")


def collection_id(s, name):
    """Reuse the collection if it exists, otherwise create it."""
    for item in s.get(f"{BASE}/api/collection", timeout=30).json():
        if item["name"] == name and item.get("location") == "/":
            return item["id"]
    resp = s.post(f"{BASE}/api/collection", json={"name": name, "color": "#509EE3"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def cards_in(s, coll_id):
    """Map card name -> id for everything already in the collection."""
    items = s.get(f"{BASE}/api/collection/{coll_id}/items", params={"models": "card"}, timeout=30)
    return {i["name"]: i["id"] for i in items.json().get("data", [])}


def dashboards_in(s, coll_id):
    items = s.get(f"{BASE}/api/collection/{coll_id}/items", params={"models": "dashboard"}, timeout=30)
    return {i["name"]: i["id"] for i in items.json().get("data", [])}


def build_sql(spec):
    """
    Replace the __STORE__ placeholder in a query with the optional store filter.

    `[[AND {{store}}]]` is ignored by Metabase when the filter has no value, and
    expands to a store_id comparison when it does. The filter sits inside the
    query's own WHERE clause so it filters the rows before aggregation.
    """
    sql = spec["sql"].strip().rstrip(";")
    if not spec["store_filter"]:
        return sql.replace("__STORE__", ""), {}

    tag = {
        "store": {
            "id": str(uuid.uuid4()),
            "name": "store",
            "display-name": "Store",
            "type": "dimension",
            "dimension": ["field", STORE_FIELD_ID, None],
            "widget-type": "string/=",
        }
    }
    return sql.replace("__STORE__", "[[AND {{store}}]]"), tag


def upsert_card(s, db_id, coll_id, existing, spec):
    """Create the card, or update it in place if a card with the same name exists."""
    sql, tags = build_sql(spec)
    payload = {
        "name": spec["name"],
        "description": spec.get("description", ""),
        "display": spec["display"],
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": {"query": sql, "template-tags": tags},
        },
        "visualization_settings": spec.get("settings", {}),
        "collection_id": coll_id,
    }
    if spec["name"] in existing:
        resp = s.put(f"{BASE}/api/card/{existing[spec['name']]}", json=payload, timeout=60)
    else:
        resp = s.post(f"{BASE}/api/card", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["id"]


# ---------------------------------------------------------------- card specs
# Tables are referenced by their real names (not aliases) because a Metabase field
# filter expands to "sales.store_id" and an alias would make that column unknown.
# __STORE__ is replaced with the optional store filter by build_sql().
CARDS = [
    {
        "name": "Total revenue",
        "display": "scalar",
        "sql": """
            SELECT ROUND(SUM(sales.total_sale), 2) AS revenue
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
        """,
        "settings": {"scalar.field": "revenue"},
        "store_filter": True,
        "description": "Revenue from all orders that were not cancelled.",
    },
    {
        "name": "Items sold",
        "display": "scalar",
        "sql": """
            SELECT SUM(sales.quantity_sold) AS items
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
        """,
        "settings": {"scalar.field": "items"},
        "store_filter": True,
        "description": "Units sold, excluding cancelled orders.",
    },
    {
        "name": "Average order value",
        "display": "scalar",
        "sql": """
            SELECT ROUND(AVG(sales.total_sale), 2) AS avg_order
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
        """,
        "settings": {"scalar.field": "avg_order"},
        "store_filter": True,
        "description": "Average value per sale line.",
    },
    {
        "name": "Cancelled rate %",
        "display": "scalar",
        "sql": """
            SELECT ROUND(100 * SUM(CASE WHEN sales.order_status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*), 1) AS cancelled_pct
            FROM sales
        """,
        "settings": {"scalar.field": "cancelled_pct"},
        "store_filter": False,
        "description": "Share of all orders that were cancelled.",
    },
    {
        "name": "Revenue trend with 7-day average",
        "display": "line",
        "sql": """
            WITH daily AS (
                SELECT sales.transaction_date AS d, SUM(sales.total_sale) AS revenue
                FROM sales
                WHERE sales.order_status <> 'cancelled' __STORE__
                GROUP BY sales.transaction_date
            )
            SELECT d AS date, revenue,
                   ROUND(AVG(revenue) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS revenue_7day_avg
            FROM daily
            ORDER BY d
        """,
        "settings": {
            "graph.dimensions": ["date"],
            "graph.metrics": ["revenue", "revenue_7day_avg"],
            "series_settings": {"revenue": {"title": "Revenue"}, "revenue_7day_avg": {"title": "7-day average"}},
            "graph.show_values": False,
        },
        "store_filter": True,
        "description": "Daily revenue with a rolling 7-day average, so the trend shows instead of the noise. It fills in as weekly runs accumulate.",
    },
    {
        "name": "Payment method mix",
        "display": "pie",
        "sql": """
            SELECT sales.payment_method, ROUND(SUM(sales.total_sale), 2) AS revenue
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY sales.payment_method
            ORDER BY revenue DESC
        """,
        "settings": {"pie.dimension": "payment_method", "pie.metric": "revenue", "pie.show_legend": True},
        "store_filter": True,
        "description": "Which payment methods bring in the revenue.",
    },
    {
        "name": "Top 10 products by revenue",
        "display": "row",
        "sql": """
            SELECT p.product_name, ROUND(SUM(sales.total_sale), 2) AS revenue, SUM(sales.quantity_sold) AS units
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY p.product_name
            ORDER BY revenue DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["product_name"], "graph.metrics": ["revenue"]},
        "store_filter": True,
        "description": "Revenue leaders - the products that actually make the money.",
    },
    {
        "name": "Most sold products by units",
        "display": "row",
        "sql": """
            SELECT p.product_name, SUM(sales.quantity_sold) AS units_sold
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY p.product_name
            ORDER BY units_sold DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["product_name"], "graph.metrics": ["units_sold"]},
        "store_filter": True,
        "description": "Volume leaders - what customers buy most often, regardless of price.",
    },
    {
        "name": "Revenue share by store",
        "display": "bar",
        "sql": """
            SELECT st.store_location AS store, st.store_region AS region,
                   ROUND(SUM(sales.total_sale), 2) AS revenue,
                   ROUND(100 * SUM(sales.total_sale) / (
                       SELECT SUM(total_sale) FROM sales WHERE order_status <> 'cancelled'
                   ), 1) AS pct_of_total
            FROM sales
            JOIN stores st ON st.store_id = sales.store_id
            WHERE sales.order_status <> 'cancelled'
            GROUP BY st.store_location, st.store_region
            ORDER BY revenue DESC
        """,
        "settings": {"graph.dimensions": ["store"], "graph.metrics": ["revenue"]},
        "store_filter": False,
        "description": "Which stores carry the business, and their share of total revenue.",
    },
    {
        "name": "Revenue by day of week",
        "display": "bar",
        "sql": """
            SELECT sales.day_of_week, ROUND(SUM(sales.total_sale), 2) AS revenue, COUNT(*) AS orders
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY sales.day_of_week
            ORDER BY FIELD(sales.day_of_week,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
        """,
        "settings": {"graph.dimensions": ["day_of_week"], "graph.metrics": ["revenue"]},
        "store_filter": True,
        "description": "Trading pattern across the week.",
    },
    {
        "name": "Sales by hour of day",
        "display": "bar",
        "sql": """
            SELECT HOUR(sales.transaction_time) AS hour_of_day,
                   ROUND(SUM(sales.total_sale), 2) AS revenue,
                   COUNT(*) AS orders
            FROM sales
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY HOUR(sales.transaction_time)
            ORDER BY hour_of_day
        """,
        "settings": {"graph.dimensions": ["hour_of_day"], "graph.metrics": ["revenue"]},
        "store_filter": True,
        "description": "When the shop actually sells - useful for staffing.",
    },
    {
        "name": "Top customers by revenue",
        "display": "row",
        "sql": """
            SELECT c.customer_name, ROUND(SUM(sales.total_sale), 2) AS revenue, COUNT(*) AS orders
            FROM sales
            JOIN customers c ON c.customer_id = sales.customer_id
            WHERE sales.order_status <> 'cancelled' __STORE__
            GROUP BY c.customer_name
            ORDER BY revenue DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["customer_name"], "graph.metrics": ["revenue"]},
        "store_filter": True,
        "description": "Highest-value customers.",
    },
    {
        "name": "Order status breakdown",
        "display": "bar",
        "sql": """
            SELECT sales.order_status, COUNT(*) AS orders, ROUND(SUM(sales.total_sale), 2) AS value
            FROM sales
            GROUP BY sales.order_status
            ORDER BY orders DESC
        """,
        "settings": {"graph.dimensions": ["order_status"], "graph.metrics": ["orders"]},
        "store_filter": False,
        "description": "How many orders complete, and how much value sits in cancelled ones.",
    },
    {
        "name": "Cumulative revenue through the day",
        "display": "line",
        "sql": """
            SELECT hour_of_day, revenue,
                   ROUND(SUM(revenue) OVER (ORDER BY hour_of_day), 2) AS cumulative_revenue
            FROM (
                SELECT HOUR(sales.transaction_time) AS hour_of_day, SUM(sales.total_sale) AS revenue
                FROM sales
                WHERE sales.order_status <> 'cancelled' __STORE__
                GROUP BY HOUR(sales.transaction_time)
            ) hourly
            ORDER BY hour_of_day
        """,
        "settings": {
            "graph.dimensions": ["hour_of_day"],
            "graph.metrics": ["cumulative_revenue"],
            "series_settings": {"cumulative_revenue": {"title": "Cumulative revenue"}},
        },
        "store_filter": True,
        "description": "How the day accumulates - the shape of trading, not just the total.",
    },
]

# Dashboard grid layout: (card name, col, row, width, height) on a 24-column grid
LAYOUT = [
    ("Total revenue", 0, 0, 6, 3),
    ("Items sold", 6, 0, 6, 3),
    ("Average order value", 12, 0, 6, 3),
    ("Cancelled rate %", 18, 0, 6, 3),
    ("Revenue trend with 7-day average", 0, 3, 17, 7),
    ("Payment method mix", 17, 3, 7, 7),
    ("Top 10 products by revenue", 0, 10, 8, 7),
    ("Most sold products by units", 8, 10, 8, 7),
    ("Revenue share by store", 16, 10, 8, 7),
    ("Revenue by day of week", 0, 17, 8, 6),
    ("Sales by hour of day", 8, 17, 8, 6),
    ("Top customers by revenue", 16, 17, 8, 6),
    ("Cumulative revenue through the day", 0, 23, 12, 6),
    ("Order status breakdown", 12, 23, 12, 6),
]


def main():
    s = session()
    db_id = database_id(s, DB_NAME)
    coll_id = collection_id(s, COLLECTION_NAME)

    existing_cards = cards_in(s, coll_id)
    card_ids = {}
    for spec in CARDS:
        card_ids[spec["name"]] = upsert_card(s, db_id, coll_id, existing_cards, spec)
        print(f"card: {spec['name']} (id {card_ids[spec['name']]})")

    existing_dashboards = dashboards_in(s, coll_id)
    store_param = {
        "id": str(uuid.uuid4()),
        "name": "Store",
        "slug": "store",
        "type": "string/=",
        "sectionId": "location",
    }

    if DASHBOARD_NAME in existing_dashboards:
        dash_id = existing_dashboards[DASHBOARD_NAME]
        s.put(f"{BASE}/api/dashboard/{dash_id}",
              json={"name": DASHBOARD_NAME, "parameters": [store_param]}, timeout=30).raise_for_status()
    else:
        resp = s.post(f"{BASE}/api/dashboard",
                      json={"name": DASHBOARD_NAME, "collection_id": coll_id, "parameters": [store_param]},
                      timeout=30)
        resp.raise_for_status()
        dash_id = resp.json()["id"]

    # Replace the dashboard's cards with our layout. Negative ids are temporary.
    by_name = {c["name"]: c for c in CARDS}
    dash_cards = []
    for name, col, row, size_x, size_y in LAYOUT:
        mappings = []
        if by_name[name]["store_filter"]:
            mappings = [{
                "parameter_id": store_param["id"],
                "card_id": card_ids[name],
                "target": ["dimension", ["template-tag", "store"]],
            }]
        dash_cards.append({
            "id": -len(dash_cards) - 1,
            "card_id": card_ids[name],
            "row": row,
            "col": col,
            "size_x": size_x,
            "size_y": size_y,
            "parameter_mappings": mappings,
            "visualization_settings": {},
        })
    put = s.put(f"{BASE}/api/dashboard/{dash_id}/cards", json={"cards": dash_cards}, timeout=60)
    put.raise_for_status()

    print(f"\ndashboard: {BASE}/dashboard/{dash_id}")

    # Public link so viewers do not need a login.
    s.put(f"{BASE}/api/setting/enable-public-sharing", json={"value": True}, timeout=30)
    link = s.post(f"{BASE}/api/dashboard/{dash_id}/public_link", timeout=30)
    if link.status_code == 200:
        print(f"public:    {BASE}/public/dashboard/{link.json()['uuid']}")
    else:
        print("public link:", link.status_code, link.text[:200])


if __name__ == "__main__":
    sys.exit(main())
