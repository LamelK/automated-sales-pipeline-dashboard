"""Create the "Sales Overview" Metabase dashboard through the Metabase API.

Idempotent: re-running updates the existing collection, cards and dashboard
instead of creating duplicates.

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
DB_NAME = "sales-dashboard"          # Metabase's name for the MySQL connection
COLLECTION_NAME = "Sales Overview"
DASHBOARD_NAME = "Sales Overview"

# Bluish-earth palette: deep teal, teal, sea, slate, sand, stone.
PALETTE = {
    "deep_teal": "#14524F",
    "teal": "#2A7168",
    "sea": "#6E9A8E",
    "slate": "#3F5B6B",
    "sand": "#C7B299",
    "stone": "#7A8B8B",
}

# Colour per chart metric (the metric column name as returned by the query).
SERIES_COLORS = {
    "Total revenue": {"revenue": PALETTE["deep_teal"]},
    "Items sold": {"items": PALETTE["sea"]},
    "Average order value": {"avg_order": PALETTE["slate"]},
    "Cancelled rate %": {"cancelled_pct": PALETTE["stone"]},
    "Revenue trend with 7-day average": {
        "revenue": PALETTE["deep_teal"],
        "revenue_7day_avg": PALETTE["sand"],
    },
    "Payment method mix": {"revenue": PALETTE["deep_teal"]},
    "Top 10 products by revenue": {"revenue": PALETTE["teal"]},
    "Most sold products by units": {"units_sold": PALETTE["sea"]},
    "Revenue share by store": {"revenue": PALETTE["slate"]},
    "Revenue by day of week": {"revenue": PALETTE["teal"]},
    "Sales by hour of day": {"revenue": PALETTE["deep_teal"]},
    "Top customers by revenue": {"revenue": PALETTE["sea"]},
    "Order status breakdown": {"orders": PALETTE["stone"]},
    "Cumulative revenue through the day": {"cumulative_revenue": PALETTE["slate"]},
}

# Pie slices are coloured per payment method.
PIE_COLORS = {
    "Card": PALETTE["deep_teal"],
    "EFT": PALETTE["teal"],
    "Cash": PALETTE["sea"],
    "Voucher": PALETTE["sand"],
}

# Dashboard filters. field_id points at the Metabase field the filter constrains.
FILTERS = {
    "store": {"field_id": 83, "display": "Store", "type": "string/="},          # sales.store_id
    "payment": {"field_id": 88, "display": "Payment method", "type": "string/="},  # sales.payment_method
    "category": {"field_id": 76, "display": "Product category", "type": "string/="},  # products.product_category
}


# ------------------------------------------------------------------ API helpers
def session():
    """Log in and return a session carrying the Metabase session token."""
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
    for db in s.get(f"{BASE}/api/database", timeout=30).json()["data"]:
        if db["name"] == name:
            return db["id"]
    raise SystemExit(f"database {name!r} not found in Metabase")


def collection_id(s, name):
    """Reuse the collection if it exists, otherwise create it."""
    for item in s.get(f"{BASE}/api/collection", timeout=30).json():
        if item["name"] == name and item.get("location") == "/":
            return item["id"]
    resp = s.post(f"{BASE}/api/collection", json={"name": name, "color": "#2A7168"}, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def items_in(s, coll_id, model):
    """Map name -> id for cards or dashboards already in the collection."""
    resp = s.get(f"{BASE}/api/collection/{coll_id}/items", params={"models": model}, timeout=30)
    return {i["name"]: i["id"] for i in resp.json().get("data", [])}


def build_sql(spec):
    """
    Replace the __FILTERS__ placeholder with the optional filters for this card.

    Each [[AND {{tag}}]] block is dropped by Metabase when that filter has no
    value, and becomes a field comparison when it does.
    """
    sql = spec["sql"].strip().rstrip(";")
    wanted = spec.get("filters", [])
    if not wanted:
        return sql.replace("__FILTERS__", ""), {}

    conditions = " ".join(f"[[AND {{{{{name}}}}}]]" for name in wanted)
    tags = {}
    for name in wanted:
        f = FILTERS[name]
        tags[name] = {
            "id": str(uuid.uuid4()),
            "name": name,
            "display-name": f["display"],
            "type": "dimension",
            "dimension": ["field", f["field_id"], None],
            "widget-type": f["type"],
        }
    return sql.replace("__FILTERS__", conditions), tags


def upsert_card(s, db_id, coll_id, existing, spec):
    """Create the card, or update it in place when a card with that name exists."""
    sql, tags = build_sql(spec)

    settings = dict(spec.get("settings", {}))
    series = dict(settings.get("series_settings", {}))
    for metric, colour in SERIES_COLORS.get(spec["name"], {}).items():
        series.setdefault(metric, {})["color"] = colour
    if series:
        settings["series_settings"] = series
    if spec["display"] == "pie":
        settings["pie.colors"] = PIE_COLORS

    payload = {
        "name": spec["name"],
        "description": spec.get("description", ""),
        "display": spec["display"],
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": {"query": sql, "template-tags": tags},
        },
        "visualization_settings": settings,
        "collection_id": coll_id,
    }
    if spec["name"] in existing:
        resp = s.put(f"{BASE}/api/card/{existing[spec['name']]}", json=payload, timeout=60)
    else:
        resp = s.post(f"{BASE}/api/card", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["id"]


# ------------------------------------------------------------------ card specs
# Tables are named in full (sales.x, not s.x) because a field filter expands to
# "sales.store_id" / "products.product_category" — an alias would break it.
ALL_FILTERS = ["store", "payment", "category"]

CARDS = [
    {
        "name": "Total revenue",
        "display": "scalar",
        "sql": """
            SELECT ROUND(SUM(sales.total_sale), 2) AS revenue
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
        """,
        "settings": {"scalar.field": "revenue"},
        "filters": ALL_FILTERS,
        "description": "Revenue from all orders that were not cancelled.",
    },
    {
        "name": "Items sold",
        "display": "scalar",
        "sql": """
            SELECT SUM(sales.quantity_sold) AS items
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
        """,
        "settings": {"scalar.field": "items"},
        "filters": ALL_FILTERS,
        "description": "Units sold, excluding cancelled orders.",
    },
    {
        "name": "Average order value",
        "display": "scalar",
        "sql": """
            SELECT ROUND(AVG(sales.total_sale), 2) AS avg_order
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
        """,
        "settings": {"scalar.field": "avg_order"},
        "filters": ALL_FILTERS,
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
        "filters": [],
        "description": "Share of all orders that were cancelled.",
    },
    {
        "name": "Revenue trend with 7-day average",
        "display": "line",
        "sql": """
            WITH daily AS (
                SELECT sales.transaction_date AS d, SUM(sales.total_sale) AS revenue
                FROM sales
                JOIN products p ON p.product_id = sales.product_id
                WHERE sales.order_status <> 'cancelled' __FILTERS__
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
        "filters": ALL_FILTERS,
        "description": "Revenue per trading day with a rolling 7-day average. Each pipeline run adds one day.",
    },
    {
        "name": "Payment method mix",
        "display": "pie",
        "sql": """
            SELECT sales.payment_method, ROUND(SUM(sales.total_sale), 2) AS revenue
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY sales.payment_method
            ORDER BY revenue DESC
        """,
        "settings": {"pie.dimension": "payment_method", "pie.metric": "revenue", "pie.show_legend": True},
        "filters": ["store", "category"],
        "description": "Which payment methods bring in the revenue.",
    },
    {
        "name": "Top 10 products by revenue",
        "display": "row",
        "sql": """
            SELECT p.product_name, ROUND(SUM(sales.total_sale), 2) AS revenue, SUM(sales.quantity_sold) AS units
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY p.product_name
            ORDER BY revenue DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["product_name"], "graph.metrics": ["revenue"]},
        "filters": ALL_FILTERS,
        "description": "Revenue leaders - the products that actually make the money.",
    },
    {
        "name": "Most sold products by units",
        "display": "row",
        "sql": """
            SELECT p.product_name, SUM(sales.quantity_sold) AS units_sold
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY p.product_name
            ORDER BY units_sold DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["product_name"], "graph.metrics": ["units_sold"]},
        "filters": ALL_FILTERS,
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
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY st.store_location, st.store_region
            ORDER BY revenue DESC
        """,
        "settings": {"graph.dimensions": ["store"], "graph.metrics": ["revenue"]},
        "filters": ["payment", "category"],
        "description": "Which stores carry the business, and their share of total revenue.",
    },
    {
        "name": "Revenue by day of week",
        "display": "bar",
        "sql": """
            SELECT sales.day_of_week, ROUND(SUM(sales.total_sale), 2) AS revenue, COUNT(*) AS orders
            FROM sales
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY sales.day_of_week
            ORDER BY FIELD(sales.day_of_week,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
        """,
        "settings": {"graph.dimensions": ["day_of_week"], "graph.metrics": ["revenue"]},
        "filters": ALL_FILTERS,
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
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY HOUR(sales.transaction_time)
            ORDER BY hour_of_day
        """,
        "settings": {"graph.dimensions": ["hour_of_day"], "graph.metrics": ["revenue"]},
        "filters": ALL_FILTERS,
        "description": "When the shop actually sells - useful for staffing.",
    },
    {
        "name": "Top customers by revenue",
        "display": "row",
        "sql": """
            SELECT c.customer_name, ROUND(SUM(sales.total_sale), 2) AS revenue, COUNT(*) AS orders
            FROM sales
            JOIN customers c ON c.customer_id = sales.customer_id
            JOIN products p ON p.product_id = sales.product_id
            WHERE sales.order_status <> 'cancelled' __FILTERS__
            GROUP BY c.customer_name
            ORDER BY revenue DESC
            LIMIT 10
        """,
        "settings": {"graph.dimensions": ["customer_name"], "graph.metrics": ["revenue"]},
        "filters": ALL_FILTERS,
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
        "filters": [],
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
                JOIN products p ON p.product_id = sales.product_id
                WHERE sales.order_status <> 'cancelled' __FILTERS__
                GROUP BY HOUR(sales.transaction_time)
            ) hourly
            ORDER BY hour_of_day
        """,
        "settings": {
            "graph.dimensions": ["hour_of_day"],
            "graph.metrics": ["cumulative_revenue"],
            "series_settings": {"cumulative_revenue": {"title": "Cumulative revenue"}},
        },
        "filters": ALL_FILTERS,
        "description": "How the day accumulates - the shape of trading, not just the total.",
    },
]

# Dashboard grid: (card name, col, row, width, height) on a 24-column grid.
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

    existing_cards = items_in(s, coll_id, "card")
    card_ids = {}
    for spec in CARDS:
        card_ids[spec["name"]] = upsert_card(s, db_id, coll_id, existing_cards, spec)
        print(f"card: {spec['name']} (id {card_ids[spec['name']]})")

    # One dashboard parameter per filter, plus the id needed for the mappings.
    param_ids = {}
    parameters = []
    for name, f in FILTERS.items():
        pid = str(uuid.uuid4())
        param_ids[name] = pid
        parameters.append({"id": pid, "name": f["display"], "slug": name, "type": f["type"]})

    existing_dashboards = items_in(s, coll_id, "dashboard")
    if DASHBOARD_NAME in existing_dashboards:
        dash_id = existing_dashboards[DASHBOARD_NAME]
        s.put(f"{BASE}/api/dashboard/{dash_id}",
              json={"name": DASHBOARD_NAME, "parameters": parameters}, timeout=30).raise_for_status()
    else:
        resp = s.post(f"{BASE}/api/dashboard",
                      json={"name": DASHBOARD_NAME, "collection_id": coll_id, "parameters": parameters},
                      timeout=30)
        resp.raise_for_status()
        dash_id = resp.json()["id"]

    # Replace the dashboard's cards with this layout. Negative ids are temporary.
    by_name = {c["name"]: c for c in CARDS}
    dash_cards = []
    for name, col, row, size_x, size_y in LAYOUT:
        mappings = [
            {
                "parameter_id": param_ids[f],
                "card_id": card_ids[name],
                "target": ["dimension", ["template-tag", f]],
            }
            for f in by_name[name]["filters"]
        ]
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
    s.put(f"{BASE}/api/dashboard/{dash_id}/cards", json={"cards": dash_cards}, timeout=60).raise_for_status()

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
