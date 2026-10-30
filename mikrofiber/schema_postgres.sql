DO $mikrofiber_setup$
DECLARE t TEXT; r TEXT;
BEGIN
CREATE SCHEMA IF NOT EXISTS mikrofiber;
REVOKE ALL ON SCHEMA mikrofiber FROM PUBLIC;

CREATE TABLE IF NOT EXISTS mikrofiber.admins (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mikrofiber.sessions (
  token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
  username TEXT REFERENCES mikrofiber.admins(username), expires BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS mikrofiber.rate_limits (bucket TEXT NOT NULL, client TEXT NOT NULL, happened BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS rate_lookup ON mikrofiber.rate_limits(bucket, client, happened);
CREATE TABLE IF NOT EXISTS mikrofiber.categories (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS mikrofiber.products (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
  price BIGINT NOT NULL CHECK(price>=1), cost BIGINT CHECK(cost>=0),
  compare_at BIGINT CHECK(compare_at IS NULL OR compare_at>=price),
  category_id TEXT REFERENCES mikrofiber.categories(id),
  status TEXT NOT NULL CHECK(status IN ('draft','published','hidden','archived')),
  available INTEGER NOT NULL CHECK(available IN (0,1)),
  legacy_towel INTEGER NOT NULL DEFAULT 0 CHECK(legacy_towel IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mikrofiber.variants (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES mikrofiber.products(id),
  size TEXT NOT NULL, colour TEXT NOT NULL, price BIGINT CHECK(price>=1), cost BIGINT CHECK(cost>=0),
  compare_at BIGINT, stock INTEGER NOT NULL CHECK(stock>=0),
  available INTEGER NOT NULL CHECK(available IN (0,1)), active INTEGER NOT NULL DEFAULT 1,
  _insertion_sequence BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE TABLE IF NOT EXISTS mikrofiber.images (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES mikrofiber.products(id),
  filename TEXT NOT NULL, thumbnail TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
  position INTEGER NOT NULL, _insertion_sequence BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE TABLE IF NOT EXISTS mikrofiber.partners (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
  commission BIGINT NOT NULL CHECK(commission>=0), active INTEGER NOT NULL CHECK(active IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mikrofiber.orders (
  id TEXT PRIMARY KEY, reference TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
  customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, note TEXT NOT NULL,
  delivery TEXT NOT NULL, delivery_fee BIGINT NOT NULL, subtotal BIGINT NOT NULL,
  discount BIGINT NOT NULL, total BIGINT NOT NULL, currency TEXT NOT NULL DEFAULT 'AZN',
  referral_submitted TEXT NOT NULL, partner_id TEXT REFERENCES mikrofiber.partners(id), referral_code TEXT,
  partner_name TEXT, commission_snapshot BIGINT NOT NULL,
  sale_status TEXT NOT NULL DEFAULT 'submitted' CHECK(sale_status IN ('submitted','confirmed','cancelled')),
  fulfillment TEXT NOT NULL DEFAULT 'pending' CHECK(fulfillment IN ('pending','delivered','returned')),
  payment TEXT NOT NULL DEFAULT 'unpaid' CHECK(payment IN ('unpaid','paid','refunded')),
  eligible INTEGER NOT NULL DEFAULT 1 CHECK(eligible IN (0,1)),
  stock_deducted INTEGER NOT NULL DEFAULT 0 CHECK(stock_deducted IN (0,1)),
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
  _insertion_sequence BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE TABLE IF NOT EXISTS mikrofiber.order_items (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES mikrofiber.orders(id),
  product_id TEXT NOT NULL REFERENCES mikrofiber.products(id), variant_id TEXT NOT NULL REFERENCES mikrofiber.variants(id),
  product_name TEXT NOT NULL, variant_name TEXT NOT NULL, unit_price BIGINT NOT NULL,
  quantity INTEGER NOT NULL, discount BIGINT NOT NULL, line_total BIGINT NOT NULL,
  _insertion_sequence BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE TABLE IF NOT EXISTS mikrofiber.audit_events (
  sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mikrofiber.commission_ledger (
  sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES mikrofiber.orders(id), partner_id TEXT NOT NULL REFERENCES mikrofiber.partners(id),
  kind TEXT NOT NULL CHECK(kind IN ('earned','reversed','payout')),
  amount BIGINT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE OR REPLACE FUNCTION mikrofiber.reject_history_change() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'Historical records are immutable' USING ERRCODE='23514';
END;
$$;
CREATE OR REPLACE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON mikrofiber.audit_events
FOR EACH ROW EXECUTE FUNCTION mikrofiber.reject_history_change();
CREATE OR REPLACE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE ON mikrofiber.commission_ledger
FOR EACH ROW EXECUTE FUNCTION mikrofiber.reject_history_change();
CREATE OR REPLACE TRIGGER items_immutable BEFORE UPDATE OR DELETE ON mikrofiber.order_items
FOR EACH ROW EXECUTE FUNCTION mikrofiber.reject_history_change();
CREATE OR REPLACE TRIGGER orders_no_delete BEFORE DELETE ON mikrofiber.orders
FOR EACH ROW EXECUTE FUNCTION mikrofiber.reject_history_change();
CREATE OR REPLACE TRIGGER orders_snapshot_immutable BEFORE UPDATE OF
  reference,idempotency_key,request_hash,customer_name,phone,address,note,delivery,
  delivery_fee,subtotal,discount,total,currency,referral_submitted,partner_id,
  referral_code,partner_name,commission_snapshot,created_at ON mikrofiber.orders
FOR EACH ROW EXECUTE FUNCTION mikrofiber.reject_history_change();

-- Defence in depth: no browser API role may read even private costs or orders.
  FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA mikrofiber FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA mikrofiber FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA mikrofiber FROM %I',r);
      EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA mikrofiber FROM %I',r);
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['admins','sessions','rate_limits','categories','products','variants',
    'images','partners','orders','order_items','audit_events','commission_ledger'] LOOP
    EXECUTE format('ALTER TABLE mikrofiber.%I ENABLE ROW LEVEL SECURITY',t);
  END LOOP;
END;
$mikrofiber_setup$;
