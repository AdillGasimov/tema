# Architecture and migration decisions

## Actual starting point

The only supplied application is a self-contained landing page. Product sizes/prices are in `SIZES`, discount quantities in `BUNDLES`, and image data in inline `data:` URLs. Customer fields are read by a submit handler and converted to a WhatsApp message. No network data source is present. An optional `fbq` Lead hook exists, but the file does not load a pixel. No referral data, server storage, hosting settings, or credentials are supplied. The original remains in `seed/original.html` for comparison and rollback.

## Smallest useful addition

| Component | Choice | Reason |
| --- | --- | --- |
| Storefront | Existing HTML/CSS + plain JS | Preserve layout, branding, mobile behavior, and content; no frontend build system |
| Backend | Flask on Vercel's Python runtime; Gunicorn locally | Existing API and validation logic preserved; no new frontend framework |
| Database | Supabase PostgreSQL in production; SQLite locally | Durable transactions across Vercel instances; private schema and RLS protect costs/orders |
| Images | Supabase Storage + WebP thumbnails; local disk in development | Durable uploads independent of Vercel function instances |
| Admin | Same-origin HTML/CSS/JS at `/admin` | No separate SPA, identity provider, or exposed backend keys |
| Authentication | Werkzeug password hashes + random server-side sessions | Revocable sessions; no hard-coded credentials or signing key in frontend |
| Referral QR | Local `qrcode` SVG generation | No tracking through an external QR provider |
| Backup | Consistent database snapshot + referenced media in a private archive | SQLite online backup locally; PostgreSQL repeatable-read export and checksummed media for hosted recovery |

Public endpoints: `GET /api/catalog`, `GET /api/referrals/<code>`, and `POST /api/orders`. Admin endpoints require a valid session; state changes also require a CSRF token. Admin product endpoints include costs; the catalog and admin preview use public allowlists. Database, original HTML, backup files, and operational scripts are not served as static files.

Currency is stored as integer qəpik, with exact decimal validation at entry. Bundle discount calculations use integer half-up rounding. A variant can inherit the product's price and cost. Removing a variant deactivates its row rather than deleting history; returned inventory on an old inactive variant remains there until the owner explicitly reconciles it. New variants have distinct identities.

Requests, confirmation, fulfillment, payment and eligibility are separate fields. Write transactions serialize inventory confirmation across workers. Product versions also change when orders alter stock, so an old admin form cannot silently overwrite a newer stock deduction. Order and partner versions reject stale changes with HTTP 409.

Referral codes establish attribution to an active code, not proof of the customer's relationship with a worker. Codes/QRs can be shared. No commission is paid automatically; verify the real sale, delivery and payment in the admin. There was no referral implementation to migrate from the uploaded file, so these are newly implemented requirements.

## Hosting and costs

The owner confirmed Vercel without GitHub integration and supplied a Supabase project URL. The app therefore supports PostgreSQL and Supabase Storage for Vercel. The backend uses the transaction pooler, short-lived verified-TLS connections without prepared statements, and transaction-level advisory locks to preserve stock/order serialization across instances. No database DDL or seed operation runs automatically on serverless cold start. Authenticated first-login bootstrap and an idempotent admin import cover initialization without a terminal.

The earlier local-only SQLite/disk setup is retained for development or the [optional persistent-server deployment](DEPLOYMENT.md). It cannot be used unchanged as production storage on Vercel. Private data and photos must survive function restarts and deployment changes, which is why hosted database/object storage are now necessary. See [Vercel deployment, costs and remaining setup](VERCEL_SUPABASE.md). No paid service was purchased and no live account credentials were used.

## Migration risks and boundaries

- No live files, DNS records, production orders, Supabase objects, or repository history were overwritten. The implementation is prepared locally and awaits secure account configuration and deployment validation.
- Back up the current site before switching. Preserve its original routes or configure redirects only after inspecting the actual host. Both `/` and `/mikrofiber-desmal.html` are served here. Other URLs/assets were not supplied and must be inventoried before cutover.
- The import retains the three photos and actual price choices, not the page's unverified stock claim. Verify sizes, costs and available quantities before enabling orders. Static testimonials are retained as supplied; verify their authenticity separately.
- Product-specific prose below the hero is shown only for the imported towel and its duplicates. Edit generic product descriptions in admin. This is a catalog addition to the landing page, not a CMS for unrelated editorial content.
- Existing WhatsApp chats cannot automatically become historical backend orders. Record or reconcile old sales separately. No historical commissions or old orders have been invented.
- The commission at **request submission** is frozen and earned only on completion. Deactivating/renaming a partner later does not reattribute an already verified request. A new request validates the current active code. Refunds/returns reverse earnings without erasing payouts.
- Submitted requests do not reserve inventory and can exceed available inventory in aggregate. The operator confirms only while sufficient stock exists. This prevents abandoned WhatsApp requests from consuming stock indefinitely.
- No payment gateway, automatic WhatsApp delivery confirmation, partner payout transfer, or external accounting integration is included.
- The browser opens WhatsApp only after a successful backend response. If that response is lost, retrying identical inputs reuses the request key. A changed payload/new browser may create another request; the operator should review suspicious duplicates before confirmation.
- Future schema changes need explicit migrations and a fresh backup. Current `init` only creates missing tables/triggers and never drops data.
