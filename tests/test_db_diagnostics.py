import sqlite3
import os
import traceback
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import psycopg
import certifi

from mikrofiber.db import (connect, postgres_options, DatabaseAuthenticationError,
    DatabaseTLSVerificationError, DatabaseHostnameError, DatabaseNetworkError,
    DatabaseTimeoutError, DatabasePoolerIdentityError, DatabaseConfigurationError,
    DatabaseSchemaError, safe_database_error)


class DatabaseDiagnosticsTest(unittest.TestCase):
    def test_connection_categories_exclude_native_credentials_and_dsn(self):
        secret = 'fake-private-password-never-log-this'
        uri = 'postgresql://fake:fake@127.0.0.1:1/test'
        cases = [
            ('password authentication failed for user ' + secret, DatabaseAuthenticationError),
            ('SSL error: certificate verify failed ' + secret, DatabaseTLSVerificationError),
            ('root certificate file does not exist ' + secret, DatabaseTLSVerificationError),
            ('could not translate host name ' + secret, DatabaseHostnameError),
            ('Network is unreachable ' + secret, DatabaseNetworkError),
            ('connection refused ' + secret, DatabaseNetworkError),
            ('connection timeout expired ' + secret, DatabaseTimeoutError),
            ('Tenant or user not found ' + secret, DatabasePoolerIdentityError),
        ]
        for message, expected in cases:
            with self.subTest(category=expected.__name__):
                with patch('mikrofiber.db.psycopg.connect', side_effect=psycopg.OperationalError(message)):
                    try:
                        connect(uri)
                    except expected as error:
                        rendered = ''.join(traceback.format_exception(error))
                        self.assertNotIn(secret, rendered)
                        self.assertNotIn('postgresql://', rendered)
                        self.assertIsInstance(error, sqlite3.OperationalError)
                    else:
                        self.fail('Expected a safe connection error.')

    def test_sqlstate_classification(self):
        self.assertIsInstance(safe_database_error(psycopg.errors.InvalidPassword('private detail')), DatabaseAuthenticationError)
        self.assertIsInstance(safe_database_error(psycopg.errors.UndefinedTable('private detail')), DatabaseSchemaError)
        self.assertIsInstance(safe_database_error(psycopg.errors.InsufficientPrivilege('private detail')), DatabaseSchemaError)
        self.assertIsInstance(safe_database_error(psycopg.ProgrammingError('invalid URI private detail')), DatabaseConfigurationError)

    def test_missing_system_ca_uses_verified_certifi_bundle(self):
        with patch.dict(os.environ, {'PGSSLROOTCERT': '', 'SSL_CERT_FILE': ''}), patch('mikrofiber.db.ssl.get_default_verify_paths', return_value=SimpleNamespace(cafile=None)):
            options = postgres_options('postgresql://fake:fake@db.example.com:6543/postgres?sslmode=disable')
        self.assertEqual(options['sslmode'], 'verify-full')
        self.assertEqual(options['sslrootcert'], certifi.where())

    def test_known_operator_ca_selection_is_preserved(self):
        options = postgres_options('postgresql://fake:fake@db.example.com:6543/postgres?sslrootcert=provider-root.crt&sslmode=require')
        self.assertEqual(options['sslmode'], 'verify-full')
        self.assertEqual(options['sslrootcert'], 'provider-root.crt')

    def test_api_response_and_logs_retain_category_without_secret(self):
        from test_shop import ShopTest
        fixture = ShopTest('runTest')
        fixture.setUp()
        try:
            fixture.app.config['DATABASE'] = 'postgresql://fake:fake@127.0.0.1:1/test'
            with patch('mikrofiber.db.psycopg.connect', side_effect=psycopg.OperationalError('password authentication failed: fake-secret-value')):
                with self.assertLogs('mikrofiber.app', level='ERROR') as logs:
                    response = fixture.client.get('/api/admin/session')
            self.assertEqual(response.status_code, 503)
            self.assertIn('DatabaseAuthenticationError', ' '.join(logs.output))
            self.assertNotIn('fake-secret-value', ' '.join(logs.output) + response.get_data(as_text=True))
            self.assertNotIn('postgresql://', ' '.join(logs.output) + response.get_data(as_text=True))
        finally:
            fixture.tearDown()
