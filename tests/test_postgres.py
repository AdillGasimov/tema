"""Run the same shop behavior against a real disposable PostgreSQL database.

PG_TEST_URL must point at a local test server with permission to create databases.
No Supabase project or production database is touched.
"""
import json
import os
import tarfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import psycopg
from psycopg import sql

from test_shop import ShopTest as _ShopTest
from mikrofiber.app import create_app
from mikrofiber.__main__ import backup, seed
from mikrofiber.hosted_backup import restore_postgres
from mikrofiber.db import get_db, init_db, connect, DatabaseAuthenticationError

# Import the base without exposing another TestCase class to unittest discovery.
ShopBehavior = _ShopTest
del _ShopTest


@unittest.skipUnless(os.environ.get('PG_TEST_URL'), 'PG_TEST_URL not configured; no PostgreSQL checks executed')
class PostgresShopTest(ShopBehavior):
    def database_options(self):
        base = os.environ['PG_TEST_URL']
        parts = urlsplit(base)
        if parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('PostgreSQL integration tests require a disposable loopback test server.')
        self.dbname = 'mikrofiber_test_' + uuid.uuid4().hex
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.dbname)))
        return {'DATABASE': urlunsplit(parts._replace(path='/' + self.dbname))}

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            if getattr(self, 'dbname', None):
                with psycopg.connect(os.environ['PG_TEST_URL'], autocommit=True) as db:
                    db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.dbname)))

    def test_real_authentication_failure_has_a_safe_category(self):
        parts = urlsplit(self.app.config['DATABASE'])
        wrong = parts._replace(netloc=f'{parts.username}:intentionally-wrong-local-password@{parts.hostname}:{parts.port}')
        with self.assertRaises(DatabaseAuthenticationError) as failure:
            connect(urlunsplit(wrong))
        self.assertNotIn('intentionally-wrong-local-password', str(failure.exception))
        self.assertNotIn('postgresql://', str(failure.exception))

    def test_backup_restore_includes_orders_images_and_admin(self):
        seed(self.app)
        p = self.product()
        original_order, _, _ = self.submit(p)
        archive = backup(self.app, self.root / 'backups')
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as f:
            manifest = json.load(f.extractfile('database.json'))
            self.assertEqual(len(manifest['tables']['orders']), 1)
            self.assertEqual(len(manifest['media_sha256']), 6)
        restore_name = 'mikrofiber_restore_' + uuid.uuid4().hex
        parts = urlsplit(self.app.config['DATABASE'])
        with psycopg.connect(os.environ['PG_TEST_URL'], autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restore_name)))
        try:
            restored_app = create_app({'DATABASE': urlunsplit(parts._replace(path='/' + restore_name)),
                'DATA_DIR': str(self.root / 'restored'), 'MEDIA_DIR': str(self.root / 'restored/media'),
                'COOKIE_SECURE': False, 'PUBLIC_BASE_URL': 'http://localhost', 'STORAGE_BACKEND': 'local'})
            restore_postgres(restored_app, archive)
            with restored_app.app_context():
                db = get_db()
                self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT reference FROM orders').fetchone()[0], original_order['reference'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM admins').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)
                for im in db.execute('SELECT filename,thumbnail FROM images'):
                    for key in ('filename', 'thumbnail'):
                        self.assertTrue(Path(restored_app.config['MEDIA_DIR'], im[key]).is_file())
            # Non-empty restores are rejected before overwriting any data/media.
            with self.assertRaisesRegex(ValueError, 'not empty'):
                restore_postgres(restored_app, archive)
        finally:
            with psycopg.connect(os.environ['PG_TEST_URL'], autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(restore_name)))

    def test_private_schema_and_repeatable_migration(self):
        self.product()
        init_db(self.app.config['DATABASE'])
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM products').fetchone()[0], 1)
            tables = db.raw.execute("SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='mikrofiber'").fetchall()
            self.assertEqual(len(tables), 12)
            self.assertTrue(all(t['rowsecurity'] for t in tables))
            # A public/browser role has neither schema nor table access.
            role = 'anon_test_' + uuid.uuid4().hex
            db.raw.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
            try:
                db.raw.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.raw.execute('SELECT cost FROM mikrofiber.products')
            finally:
                db.raw.execute('RESET ROLE')
                db.raw.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

    def test_sql_editor_setup_is_atomic_and_independent_of_search_path(self):
        name = 'mikrofiber_setup_' + uuid.uuid4().hex
        base = os.environ['PG_TEST_URL']
        parts = urlsplit(base)
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            script = (Path(__file__).resolve().parent.parent / 'mikrofiber/schema_postgres.sql').read_text()
            with psycopg.connect(urlunsplit(parts._replace(path='/' + name)), autocommit=True) as db:
                db.execute('SET search_path=pg_catalog')
                db.execute(script, prepare=False)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='mikrofiber'").fetchone()[0], 12)
                db.execute("INSERT INTO mikrofiber.categories VALUES('preserved','Existing category')")
                db.execute('SET search_path=public,pg_catalog')
                db.execute(script, prepare=False)
                self.assertEqual(db.execute("SELECT name FROM mikrofiber.categories WHERE id='preserved'").fetchone()[0], 'Existing category')
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0], 0)
        finally:
            with psycopg.connect(base, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


# unittest loads every TestCase global, including imported aliases.
del ShopBehavior
