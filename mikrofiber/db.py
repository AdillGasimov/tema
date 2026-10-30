import json
import sqlite3
import os
import re
import ssl
import certifi
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


class DatabaseConnectionError(sqlite3.OperationalError):
    """Safe operator-facing category; never retain the native message/DSN."""


class DatabaseAuthenticationError(DatabaseConnectionError):
    pass


class DatabaseTLSVerificationError(DatabaseConnectionError):
    pass


class DatabaseHostnameError(DatabaseConnectionError):
    pass


class DatabaseNetworkError(DatabaseConnectionError):
    pass


class DatabaseTimeoutError(DatabaseConnectionError):
    pass


class DatabasePoolerIdentityError(DatabaseConnectionError):
    pass


class DatabaseConfigurationError(DatabaseConnectionError):
    pass


class DatabaseSchemaError(DatabaseConnectionError):
    pass


def safe_database_error(error):
    # Inspect native details only to choose a fixed class. Never interpolate
    # their text into the resulting error, API response, traceback, or logs.
    message = str(error).lower()
    state = getattr(error, 'sqlstate', None)
    if 'tenant or user not found' in message:
        kind = DatabasePoolerIdentityError
    elif state in ('28P01', '28000') or 'password authentication failed' in message or 'authentication failed' in message:
        kind = DatabaseAuthenticationError
    elif ('certificate verify failed' in message or 'certificate verification failed' in message or
          'root certificate' in message or 'ssl error' in message or 'self-signed certificate' in message):
        kind = DatabaseTLSVerificationError
    elif ('could not translate host name' in message or 'name or service not known' in message or
          'nodename nor servname' in message or 'name resolution' in message):
        kind = DatabaseHostnameError
    elif 'timeout' in message or 'timed out' in message or state == '57014':
        kind = DatabaseTimeoutError
    elif 'network is unreachable' in message or 'connection refused' in message or 'no route to host' in message:
        kind = DatabaseNetworkError
    elif state in ('42P01', '3F000', '42501'):
        kind = DatabaseSchemaError
    elif state == '3D000' or isinstance(error, psycopg.ProgrammingError):
        kind = DatabaseConfigurationError
    else:
        kind = DatabaseConnectionError
    return kind('PostgreSQL operation unavailable. See the safe error category in the server log.')


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
        system_ca = ssl.get_default_verify_paths().cafile
        default_ca = system_ca if system_ca and Path(system_ca).is_file() else certifi.where()
        options.setdefault('sslrootcert', os.environ.get('PGSSLROOTCERT') or
                           os.environ.get('SSL_CERT_FILE') or default_ca)
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
        except psycopg.OperationalError as error:
            raise safe_database_error(error) from None
        except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName, psycopg.errors.InsufficientPrivilege) as error:
            raise safe_database_error(error) from None

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
        except psycopg.Error as error:
            raise safe_database_error(error) from None
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
