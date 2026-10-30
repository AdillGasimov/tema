import io
import json
import os
import tempfile
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from PIL import Image
from mikrofiber.app import create_app
from mikrofiber.db import postgres_options


class HostedTest(unittest.TestCase):
    def setUp(self):
        from test_shop import ShopTest
        self.fixture = ShopTest('runTest')
        self.fixture.setUp()
        self.app, self.client = self.fixture.app, self.fixture.client
        self.objects, self.requests = {}, []
        self.fail_upload = 0
        self.app.config.update(STORAGE_BACKEND='supabase',
            SUPABASE_URL='https://kopvvjbsrvwuteplmphp.supabase.co',
            SUPABASE_SERVICE_ROLE_KEY='test-only-server-secret', SUPABASE_STORAGE_BUCKET='product-images',
            STORAGE_HTTP_TRANSPORT=httpx.MockTransport(self.storage_service))

    def tearDown(self):
        self.fixture.tearDown()

    def storage_service(self, request):
        self.assertEqual(request.url.host, 'kopvvjbsrvwuteplmphp.supabase.co')
        self.assertEqual(request.headers['apikey'], 'test-only-server-secret')
        self.requests.append(request)
        if request.method == 'POST':
            posts = [r for r in self.requests if r.method == 'POST']
            if len(posts) == self.fail_upload:
                return httpx.Response(503)
            self.assertEqual(request.headers['content-type'], 'image/webp')
            self.assertEqual(request.headers['x-upsert'], 'false')
            if request.url.path in self.objects:
                return httpx.Response(409)
            self.objects[request.url.path] = request.content
            return httpx.Response(200, json={'Key': request.url.path})
        if request.method == 'GET':
            return httpx.Response(200, content=self.objects[request.url.path])
        if request.method == 'DELETE':
            data = json.loads(request.content)
            for name in data['prefixes']:
                self.objects.pop('/storage/v1/object/product-images/' + name, None)
            return httpx.Response(200, json=[])
        raise AssertionError('Unexpected storage operation')

    def upload(self, p):
        source = io.BytesIO()
        Image.new('RGB', (900, 600), 'navy').save(source, 'PNG')
        source.seek(0)
        return self.client.post('/api/admin/products/' + p['id'] + '/images',
            data={'version': str(p['version']), 'images': (source, 'photo.png')},
            headers={'X-CSRF-Token': self.fixture.csrf})

    def test_persistent_upload_redirect_and_no_secret_leak(self):
        p = self.fixture.product()
        response = self.upload(p)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.objects), 2)
        image = response.json['images'][0]
        self.assertFalse(list(Path(self.app.config['MEDIA_DIR']).glob('*.webp')))
        public = self.client.get('/api/catalog')
        self.assertNotIn('test-only-server-secret', public.get_data(as_text=True))
        self.assertNotIn('cost', public.get_data(as_text=True))
        redirect = self.client.get(image['url'])
        self.assertEqual(redirect.status_code, 302)
        self.assertTrue(redirect.location.startswith('https://kopvvjbsrvwuteplmphp.supabase.co/storage/v1/object/public/product-images/'))
        self.assertIn('https://kopvvjbsrvwuteplmphp.supabase.co', redirect.headers['Content-Security-Policy'])

    def test_partial_upload_failure_cleans_only_new_objects(self):
        p = self.fixture.product()
        self.fail_upload = 2
        response = self.upload(p)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.objects, {})
        self.assertEqual(self.client.get('/api/admin/products/' + p['id']).json['images'], [])
        deletion = next(r for r in self.requests if r.method == 'DELETE')
        self.assertEqual(len(json.loads(deletion.content)['prefixes']), 1)

    def test_stale_upload_does_not_leave_public_or_database_images(self):
        p = self.fixture.product()
        data = self.fixture.edit_data(p)
        self.assertEqual(self.fixture.write('PUT', '/api/admin/products/' + p['id'], data).status_code, 200)
        self.assertEqual(self.upload(p).status_code, 409)
        self.assertEqual(self.objects, {})

    def test_admin_import_uses_persistent_storage_and_is_repeatable(self):
        response = self.fixture.write('POST', '/api/admin/import-original', {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['imported'])
        self.assertEqual(len(self.objects), 6)
        response = self.fixture.write('POST', '/api/admin/import-original', {})
        self.assertFalse(response.json['imported'])
        self.assertEqual(len(self.objects), 6)
        p = self.client.get('/api/catalog').json['products'][0]
        self.assertFalse(p['available'])
        self.assertEqual(len(p['images']), 3)

    def test_postgres_tls_cannot_be_disabled_for_remote_host(self):
        options = postgres_options('postgresql://test:fake@db.example.com:6543/db?sslmode=disable')
        self.assertEqual(options['sslmode'], 'verify-full')
        self.assertTrue(options['sslrootcert'])

    def test_vercel_fails_closed_without_persistent_services(self):
        with patch.dict(os.environ, {'VERCEL': '1', 'DATABASE_URL': '', 'STORAGE_BACKEND': 'local'}):
            with self.assertRaisesRegex(ValueError, 'Vercel requires'):
                create_app()

    def test_initial_admin_one_time_setup_and_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = {'DATA_DIR': directory, 'DATABASE': str(root / 'shop.sqlite3'), 'MEDIA_DIR': str(root / 'media'),
                   'STORAGE_BACKEND': 'local', 'COOKIE_SECURE': False, 'PUBLIC_BASE_URL': 'http://localhost'}
            env = {'INITIAL_ADMIN_USERNAME': 'owner', 'INITIAL_ADMIN_PASSWORD': 'test-only-first-password'}
            with patch.dict(os.environ, env):
                app = create_app(cfg)
            c = app.test_client()
            csrf = c.get('/api/admin/session').json['csrf']
            response = c.post('/api/admin/login', json={'username': 'owner', 'password': env['INITIAL_ADMIN_PASSWORD']}, headers={'X-CSRF-Token': csrf})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('test-only-first-password', response.get_data(as_text=True))
            # Another configured bootstrap name cannot add/replace an account.
            with patch.dict(os.environ, {**env, 'INITIAL_ADMIN_USERNAME': 'another'}):
                other = create_app(cfg).test_client()
            csrf = other.get('/api/admin/session').json['csrf']
            response = other.post('/api/admin/login', json={'username': 'another', 'password': env['INITIAL_ADMIN_PASSWORD']}, headers={'X-CSRF-Token': csrf})
            self.assertEqual(response.status_code, 409)
            # The original password is persisted after both env values are removed.
            with patch.dict(os.environ, {'INITIAL_ADMIN_USERNAME': '', 'INITIAL_ADMIN_PASSWORD': ''}):
                normal = create_app(cfg).test_client()
            csrf = normal.get('/api/admin/session').json['csrf']
            self.assertEqual(normal.post('/api/admin/login', json={'username': 'owner', 'password': env['INITIAL_ADMIN_PASSWORD']}, headers={'X-CSRF-Token': csrf}).status_code, 200)

    def test_vercel_candidate_origin_and_platform_client_address(self):
        from mikrofiber.db import connect
        database = self.app.config['DATABASE']
        environment = {'VERCEL': '1', 'VERCEL_URL': 'candidate-mikrofiber.vercel.app',
            'PUBLIC_BASE_URL': 'https://mikrofiber.shop', 'COOKIE_SECURE': '1',
            'DATABASE_URL': 'postgresql://fake:fake@127.0.0.1:1/test',
            'STORAGE_BACKEND': 'supabase', 'SUPABASE_URL': 'https://kopvvjbsrvwuteplmphp.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'test-only-server-secret', 'INITIAL_ADMIN_USERNAME': '', 'INITIAL_ADMIN_PASSWORD': ''}
        with patch.dict(os.environ, environment), patch('mikrofiber.db.connect', side_effect=lambda _: connect(database)):
            app = create_app({'DATA_DIR': self.app.config['DATA_DIR'], 'MEDIA_DIR': self.app.config['MEDIA_DIR']})
            c = app.test_client()
            base = 'https://candidate-mikrofiber.vercel.app'
            r = c.get('/api/admin/session', base_url=base, headers={'X-Vercel-Forwarded-For': '192.0.2.10'})
            csrf = r.json['csrf']
            r = c.post('/api/admin/login', base_url=base, json={'username': 'owner', 'password': 'test-only-long-password'},
                headers={'X-CSRF-Token': csrf, 'Origin': base, 'X-Vercel-Forwarded-For': '192.0.2.10'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(c.post('/api/admin/products', base_url=base, json={},
                headers={'X-CSRF-Token': r.json['csrf'], 'Origin': 'https://attacker.example'}).status_code, 403)
        with self.app.app_context():
            from mikrofiber.db import get_db
            client = hashlib.sha256(b'192.0.2.10').hexdigest()
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM rate_limits WHERE client=? AND bucket='login'", (client,)).fetchone()[0], 1)
