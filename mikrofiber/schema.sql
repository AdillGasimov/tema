PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS admins (
  username TEXT PRIMARY KEY, password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
  username TEXT REFERENCES admins(username), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (
  bucket TEXT NOT NULL, client TEXT NOT NULL, happened INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_lookup ON rate_limits(bucket, client, happened);
CREATE TABLE IF NOT EXISTS categories (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
  price INTEGER NOT NULL CHECK(price >= 1), cost INTEGER CHECK(cost >= 0),
  compare_at INTEGER CHECK(compare_at IS NULL OR compare_at >= price),
  category_id TEXT REFERENCES categories(id),
  status TEXT NOT NULL CHECK(status IN ('draft','published','hidden','archived')),
  available INTEGER NOT NULL CHECK(available IN (0,1)),
  legacy_towel INTEGER NOT NULL DEFAULT 0 CHECK(legacy_towel IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variants (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
  size TEXT NOT NULL, colour TEXT NOT NULL,
  price INTEGER CHECK(price >= 1), cost INTEGER CHECK(cost >= 0),
  compare_at INTEGER, stock INTEGER NOT NULL CHECK(stock >= 0),
  available INTEGER NOT NULL CHECK(available IN (0,1)),
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
  filename TEXT NOT NULL, thumbnail TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
  position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS partners (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
  commission INTEGER NOT NULL CHECK(commission >= 0), active INTEGER NOT NULL CHECK(active IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, reference TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, note TEXT NOT NULL,
  delivery TEXT NOT NULL, delivery_fee INTEGER NOT NULL, subtotal INTEGER NOT NULL,
  discount INTEGER NOT NULL, total INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'AZN',
  referral_submitted TEXT NOT NULL, partner_id TEXT REFERENCES partners(id),
  referral_code TEXT, partner_name TEXT, commission_snapshot INTEGER NOT NULL,
  sale_status TEXT NOT NULL DEFAULT 'submitted' CHECK(sale_status IN ('submitted','confirmed','cancelled')),
  fulfillment TEXT NOT NULL DEFAULT 'pending' CHECK(fulfillment IN ('pending','delivered','returned')),
  payment TEXT NOT NULL DEFAULT 'unpaid' CHECK(payment IN ('unpaid','paid','refunded')),
  eligible INTEGER NOT NULL DEFAULT 1 CHECK(eligible IN (0,1)),
  stock_deducted INTEGER NOT NULL DEFAULT 0 CHECK(stock_deducted IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
  product_id TEXT NOT NULL REFERENCES products(id), variant_id TEXT NOT NULL REFERENCES variants(id),
  product_name TEXT NOT NULL, variant_name TEXT NOT NULL,
  unit_price INTEGER NOT NULL, quantity INTEGER NOT NULL, discount INTEGER NOT NULL, line_total INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commission_ledger (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
  partner_id TEXT NOT NULL REFERENCES partners(id),
  kind TEXT NOT NULL CHECK(kind IN ('earned','reversed','payout')),
  amount INTEGER NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN
  SELECT RAISE(ABORT, 'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN
  SELECT RAISE(ABORT, 'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON commission_ledger BEGIN
  SELECT RAISE(ABORT, 'Commission ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON commission_ledger BEGIN
  SELECT RAISE(ABORT, 'Commission ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS items_no_update BEFORE UPDATE ON order_items BEGIN
  SELECT RAISE(ABORT, 'Order price snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS items_no_delete BEFORE DELETE ON order_items BEGIN
  SELECT RAISE(ABORT, 'Order price snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS orders_snapshot_immutable BEFORE UPDATE OF
  reference, idempotency_key, request_hash, customer_name, phone, address, note, delivery,
  delivery_fee, subtotal, discount, total, currency, referral_submitted, partner_id,
  referral_code, partner_name, commission_snapshot, created_at ON orders BEGIN
  SELECT RAISE(ABORT, 'Order snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS orders_no_delete BEFORE DELETE ON orders BEGIN
  SELECT RAISE(ABORT, 'Order records must be retained'); END;
