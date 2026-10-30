# Setup, deployment, backup and recovery

**Your confirmed host is Vercel. Follow [VERCEL_SUPABASE.md](VERCEL_SUPABASE.md) for your deployment.** The instructions below describe the alternative single-server/SQLite setup, which remains usable for development or a future hosting change. No deployment or subscription has been purchased or performed here. Preserve current routes/files before any cutover.

## Runtime settings

| Setting | Purpose / production value |
| --- | --- |
| `PUBLIC_BASE_URL` | Exact public origin, e.g. `https://mikrofiber.shop`; no trailing path. Used for origin checks and QR links. Redirect `www` to this canonical host if appropriate. |
| `DATA_DIR` | Absolute persistent private directory, e.g. `/var/lib/mikrofiber`. Contains `shop.sqlite3` (and live WAL/SHM files) and `media/`. Never put it under a public web root. |
| `COOKIE_SECURE` | `1` in production (default); `0` only for local HTTP development. |
| `WHATSAPP_NUMBER` | International digits, default `994994350013`. |
| `DELIVERY_FEE_AZN` | Exact nonnegative decimal amount; default `3.99`. Metro pickup is free. |
| `TRUST_PROXY` | `1` only when Gunicorn is bound to loopback behind exactly one trusted reverse proxy that replaces forwarded headers. Otherwise leave unset/`0`. |

No API secrets or external service credentials are needed. Admin usernames/password hashes are stored in the private database. The password is set interactively using `create-admin`, not via a frontend variable, a default password, or a chat message. `.env.example` is a reference; the app does not auto-load `.env`.

## Example single-server deployment

These examples assume Linux with Python 3.12+, a service user `mikrofiber`, code installed at `/opt/mikrofiber`, a persistent data directory `/var/lib/mikrofiber`, and backup directory `/var/backups/mikrofiber`. Your host may manage processes differently. Keep the data directory stable across releases. Use a release directory or preserved copy of the old site for rollback.

1. Back up the current live site and identify any other routes/assets. Copy the prepared application and pinned `requirements.txt` to a new private release directory. Do not copy test databases, local `var`, temporary passwords, or `.venv` from a different machine.
2. Create a venv, install pinned packages, and configure the non-secret runtime settings from the table. Store `/etc/mikrofiber.env` outside the public tree. Restrict application-data and backup directories to the service user. Install using normal verified package sources; never disable TLS checks.
3. Run these commands **as the service user with the production environment loaded**, before starting the web process:

   ```sh
   cd /opt/mikrofiber
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python -m mikrofiber init
   .venv/bin/python -m mikrofiber import-original
   .venv/bin/python -m mikrofiber create-admin --username owner
   .venv/bin/python -m mikrofiber backup --output /var/backups/mikrofiber
   ```

   `init` and `import-original` can be repeated without deleting existing products/orders. Do not run the import against an unrelated existing database. The schema here is new and no prior production database was supplied.

4. Configure a process manager. Example `/etc/systemd/system/mikrofiber.service`:

   ```ini
   [Unit]
   Description=Mikrofiber storefront and admin
   After=network.target

   [Service]
   User=mikrofiber
   Group=mikrofiber
   WorkingDirectory=/opt/mikrofiber
   EnvironmentFile=/etc/mikrofiber.env
   ExecStart=/opt/mikrofiber/.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 60 wsgi:app
   Restart=on-failure
   UMask=0077
   NoNewPrivileges=true
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   ```

5. Put a TLS reverse proxy in front. For example, Caddy obtains certificates when DNS points to this host and ports 80/443 are reachable:

   ```caddyfile
   mikrofiber.shop {
       request_body {
           max_size 32MB
       }
       reverse_proxy 127.0.0.1:8000
   }
   www.mikrofiber.shop {
       redir https://mikrofiber.shop{uri} permanent
   }
   ```

   Do not configure a static `file_server` over the project or data directories. Serve the app through Gunicorn; it exposes only the intended static and media paths. If using nginx, preserve `Host`, replace trusted forwarded headers, permit the 32 MB multipart body, and proxy all app routes. Do not expose port 8000 directly. Start/enable the service using your host's documented process manager. The Flask `run` command is only for development.

6. Before switching traffic, verify `/api/catalog`, the landing page, `/mikrofiber-desmal.html`, `/admin` login/logout, private cost exclusion, upload persistence across a service restart, and an intentional test order with a test referral. Confirm its requested → confirmed → delivered → paid transitions and review the commission ledger. Do not treat test orders as actual sales. Test the WhatsApp link manually; browser automation here deliberately did not send a message.
7. Enter real stock, costs and availability for imported products. Verify QR links use the real canonical HTTPS domain. Ensure secure cookies work. Confirm a backup can be restored on staging and that the daily backup schedule is running. Only then switch the existing site routes/DNS as needed. Keep the old static deployment available for rollback, while retaining all new order data separately.

Costs depend on your plan: a Python-capable persistent server and independent backup storage may be paid. SQLite and local photos require no separate hosted database/storage plan. If your current host already supports this, no platform change may be necessary. A multi-instance/serverless deployment would require a different database/storage arrangement and is outside this initial implementation.

## Backups

```sh
cd /opt/mikrofiber
.venv/bin/python -m mikrofiber backup --output /var/backups/mikrofiber
```

Run with the same `DATA_DIR` as the app. The command uses SQLite's online backup API from a consistent read snapshot, checks database/foreign-key integrity, and bundles all referenced original-sized WebP files and thumbnails. Each archive has mode `0600`. It contains customer details and password hashes; treat it as sensitive. Media is immutable; removed references leave files on disk, so concurrent edits do not invalidate a backup. Archive creation fails instead of silently omitting a missing referenced image.

For daily automation, install both units below and enable the timer on the deployment host. These sample units have **not** been installed on production by this task.

`/etc/systemd/system/mikrofiber-backup.service`:

```ini
[Unit]
Description=Back up Mikrofiber database and photos

[Service]
Type=oneshot
User=mikrofiber
Group=mikrofiber
WorkingDirectory=/opt/mikrofiber
EnvironmentFile=/etc/mikrofiber.env
ExecStart=/opt/mikrofiber/.venv/bin/python -m mikrofiber backup --output /var/backups/mikrofiber
UMask=0077
```

`/etc/systemd/system/mikrofiber-backup.timer`:

```ini
[Unit]
Description=Daily Mikrofiber backup

[Timer]
OnCalendar=*-*-* 03:00:00 Asia/Baku
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mikrofiber-backup.timer
sudo systemctl start mikrofiber-backup.service
sudo systemctl status mikrofiber-backup.service
sudo systemctl list-timers mikrofiber-backup.timer
```

Choose a retention policy and monitor disk usage; the command intentionally does not delete old archives. Copy completed archives to independent, access-controlled storage and encrypt them according to your hosting facilities. A backup on the same disk does not protect against losing the server. No external storage credentials were supplied, so off-server copies and scheduling remain deployment steps.

## Recovery drill

1. Stop the web service (or restore first to a separate staging server). Preserve the current data directory and all WAL/SHM files as a rollback copy; never overwrite live SQLite files while Gunicorn is running.
2. Inspect a trusted backup archive, then extract it into a **new empty private directory**, e.g. `/var/lib/mikrofiber-restored`. It contains `shop.sqlite3` and `media/`. Never extract an untrusted archive or extract directly over live data.
3. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` with Python's `sqlite3` or the SQLite CLI. Clear restored sessions with `DELETE FROM sessions` so old backed-up sessions are revoked. Correct ownership/permissions for the service user.
4. Point a staging instance's `DATA_DIR` at the restored directory. Validate catalog images, admin login, known order/reference totals, partner attribution and audit/commission entries. This repository's automated backup test checks restored order, admin, integrity and all three imported media references.
5. With the web service stopped, switch `DATA_DIR` to the verified restored directory and restart. Never reuse WAL files from a different database snapshot. Record the restoration and reconcile any orders received after the backup time from your operational records/WhatsApp. A backup cannot restore newer data that it did not capture.

## Security and operational limits

- Keep HTTPS, server patches and dependency updates current; never serve `DATA_DIR`, archives, `.env`, `.git`, or the uploaded source as public static directories. Cost fields are filtered in public responses, not merely hidden with CSS.
- Admin sessions expire after 12 hours, are revocable on logout/password reset, and have `HttpOnly`/`SameSite=Strict` cookies. This version uses password authentication; MFA is not implemented. Use a strong unique password and restrict server access.
- Rate limits are persisted per client IP. Correct trusted-proxy configuration matters; shared networks may share a limit. Higher-volume deployments need tuning and monitoring.
- Back up before upgrades. Do not reset/delete the database to refresh product data. Use explicit migration scripts for future schema changes.
- Product preview requires an authenticated browser session and cannot place orders. Draft photos have random public media URLs; they are product photos, not a private document storage service. Do not upload confidential documents.
- The app records payment/delivery/payout facts entered by an admin. It cannot independently verify physical delivery, bank transfers, WhatsApp messages, or a worker's identity.
