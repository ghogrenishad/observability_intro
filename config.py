"""All paths and credentials belong to this folder."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DB_PATH = Path(os.getenv("KIOSK_DB_PATH", str(ROOT / "kiosk.sqlite3")))
API_PORT = int(os.getenv("KIOSK_API_PORT", "8090"))
TRACING = os.getenv("KIOSK_TRACING", "off")
if TRACING not in {"off", "manual", "otel"}:
    raise ValueError("KIOSK_TRACING must be off, manual or otel")
# This lesson introduces local instrumentation before any hosted tracing service.
# os.environ["LANGSMITH_TRACING"] = "false"


def initialize_database():
    import json
    import sqlite3
    with sqlite3.connect(DB_PATH) as db:
        db.executescript((ROOT / "schema.sql").read_text())
        db.executescript("""
            CREATE TABLE IF NOT EXISTS demo_sessions (
                token TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL,
                message TEXT NOT NULL);
        """)
        for p in json.loads((ROOT / "products.json").read_text()):
            db.execute("""INSERT INTO products (product_id,name,description,price_paise,stock_quantity)
                       VALUES (?,?,?,?,?) ON CONFLICT(product_id) DO NOTHING""",
                       tuple(p[k] for k in ("product_id", "name", "description", "price_paise", "stock_quantity")))
