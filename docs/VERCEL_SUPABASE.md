# Deploy mikrofiber.shop on Vercel + Supabase

Your project URL is `https://kopvvjbsrvwuteplmphp.supabase.co`. This is a public identifier, not a credential. No password or secret has been supplied, and this project has not been modified or verified from the development environment.

The site keeps its HTML/CSS and admin interface. On Vercel, PostgreSQL replaces local SQLite and Supabase Storage replaces local photo files. `/tmp` is used only for temporary image processing. Missing persistent services cause startup to fail rather than silently accepting data on ephemeral disk. The local SQLite workflow remains available for development.

## 1. Initialize your new Supabase project

In Supabase Dashboard → your project → **SQL Editor**, create a query. Paste and run the contents of:

1. [mikrofiber/schema_postgres.sql](../mikrofiber/schema_postgres.sql)
2. [supabase/storage.sql](../supabase/storage.sql)

Run them separately, in that order. Copy the **complete** database script, from `DO $mikrofiber_setup$` through the final `$mikrofiber_setup$;`. It is one atomic statement with explicit schema-qualified references, independent of the SQL Editor's search-path settings. Clear any text selection before clicking Run. It creates a private `mikrofiber` schema with tables, constraints, RLS, and immutable audit/history triggers. It does not drop tables or insert invented sales. It can be repeated without deleting data. The second creates the public `product-images` bucket, without giving anonymous users permission to upload/delete. If a bucket with that name already exists with incompatible settings, it stops rather than changing it.

Do **not** add `mikrofiber` to the schemas exposed through the Supabase Data API or create public table policies. Database reads/writes go through the authenticated Python backend; costs and customer details must not be accessible to publishable/anon API keys. The app connects as the schema owner (the normal project PostgreSQL user). A future restricted runtime role must receive deliberate grants and RLS policies before use.

No existing production data is migrated automatically. If you have started using local SQLite, preserve a backup and plan a separate data migration instead of creating an unrelated empty live catalog. In the prepared workspace, local data consists only of the imported towel; all automated orders/users were in disposable test databases.

## 2. Add private Vercel environment variables

Open the **existing Vercel project** that serves mikrofiber.shop → **Settings → Environment Variables**. Use [vercel.env.example](../vercel.env.example) as the checklist. Set these for **Production**:

| Name | Value / where to find it |
| --- | --- |
| `PUBLIC_BASE_URL` | `https://mikrofiber.shop` |
| `COOKIE_SECURE` | `1` |
| `STORAGE_BACKEND` | `supabase` |
| `SUPABASE_URL` | `https://kopvvjbsrvwuteplmphp.supabase.co` |
| `SUPABASE_STORAGE_BUCKET` | `product-images` |
| `DATABASE_URL` | Supabase **Connect → Transaction pooler**, normally port **6543**. Copy the full PostgreSQL URI and replace its password placeholder securely. URL-encode reserved characters in the password. Use the supplied project/user/region hostname; do not invent it from the project ID. |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase API Keys settings: a **server secret key or legacy service-role key**, never the publishable/anon key. |
| `INITIAL_ADMIN_USERNAME` | Your chosen login name, e.g. `owner` (3–80 letters/digits/dot/hyphen/underscore) |
| `INITIAL_ADMIN_PASSWORD` | Your own unique password, at least **14 characters**, entered only in secure Vercel settings |
| `WHATSAPP_NUMBER` | `994994350013`, unless you want another number |
| `DELIVERY_FEE_AZN` | `3.99`, unless you change delivery pricing |

Keep `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `INITIAL_ADMIN_PASSWORD` secret/sensitive. Never prefix them with `NEXT_PUBLIC_`, `PUBLIC_`, or `VITE_`; never put values in chat, source code, or the ZIP. This app does not need a Supabase browser key. Do not set `DATA_DIR` as persistent storage or enable `TRUST_PROXY` on Vercel. The Vercel runtime uses the platform-supplied client address header for request limits.

The PostgreSQL client disables prepared statements for the transaction pooler and verifies TLS certificates and hostnames. If your connection requires a specific CA, obtain the trusted certificate from Supabase and configure `PGSSLROOTCERT` to its bundled file. Do not work around a trust error by disabling verification or changing to `sslmode=disable/require`.

**Preview isolation:** use a separate empty Supabase project/bucket for ordinary Vercel Preview deployments. Set their credentials only for Preview. Leave `PUBLIC_BASE_URL` unset in Preview so the app uses Vercel's trusted deployment hostname. Never point routine test deployments at an active production database. The initial production candidate below is tested before changing domains and imports only owner-approved initial catalog data.

## 3. Upload without GitHub

The ZIP prepared for this task contains code/configuration only—no database, uploads, backups, passwords, `.env`, `.git`, or virtual environment. Download and extract it to a folder on your computer. Install a current Node.js LTS if you do not already have it. In that folder's terminal:

```sh
npx vercel login
npx vercel link
```

Choose your existing team/account and **link the existing project that already owns mikrofiber.shop**. Do not create a different project or remove the current domain. These commands authenticate through Vercel on your own computer; no token is needed in chat. Review the `vercel.json` included in this implementation; it routes requests through the Python entrypoint and bundles the templates, static files and original import source.

Then upload a production candidate without moving the domain:

```sh
npx vercel deploy --prod --skip-domain
```

Keep the deployment URL printed by the CLI. Its backend accepts both the canonical production origin and its own trusted Vercel deployment URL so you can test the candidate before domain promotion. Vercel controls the Python build and runtime; a successful local test is not proof that this cloud build has succeeded. Review the deployment build/runtime logs, without sharing secrets. The `.python-version` pins Python 3.12 and `requirements.txt` pins packages.

If your project has old custom build/output settings or another framework selected, clear those overrides for this Python deployment (Framework Preset **Other**, no custom static output directory). The included legacy builder configuration handles the Python entrypoint. Do not serve the entire repository as static files.

## 4. First login and initial products

1. Open the candidate deployment URL followed by `/admin`. Log in using `INITIAL_ADMIN_USERNAME` and the private password you set in Vercel. Only that preconfigured credential can create the first account; there is no public registration or default password. Once any account exists, bootstrap settings cannot create another or overwrite a stored account.
2. In Vercel, remove **both** `INITIAL_ADMIN_USERNAME` and `INITIAL_ADMIN_PASSWORD`. Redeploy another candidate with `--prod --skip-domain`; verify the same login still works from the saved database. Password hashes and sessions now live in PostgreSQL. Never remove the database's admin row to reset a password; use the documented CLI reset on a securely configured machine.
3. In admin **Məhsullar**, click **Orijinal dəsmalı idxal et**. It imports the original three photos, size options, prices and bundle discounts into the private database and persistent storage. Repeating it does not duplicate or overwrite the product. Verify real stock, private costs and availability before enabling ordering. You can also add products manually.
4. Check the storefront, `/mikrofiber-desmal.html`, mobile layout, category filters, private preview, uploads, logout/access protection and real storage URLs. Costs must be absent from `/api/catalog`. Generate a referral QR and verify it points to `https://mikrofiber.shop/?ref=CODE`.
5. Use a disposable staging database to test actual order submission, price/stock changes, confirmation, delivery, payment and commission reversals. Automated tests here use disposable local databases and a mocked storage service; **your real Supabase, Vercel build, and real WhatsApp opening still need this verification**. Do not confirm invented orders as real sales on an active shop.

If `/admin` says **Initial admin setup needs correction**, read the named setting. `INITIAL_ADMIN_USERNAME` must use 3–80 ASCII letters/digits/dots/underscores/hyphens; `owner` is a suitable value. Email addresses, quotes, spaces and non-ASCII letters are not accepted for this username. `INITIAL_ADMIN_PASSWORD` must be 14–1024 characters. Enter both values in **Production**, save and redeploy. The message never shows supplied values or a password. Invalid initial settings disable first-account creation while the storefront and existing accounts remain available. They do not enable public registration or overwrite stored users.

## 5. Promote after verification

When the candidate passes and you have verified inventory, photo persistence, database access and backups, switch the existing project's production domains to the candidate:

```sh
npx vercel promote YOUR_VERIFIED_DEPLOYMENT_URL
```

Alternatively use the deployment's **Promote to Production** action in Vercel. Preserve the previous deployment for rollback. Rolling back code does **not** roll back database writes; keep schema compatibility and reconcile orders. No promotion, DNS change or Vercel upload was performed by this task.

## Backups and restore

Supabase database backups do not automatically include stored photo objects, and availability/retention depends on the plan. Do not assume a free project has the backup policy your shop needs.

On a trusted computer/server with Python 3.12 and these requirements installed, securely load the same database/storage settings and run:

```sh
python -m mikrofiber backup --output /private/path/mikrofiber-backups
```

For PostgreSQL, the command creates a repeatable-read snapshot of all app tables plus referenced media, with media checksums and file mode `0600`. It is a portable `database.json` + WebP archive, not a SQLite file. Password hashes and customer details are sensitive; keep archives private and encrypted in independent storage. The command never prints credentials. Daily scheduling/off-server copies have **not** been activated for your account; configure them on a trusted scheduled runner or choose the provider's appropriate backup offering. Avoid public CI artifacts for customer-data backups.

To rehearse recovery, use a **new empty database and new empty media directory/bucket**, with those staging credentials loaded:

```sh
python -m mikrofiber restore-hosted --archive /private/path/mikrofiber-hosted-TIMESTAMP.tar.gz
```

Restore refuses a nonempty app database, verifies media checksums, never overwrites an existing photo object, preserves history/sequence values and revokes restored sessions. Test login, known order references, totals, commission ledger and photos before any production switch. Existing production data is never truncated by this command. Restore tests have been run against real local PostgreSQL 17; actual Supabase recovery remains an operator staging check.

## Costs and current limits

No paid services were purchased. Check your Vercel plan's commercial-use eligibility and Supabase's current storage, database, inactivity and backup limits before launch; an available free tier is not a guarantee of unlimited or production-grade service. This implementation adds no paid framework or external image-processing service.

The admin compresses selected photos to WebP and sends them individually under the Vercel request limit. The backend independently validates and re-encodes them. The existing app is aimed at a small catalog and serializes short write transactions for consistent stock/accounting. High traffic or large exports may require more capacity, pagination and an independent backup runner. No scheduled jobs are assumed to survive Vercel function execution.
