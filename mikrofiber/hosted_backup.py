"""Portable consistent PostgreSQL + media archives, usable without pg_dump."""
import hashlib
import io
import json
import os
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from .db import Postgres, connect, get_db, init_db, is_postgres, transaction
from .storage import download_image, persist_image, discard_new_image


def _add(archive, name, content):
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(content), 0o600
    archive.addfile(info, io.BytesIO(content))


def backup_postgres(app, destination):
    destination = Path(destination).resolve()
    root = Path(__file__).resolve().parent.parent
    public = (root / 'static').resolve()
    media = Path(app.config['MEDIA_DIR']).resolve()
    if destination == public or public in destination.parents or destination == media or media in destination.parents:
        raise ValueError('Backups must be private, outside publicly served directories.')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = destination / ('mikrofiber-hosted-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.tar.gz')
    db = connect(app.config['DATABASE'])
    try:
        db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        tables = {}
        for table in Postgres.tables:
            ordering = ' ORDER BY rowid' if table in ('variants', 'images', 'orders', 'order_items') else (' ORDER BY sequence' if table in ('audit_events', 'commission_ledger') else '')
            tables[table] = [dict(row) for row in db.execute('SELECT * FROM ' + table + ordering)]
        manifest = {'format': 'mikrofiber-postgres-v1', 'tables': tables, 'media_sha256': {}}
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with app.app_context(), os.fdopen(descriptor, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
            files = {im[key] for im in tables['images'] for key in ('filename', 'thumbnail')}
            for name in sorted(files):
                content = download_image(name)
                manifest['media_sha256'][name] = hashlib.sha256(content).hexdigest()
                _add(archive, 'media/' + name, content)
            _add(archive, 'database.json', json.dumps(manifest, ensure_ascii=False).encode())
        db.commit()
        return filename
    except BaseException:
        filename.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def restore_postgres(app, archive_path):
    """Refuse all non-empty targets. No table is truncated or overwritten."""
    if not is_postgres(app.config['DATABASE']):
        raise ValueError('restore-hosted requires a new PostgreSQL target.')
    init_db(app.config['DATABASE'])
    created = []
    with app.app_context(), tarfile.open(archive_path, 'r:gz') as archive:
        member = archive.getmember('database.json')
        if not member.isfile():
            raise ValueError('Invalid backup manifest.')
        manifest = json.load(archive.extractfile(member))
        if manifest.get('format') != 'mikrofiber-postgres-v1' or set(manifest.get('tables', {})) != set(Postgres.tables):
            raise ValueError('Unsupported backup format.')
        tables = manifest['tables']
        try:
            with transaction() as db:
                if any(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in Postgres.tables):
                    raise ValueError('Restore refused: target database is not empty. Existing data was retained.')
                for original in tables['images']:
                    image = dict(original)
                    image['_created_local'] = []
                    if not all(re.fullmatch(r'[a-f0-9]{32}(?:-small)?\.webp', image[k]) for k in ('filename', 'thumbnail')):
                        raise ValueError('Invalid image filename in backup.')
                    # Duplicates share images. Upload each immutable pair only once.
                    if any(i['filename'] == image['filename'] for i in created):
                        continue
                    created.append(image)
                    for field in ('filename', 'thumbnail'):
                        name = image[field]
                        content = archive.extractfile('media/' + name).read()
                        if hashlib.sha256(content).hexdigest() != manifest['media_sha256'].get(name):
                            raise ValueError('Backup media checksum failed.')
                        path = Path(app.config['MEDIA_DIR'], name)
                        with path.open('xb') as output:
                            image['_created_local'].append(name)
                            output.write(content)
                    persist_image(image)
                for table in Postgres.tables:
                    allowed = {r[0] for r in db.raw.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s', ('mikrofiber', table))}
                    for row in tables[table]:
                        columns = list(row)
                        if not columns or not set(columns) <= allowed or '_insertion_sequence' in columns:
                            raise ValueError('Invalid backup columns.')
                        names = ','.join('"' + c + '"' for c in columns)
                        override = ' OVERRIDING SYSTEM VALUE' if table in ('audit_events', 'commission_ledger') else ''
                        db.execute('INSERT INTO ' + table + '(' + names + ')' + override + ' VALUES(' + ','.join('?' for _ in columns) + ')', tuple(row[c] for c in columns))
                for table in ('audit_events', 'commission_ledger'):
                    db.execute("SELECT setval(pg_get_serial_sequence('mikrofiber." + table + "','sequence'), COALESCE((SELECT MAX(sequence) FROM " + table + "),0)+1, false)")
                db.execute('DELETE FROM sessions')
        except BaseException:
            for image in created:
                discard_new_image(image)
            raise
