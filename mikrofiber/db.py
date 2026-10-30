import json
import sqlite3
import os
import re
import ssl
from collections.abc import Mapping
from decimal import Decimal
import psycopg
from psycopg.conninfo import conninfo_to_dict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, g


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def is_postgres(path):
    return str(path).startswith(('postgres://', 'postgresql://'))


class Row(Mapping):
    """Named records with the numeric access used by SQLite aggregate queries."""
    def __init__(self, names, values):
        self.values = tuple(int(v) if isinstance(v, Decimal) and v == v.to_integral_value() else v
                            for n, v in zip(names, values) if n != '_insertion_sequence')
        self.names = tuple(n for n in names if n != '_insertion_sequence')
        self.data = dict(zip(self.names, self.values))

    def __getitem__(self, key):
        return self.values[key] if isinstance(key, int) else self.data[key]

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(names, values)


def postgres_options(url):
    options = conninfo_to_dict(url)
    host = options.get('host', '')
    # Production always verifies both certificate chain and hostname. Local tests
    # use a disposable loopback PostgreSQL instance without TLS.
    if host not in ('127.0.0.1', 'localhost', '::1'):
        options['sslmode'] = 'verify-full'
        options.setdefault('sslrootcert', os.environ.get('PGSSLROOTCERT') or
                           os.environ.get('SSL_CERT_FILE') or ssl.get_default_verify_paths().cafile)
        if not options.get('sslrootcert'):
            raise ValueError('A trusted PostgreSQL CA bundle is required.')
    options.setdefault('connect_timeout', '10')
    return options


class Postgres:
    """Small SQL dialect adapter; application queries remain parameterized."""
    tables = ('admins', 'sessions', 'rate_limits', 'categories', 'products', 'variants', 'images',
              'partners', 'orders', 'order_items', 'audit_events', 'commission_ledger')

    def __init__(self, url):
        self.raw = psycopg.connect(**postgres_options(url), autocommit=True,
                                   prepare_threshold=None, row_factory=row_factory)

    def execute(self, query, params=None):
        query = re.sub(r'\browid\b', '_insertion_sequence', query)
        query = query.replace('instr(', 'strpos(')
        query = re.sub(r'\b(FROM|JOIN|UPDATE|INTO)\s+(' + '|'.join(self.tables) + r')\b',
                       lambda m: m[1] + ' mikrofiber.' + m[2], query, flags=re.I)
        query = query.replace('?', '%s')
        try:
            return self.raw.execute(query, params, prepare=False)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError('Database constraint rejected the operation') from None
        except psycopg.OperationalError:
            raise sqlite3.OperationalError('PostgreSQL operation unavailable') from None

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect(path):
    if is_postgres(path):
        try:
            return Postgres(path)
        except psycopg.OperationalError:
            raise sqlite3.OperationalError('PostgreSQL connection unavailable') from None
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    return db


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def init_db(path):
    db = connect(path)
    try:
        if is_postgres(path):
            db.raw.execute(Path(__file__).with_name('schema_postgres.sql').read_text(), prepare=False)
        else:
            db.executescript(Path(__file__).with_name('schema.sql').read_text())
    finally:
        db.close()


@contextmanager
def transaction():
    db = get_db()
    db.execute('BEGIN' if isinstance(db, Postgres) else 'BEGIN IMMEDIATE')
    try:
        if isinstance(db, Postgres):
            # Preserve SQLite's write serialization for stock, retry keys, and
            # rate limits across independent Vercel instances. Transaction-scoped
            # advisory locks work through the Supabase transaction pooler.
            db.execute('SELECT pg_advisory_xact_lock(736492103)')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def audit(db, kind, identity, actor, action, detail):
    db.execute('INSERT INTO audit_events(entity_type,entity_id,actor,action,detail,created_at) VALUES(?,?,?,?,?,?)',
               (kind, identity, actor, action, json.dumps(detail, ensure_ascii=False, sort_keys=True), now()))
