# Mikrofiber.shop — existing storefront + private administration

This adds a small backend to the supplied site. It does not replace the site with a new frontend framework. **Your confirmed host is Vercel, without GitHub integration. Follow [Vercel + Supabase setup](docs/VERCEL_SUPABASE.md) for deployment.** Also see [architecture](docs/ARCHITECTURE.md) and the [short Azerbaijani admin guide](docs/ADMIN_GUIDE.az.md).

## What was inspected

- The repository checkout had no commits or application files. `seed/original.html` preserves the exact uploaded `mikrofiber-desmal.html`.
- The upload is HTML, CSS, and browser JavaScript, with three embedded WebP photos. There is no evidence of an existing backend, database, admin authentication, hosting configuration, or referral implementation.
- Two sizes cost 12.99 / 23.99 AZN; compare-at prices are 19.99 / 39.99 AZN. Towel bundle discounts are 10% for two and 15% for three. Delivery is free at 28 May metro or 3.99 AZN by courier.
- The original form opens WhatsApp for `994994350013`. It saves no orders, has no order references, and trusts browser-calculated prices. It also generates simulated recent purchases, viewer counts, countdowns, and a static stock claim.
- The owner confirmed **mikrofiber.shop**, hosted on **Vercel without GitHub integration**, and created Supabase project `https://kopvvjbsrvwuteplmphp.supabase.co`. No credentials have been supplied. No live-site, DNS, hosting, or Supabase changes have been made.

## Local setup

For **local development**, Python 3.12+, venv support, and a local filesystem are sufficient. The default local workflow uses SQLite and disk photos, without external credentials. **Vercel production instead requires the PostgreSQL and Supabase Storage settings in [vercel.env.example](vercel.env.example).** Local files are never used as persistent Vercel storage.

```sh
cd /workspace/tema
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export PUBLIC_BASE_URL=http://localhost:8000
export COOKIE_SECURE=0
# DATA_DIR defaults to ./var; keep it outside the public web root.
.venv/bin/python -m mikrofiber init
.venv/bin/python -m mikrofiber import-original
.venv/bin/python -m mikrofiber create-admin --username owner
.venv/bin/python -m mikrofiber run --port 8000
```

The password command prompts without echoing. Use at least 14 characters and a unique password. There is no default password. Repeat `create-admin` to reset a password; this revokes that user's existing sessions. Run the same command under the same `DATA_DIR` as the server.

Open the storefront and `/admin` on the local server. `COOKIE_SECURE=0` is only for local HTTP. Production must use HTTPS and secure cookies.

**Before accepting orders:** edit the imported towel, enter actual stock per size and private cost prices, enable ordering, preview, and save. The old static “5 left” text is not trustworthy inventory. The import therefore publishes the product for viewing but sets it unavailable with zero stock. No inventory or private cost has been invented. Importing again is a no-op after the first successful import.

## Implemented workflow

- Admin login with hashed passwords, server-stored revocable sessions, CSRF tokens, strict cookies, same-origin checks, and persistent request/login limits.
- Product creation, editing, duplication into a draft with **zero copied stock**, publication, hiding, archiving, search, category and availability filters, private preview, per-variant price/cost/stock, categories, and multiple photo uploads.
- Photos are resized in the browser and uploaded individually to fit Vercel's request limit. The backend independently decodes, validates and re-encodes WebP with smaller thumbnails, saving to Supabase Storage in production or disk locally. SVG uploads are rejected. Removed references do not erase files used by duplicates or backups.
- The original responsive styling, gallery, delivery choices, towel information, reviews supplied in the original file, WhatsApp destination, and towel bundle discounts are retained. Product cards permit more products; a cart permits multiple variants and products. Simulated activity and countdowns are replaced with actual availability. Generic products do not show towel-specific marketing sections.
- Published catalog responses use an explicit public field allowlist. They never serialize cost prices. Hidden/archived/draft products are excluded. Unavailable products may be viewed but cannot be ordered. Checkout rechecks current stock, availability, and price, and rejects a changed displayed total.
- Orders are committed before a WhatsApp URL is returned. Retry keys prevent duplicate requests, including concurrent retries. The browser retains only a retry key and payload digest in session storage, not customer details. A normal retry reuses its key; use **Yeni sifariş sorğusu** to intentionally start another identical request.
- The WhatsApp message includes a unique reference, product/variant names, quantities, unit prices, discounts, total, delivery, customer details, note, and submitted referral code. A fallback link is displayed if the browser blocks the asynchronous popup. The app cannot determine whether the customer actually sends that message.
- Referral partners have unique codes, locally generated downloadable QR links, and configurable fixed AZN commissions. The last referral link or manually entered verified code is remembered for 30 days on that browser. Submission always verifies the active code against the database. Unknown/inactive codes are retained as unverified and earn no commission.
- Order price, customer, referral partner, and commission snapshots are immutable. Product/partner changes apply to future requests. Stock is deducted on **confirmation**, not submission; open requests are not inventory reservations. Confirmation fails if stock has run out. A pending cancellation or physical return restores deducted stock once.
- Commission is earned once per eligible order only when confirmed, delivered, and paid. Refunds, returns, or removal of eligibility append reversals. Payouts are bookkeeping records of payments you make separately; the app does not transfer money. Reversing a commission already paid creates an auditable negative balance that requires manual recovery or settlement.
- Audit events and commission entries are append-only, with timestamps, actors, and required reasons for order changes. These controls prevent ordinary app edits, not tampering by someone with root/database access. Protect the server and keep independent backups.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
```

This exercises product creation/editing, stock and price validation, private cost filtering, statuses and private previews, categories, image uploads, authentication/CSRF/logout/rate limits, order validation and snapshots, multiple items, idempotency under concurrency, stock transitions, referral verification, commission earning/reversal/payout, append-only records, original import, and backup restoration.

PostgreSQL integration tests additionally require a disposable **loopback-only** PostgreSQL 15+ server and `PG_TEST_URL`. Each test creates/drops its own random test database. Without this variable, PostgreSQL tests are explicitly skipped; a skipped suite does not establish readiness. These tests were separately executed against real local PostgreSQL 17. Storage HTTP contract tests use a simulated Supabase service; they do not verify your real project credentials or bucket policies.

```sh
# Set PG_TEST_URL securely to the disposable LOCAL test server URI.
.venv/bin/python -m unittest discover -s tests -p test_postgres.py -v
```

For a real browser test, install the optional dependencies in a separate test environment:

```sh
python3 -m venv /tmp/mikrofiber-browser
/tmp/mikrofiber-browser/bin/python -m pip install -r requirements-browser.txt
# Either use existing /usr/bin/chromium, or install a Playwright Chromium and
# set CHROMIUM_PATH to its executable. Do not disable TLS or checksum verification.
/tmp/mikrofiber-browser/bin/python tests/browser_smoke.py
```

The browser test starts and stops an isolated temporary two-worker Gunicorn server with disposable test data and a random test-only admin password. It tests a mobile storefront and admin workflow and intercepts WhatsApp opening; **it does not send a message or modify production**. Screenshots go to ignored `test-results/`.

The SQLite and PostgreSQL tests, hosted-storage contract tests, and Chromium workflow have been run in this workspace; see `tests/`. Your real Supabase connection, bucket security, Vercel build, HTTPS, scheduled independent backups and real WhatsApp still require deployment-side validation. The first admin can be created through one-time private Vercel environment variables, and the original towel can be imported through admin. There is no public registration or default password.
