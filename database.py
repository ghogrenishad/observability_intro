"""SOLUTION: all SQLite work lives here; tools contain no SQL."""
import sqlite3
from uuid import uuid4
from config import DB_PATH

# SOLUTION 1: shared connection setup.
def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

# SOLUTION 2: public menu read.
def read_menu():
    with connect_db() as db:
        rows = db.execute("SELECT product_id, name, price_paise, stock_quantity FROM products WHERE active = 1")
        return [dict(row) for row in rows]

# SOLUTION 3: reuse a customer or create one.
def find_or_create_customer(name, email):
    email = email.strip().lower()
    with connect_db() as db:
        row = db.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone()
        if not row:
            customer_id = str(uuid4())
            db.execute("INSERT INTO customers (customer_id, name, email) VALUES (?, ?, ?)",
                       (customer_id, name, email))
            row = db.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        return dict(row)

# SOLUTION 4: read only this customer's unfinished order.
def read_current_order(customer_id):
    with connect_db() as db:
        row = db.execute("SELECT order_id FROM orders WHERE customer_id = ? AND status IN ('draft', 'awaiting_payment')",
                         (customer_id,)).fetchone()
    if not row:
        return {"items": []}
    return get_owned_order(customer_id, row["order_id"])

# SOLUTION 5: validate first, then save the complete draft selection.
def save_draft(customer_id, items, validate_total=None):
    if not items:
        raise ValueError("Add at least one item.")
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        order = db.execute("SELECT * FROM orders WHERE customer_id = ? AND status IN ('draft', 'awaiting_payment')",
                           (customer_id,)).fetchone()
        if order and order["status"] != "draft":
            raise ValueError("Checkout already started.")
        lines = []
        seen = set()
        for item in items:
            product_id = item["product_id"]
            quantity = item["quantity"]
            if product_id in seen or type(quantity) is not int or not 1 <= quantity <= 20:
                raise ValueError("Use unique products and quantities from 1 to 20.")
            seen.add(product_id)
            product = db.execute("SELECT * FROM products WHERE product_id = ? AND active = 1", (product_id,)).fetchone()
            if not product or product["stock_quantity"] < quantity:
                raise ValueError("Product unavailable or insufficient stock.")
            lines.append((product_id, product["name"], quantity, product["price_paise"]))

        total = sum(quantity * price for _, _, quantity, price in lines)
        if validate_total:
            validate_total(total)  # Enforce policy before any draft mutation.
        order_id = order["order_id"] if order else str(uuid4())
        if not order:
            db.execute("INSERT INTO orders (order_id, customer_id) VALUES (?, ?)", (order_id, customer_id))
        db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        for product_id, name, quantity, price in lines:
            db.execute("INSERT INTO order_items (item_id, order_id, product_id, product_name, quantity, unit_price_paise) VALUES (?, ?, ?, ?, ?, ?)",
                       (str(uuid4()), order_id, product_id, name, quantity, price))
        db.execute("UPDATE orders SET total_paise = ? WHERE order_id = ?", (total, order_id))
    return read_current_order(customer_id)

# SOLUTION 6: one ownership check reused by payment and email.
def get_owned_order(customer_id, order_id):
    with connect_db() as db:
        row = db.execute("""SELECT o.*, c.name, c.email FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.order_id = ? AND o.customer_id = ?""", (order_id, customer_id)).fetchone()
        if not row:
            raise PermissionError("This order is not available to you.")
        order = dict(row)
        order["items"] = [dict(item) for item in db.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,))]
        return order

# SOLUTION 7: payment and stock change together; repeat calls do not deduct twice.
def mark_paid(customer_id, order_id, payment_reference, validate_total=None):
    with connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        order = get_owned_order(customer_id, order_id)
        if order["payment_status"] == "paid":
            if order["payment_reference"] != payment_reference:
                raise ValueError("Already paid with a different reference.")
            return order
        if order["status"] != "draft" or not order["items"]:
            raise ValueError("A non-empty draft is required.")
        if validate_total:
            validate_total(order["total_paise"])
        for item in order["items"]:
            product = db.execute("SELECT * FROM products WHERE product_id = ?", (item["product_id"],)).fetchone()
            if not product or not product["active"] or product["stock_quantity"] < item["quantity"]:
                raise ValueError("Insufficient stock.")
        for item in order["items"]:
            db.execute("UPDATE products SET stock_quantity = stock_quantity - ? WHERE product_id = ?",
                       (item["quantity"], item["product_id"]))
        db.execute("""UPDATE orders SET status = 'placed', payment_status = 'paid',
            payment_reference = ?, paid_at = CURRENT_TIMESTAMP, placed_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND customer_id = ?""", (payment_reference, order_id, customer_id))
    return get_owned_order(customer_id, order_id)
