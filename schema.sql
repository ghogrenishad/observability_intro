PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Stock and menu details fit in one table for this small kiosk.
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price_paise INTEGER NOT NULL CHECK (price_paise > 0),
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'awaiting_payment', 'placed', 'cancelled')),
    total_paise INTEGER NOT NULL DEFAULT 0 CHECK (total_paise >= 0),
    payment_status TEXT NOT NULL DEFAULT 'unpaid'
        CHECK (payment_status IN ('unpaid', 'paid')),
    payment_reference TEXT UNIQUE,
    reservation_expires_at TEXT,
    paid_at TEXT,
    placed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status != 'placed' OR payment_status = 'paid')
);

-- One unfinished current order per customer in this first version.
CREATE UNIQUE INDEX IF NOT EXISTS one_current_order_per_customer
ON orders(customer_id) WHERE status IN ('draft', 'awaiting_payment');
CREATE INDEX IF NOT EXISTS orders_by_customer ON orders(customer_id);

CREATE TABLE IF NOT EXISTS order_items (
    item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 20),
    unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise > 0),
    UNIQUE(order_id, product_id)
);

-- Queue the receipt in the same transaction that completes the order.
CREATE TABLE IF NOT EXISTS email_outbox (
    email_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    provider_message_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT
);
