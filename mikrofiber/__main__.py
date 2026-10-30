import argparse
import base64
import getpass
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.security import generate_password_hash
from .app import ROOT, create_app
from .catalog import save_product, uid
from .db import audit, connect, get_db, init_db, is_postgres, now, transaction
from .images import store_image
from .storage import persist_image, discard_new_image


def backup(app, destination):
    if is_postgres(app.config['DATABASE']):
        from .hosted_backup import backup_postgres
        return backup_postgres(app, destination)
    destination = Path(destination).resolve()
    media = Path(app.config['MEDIA_DIR']).resolve()
    if destination == media or media in destination.parents or ROOT / 'static' == destination or ROOT / 'static' in destination.parents:
        raise ValueError('Backups must be outside publicly served directories.')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = destination / ('mikrofiber-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.tar.gz')
    source = connect(app.config['DATABASE'])
    try:
        # Freeze a consistent read snapshot. Media is immutable and never removed on edits.
        source.execute('BEGIN')
        files = source.execute('SELECT DISTINCT filename,thumbnail FROM images').fetchall()
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / 'shop.sqlite3'
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('Backup database integrity failed')
            finally:
                target.close()
            snapshot.chmod(0o600)
            # Exclusive creation and restrictive permissions before writing sensitive bytes.
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
                archive.add(snapshot, arcname='shop.sqlite3')
                for name in sorted({f for row in files for f in row}):
                    archive.add(media / name, arcname='media/' + name)
        return filename
    except BaseException:
        filename.unlink(missing_ok=True)
        raise
    finally:
        source.close()


from .import_original import seed


def main():
    parser = argparse.ArgumentParser(description='Mikrofiber setup and operations')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('import-original')
    admin = sub.add_parser('create-admin')
    admin.add_argument('--username', default='admin')
    b = sub.add_parser('backup')
    b.add_argument('--output', required=True)
    restore = sub.add_parser('restore-hosted')
    restore.add_argument('--archive', required=True)
    run = sub.add_parser('run')
    run.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    app = create_app()
    if args.command == 'init':
        init_db(app.config['DATABASE'])
        print('Database initialized. Existing data retained.')
    elif args.command == 'import-original':
        with app.app_context():
            if get_db().execute('SELECT id FROM products WHERE legacy_towel=1').fetchone():
                print('Original towel already imported; no data changed.')
                return
        seed(app)
    elif args.command == 'create-admin':
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', args.username):
            parser.error('Username must be 3–80 ASCII letters, digits, dots, hyphens or underscores.')
        password = getpass.getpass('New admin password (at least 14 characters): ')
        if len(password) < 14 or len(password) > 1024:
            parser.error('Password must contain 14–1024 characters.')
        if password != getpass.getpass('Repeat password: '):
            parser.error('Passwords do not match.')
        with app.app_context(), transaction() as db:
            db.execute('INSERT INTO admins VALUES(?,?) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash', (args.username, generate_password_hash(password)))
            db.execute('DELETE FROM sessions WHERE username=?', (args.username,))
            audit(db, 'admin', args.username, 'server-cli', 'password_set', {})
        print('Admin saved; previous sessions revoked. No default password is supplied.')
    elif args.command == 'backup':
        print(backup(app, args.output))
    elif args.command == 'restore-hosted':
        from .hosted_backup import restore_postgres
        restore_postgres(app, args.archive)
        print('Restored to the empty hosted database and media target. All old sessions revoked.')
    elif args.command == 'run':
        app.run(host='127.0.0.1', port=args.port, debug=False)


if __name__ == '__main__':
    main()
