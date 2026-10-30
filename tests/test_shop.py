import copy
import io
import json
import sqlite3
import tarfile
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.security import generate_password_hash

from mikrofiber.app import create_app
from mikrofiber.__main__ import backup, seed
from mikrofiber.db import get_db, init_db, is_postgres


class ShopTest(unittest.TestCase):
    def database_options(self):
        return {'DATABASE': str(self.root / 'shop.sqlite3')}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app({'TESTING': True, 'DATA_DIR': str(self.root), **self.database_options(), 'STORAGE_BACKEND': 'local',
                               'MEDIA_DIR': str(self.root / 'media'), 'COOKIE_SECURE': False,
                               'PUBLIC_BASE_URL': 'http://localhost'})
        if is_postgres(self.app.config['DATABASE']):
            init_db(self.app.config['DATABASE'])
        self.client = self.app.test_client()
        with self.app.app_context():
            get_db().execute('INSERT INTO admins VALUES(?,?)', ('owner', generate_password_hash('test-only-long-password')))
        self.csrf = self.client.get('/api/admin/session').json['csrf']
        r = self.client.post('/api/admin/login', json={'username': 'owner', 'password': 'test-only-long-password'}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(r.status_code, 200)
        self.csrf = r.json['csrf']

    def tearDown(self):
        self.temp.cleanup()

    def write(self, method, path, data):
        return self.client.open(path, method=method, json=data, headers={'X-CSRF-Token': self.csrf})

    def input_product(self, **overrides):
        p = {'name': 'Mikrofiber dəsmal', 'description': 'Azərbaycanca məhsul təsviri', 'price': '12.99', 'cost': '4.27',
             'compare_at': '', 'category_id': None, 'status': 'published', 'available': True,
             'variants': [{'size': '50×60 sm', 'colour': 'Boz', 'price': '', 'cost': '3.81', 'stock': 10, 'available': True}]}
        p.update(overrides)
        return p

    def product(self, **overrides):
        r = self.write('POST', '/api/admin/products', self.input_product(**overrides))
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.json

    def edit_data(self, p):
        data = copy.deepcopy(p)
        for k in ('price', 'cost', 'compare_at'):
            data[k] = str(p[k] / 100) if p[k] is not None else ''
        for v in data['variants']:
            for k in ('price', 'cost', 'compare_at'):
                v[k] = str(v[k] / 100) if v[k] is not None else ''
        return data

    def order_data(self, p, quantity=1, referral=''):
        return {'idempotency_key': str(uuid.uuid4()), 'customer': {'name': 'Elvin Məmmədov', 'phone': '050 123 45 67',
                   'address': '28 May metrosu, çıxış 1', 'note': 'Zəng edin'}, 'delivery': 'metro', 'referral_code': referral,
                'expected_total': p['variants'][0]['effective_price'] * quantity,
                'items': [{'product_id': p['id'], 'variant_id': p['variants'][0]['id'], 'quantity': quantity}]}

    def submit(self, p, **kwargs):
        data = self.order_data(p, **kwargs)
        r = self.client.post('/api/orders', json=data)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        orders = self.client.get('/api/admin/orders').json['orders']
        return next(o for o in orders if o['reference'] == r.json['reference']), data, r.json

    def event(self, o, action, **kwargs):
        r = self.write('POST', f"/api/admin/orders/{o['id']}/events", {'version': o['version'], 'action': action, 'reason': 'Test operation reference', **kwargs})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.json

    def partner(self, **overrides):
        data = {'name': 'Usta Elvin', 'code': 'USTA01', 'commission': '2.00', 'active': True}
        data.update(overrides)
        r = self.write('POST', '/api/admin/partners', data)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return next(p for p in self.client.get('/api/admin/partners').json['partners'] if p['id'] == r.json['id'])

    def test_product_create_edit_stock_and_cost_privacy(self):
        p = self.product()
        public = self.client.get('/api/catalog')
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json['products'][0]['price'], 1299)
        self.assertNotIn('cost', public.get_data(as_text=True))
        self.assertNotIn('427', public.get_data(as_text=True))
        self.assertNotIn('381', public.get_data(as_text=True))
        self.assertEqual(p['cost'], 427)
        data = self.edit_data(p)
        data['price'] = '14.50'
        data['variants'][0]['stock'] = 7
        r = self.write('PUT', '/api/admin/products/' + p['id'], data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['variants'][0]['stock'], 7)
        self.assertEqual(r.json['price'], 1450)
        self.assertEqual(self.write('PUT', '/api/admin/products/' + p['id'], data).status_code, 409)
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['variants'][0]['stock'], 7)

    def test_hidden_draft_archived_preview_and_duplicate(self):
        for status in ('draft', 'hidden', 'archived'):
            p = self.product(status=status)
            self.assertNotIn(p['id'], [i['id'] for i in self.client.get('/api/catalog').json['products']])
            self.assertEqual(self.client.post('/api/orders', json=self.order_data(p)).status_code, 409)
            preview = self.client.get('/api/admin/products/' + p['id'] + '/preview')
            self.assertEqual(preview.status_code, 200)
            self.assertNotIn('cost', preview.get_data(as_text=True))
        p = self.product()
        duplicate = self.write('POST', '/api/admin/products/' + p['id'] + '/duplicate', {'version': p['version']})
        self.assertEqual(duplicate.status_code, 201)
        self.assertEqual(duplicate.json['status'], 'draft')
        self.assertFalse(duplicate.json['available'])
        self.assertEqual(duplicate.json['variants'][0]['stock'], 0)
        self.assertNotEqual(duplicate.json['variants'][0]['id'], p['variants'][0]['id'])

    def test_invalid_price_stock_and_variant_payloads_rejected(self):
        for value in ('-1', 'NaN', 'Infinity', '2.001', True, None, [], '1000001'):
            with self.subTest(price=value):
                self.assertEqual(self.write('POST', '/api/admin/products', self.input_product(price=value)).status_code, 400)
        for value in (-1, 1.5, True, '3', 1000001):
            data = self.input_product()
            data['variants'][0]['stock'] = value
            self.assertEqual(self.write('POST', '/api/admin/products', data).status_code, 400)
        data = self.input_product()
        data['variants'][0]['id'] = {}
        self.assertEqual(self.write('POST', '/api/admin/products', data).status_code, 400)
        data = self.input_product()
        data['variants'] *= 2
        self.assertEqual(self.write('POST', '/api/admin/products', data).status_code, 400)

    def test_auth_csrf_origin_logout_revocation(self):
        public = self.app.test_client()
        for path in ('/api/admin/products', '/api/admin/orders', '/api/admin/partners', '/api/admin/audit'):
            self.assertEqual(public.get(path).status_code, 401)
        self.assertEqual(public.post('/api/admin/products', json=self.input_product()).status_code, 401)
        self.assertEqual(self.client.post('/api/admin/products', json=self.input_product()).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/products', json=self.input_product(), headers={'X-CSRF-Token': self.csrf, 'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(public.post('/api/orders', json={}, headers={'Origin': 'https://attacker.example'}).status_code, 403)
        cookie = self.client.get_cookie('mf_session').value
        self.assertEqual(self.write('POST', '/api/admin/logout', {}).status_code, 200)
        public.set_cookie('mf_session', cookie)
        self.assertEqual(public.get('/api/admin/products').status_code, 401)
        self.assertIn("script-src 'self'", public.get('/').headers['Content-Security-Policy'])
        self.assertEqual(public.get('/seed/original.html').status_code, 404)
        self.assertEqual(public.get('/var/shop.sqlite3').status_code, 404)

    def test_login_rate_limiting_and_secure_cookie(self):
        c = self.app.test_client()
        csrf = c.get('/api/admin/session').json['csrf']
        for _ in range(9):  # successful setup login also counts
            self.assertEqual(c.post('/api/admin/login', json={'username': 'owner', 'password': 'wrong'}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/api/admin/login', json={'username': 'owner', 'password': 'wrong'}, headers={'X-CSRF-Token': csrf}).status_code, 429)
        self.app.config['COOKIE_SECURE'] = True
        r = self.app.test_client().get('/api/admin/session')
        self.assertIn('Secure', r.headers['Set-Cookie'])
        self.assertIn('HttpOnly', r.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', r.headers['Set-Cookie'])

    def test_password_whitespace_is_preserved_and_phone_config_is_used(self):
        with self.app.app_context():
            get_db().execute('UPDATE admins SET password_hash=? WHERE username=?', (generate_password_hash('  long secret password  '), 'owner'))
        c = self.app.test_client()
        csrf = c.get('/api/admin/session').json['csrf']
        r = c.post('/api/admin/login', json={'username': 'owner', 'password': '  long secret password  '}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(r.status_code, 200)
        self.app.config['WHATSAPP_NUMBER'] = '994501234567'
        self.assertIn('https://wa.me/994501234567', self.client.get('/').get_data(as_text=True))
        p = self.product()
        _, _, receipt = self.submit(p)
        self.assertIn('phone=994501234567&', receipt['whatsapp_url'])

    def test_order_snapshot_message_server_prices_and_idempotency(self):
        p = self.product()
        o, data, receipt = self.submit(p, quantity=2)
        self.assertEqual(o['sale_status'], 'submitted')
        self.assertEqual(o['fulfillment'], 'pending')
        self.assertEqual(o['payment'], 'unpaid')
        self.assertEqual(o['items'][0]['unit_price'], 1299)
        self.assertIn(o['reference'], receipt['message'])
        self.assertIn('Elvin Məmmədov', receipt['message'])
        self.assertIn('× 2', receipt['message'])
        self.assertIn('25.98 AZN', receipt['message'])
        self.assertNotIn('cost', json.dumps(receipt))
        self.assertTrue(receipt['whatsapp_url'].startswith('https://api.whatsapp.com/send?phone=994994350013&'))
        self.assertEqual(self.client.post('/api/orders', json=data).status_code, 200)
        self.assertEqual(len(self.client.get('/api/admin/orders').json['orders']), 1)
        changed = copy.deepcopy(data)
        changed['customer']['name'] = 'Other person'
        self.assertEqual(self.client.post('/api/orders', json=changed).status_code, 409)
        edit = self.edit_data(p)
        edit['price'] = '19.50'
        self.assertEqual(self.write('PUT', '/api/admin/products/' + p['id'], edit).status_code, 200)
        historical = self.client.get('/api/admin/orders/' + o['id']).json
        self.assertEqual(historical['total'], 2598)
        self.assertEqual(historical['items'][0]['unit_price'], 1299)
        self.assertEqual(self.client.post('/api/orders', json=data).json['total'], 2598)
        bad = self.order_data(p)
        bad['expected_total'] = 1
        bad['unit_price'] = 1
        self.assertEqual(self.client.post('/api/orders', json=bad).status_code, 409)

    def test_order_validation_availability_and_courier(self):
        p = self.product()
        for mutate in ('customer', 'quantity', 'stock', 'repeat', 'delivery'):
            data = self.order_data(p)
            if mutate == 'customer': data['customer']['phone'] = '123'
            if mutate == 'quantity': data['items'][0]['quantity'] = -1
            if mutate == 'stock': data['items'][0]['quantity'] = 11
            if mutate == 'repeat': data['items'] *= 2
            if mutate == 'delivery': data['delivery'] = 'free_fake'
            self.assertIn(self.client.post('/api/orders', json=data).status_code, (400, 409))
        data = self.order_data(p)
        data['delivery'] = 'courier'
        data['expected_total'] += 399
        self.assertEqual(self.client.post('/api/orders', json=data).json['total'], 1698)
        edit = self.edit_data(p)
        edit['available'] = False
        self.assertEqual(self.write('PUT', '/api/admin/products/' + p['id'], edit).status_code, 200)
        self.assertEqual(self.client.post('/api/orders', json=self.order_data(p)).status_code, 409)

    def test_multi_product_order_snapshots(self):
        p, q = self.product(), self.product(name='Şüşə üçün dəsmal', price='7.20')
        data = self.order_data(p)
        data['items'] += self.order_data(q, quantity=2)['items']
        data['expected_total'] += 1440
        r = self.client.post('/api/orders', json=data)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json['total'], 2739)
        self.assertIn('Şüşə üçün dəsmal', r.json['message'])
        self.assertEqual(len(self.client.get('/api/admin/orders').json['orders'][0]['items']), 2)

    def test_stock_only_deducted_at_confirmation_no_oversell_and_cancel_restore(self):
        p = self.product(variants=[{'size': '', 'colour': '', 'stock': 1, 'available': True}])
        first, _, _ = self.submit(p)
        second, _, _ = self.submit(p)
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['variants'][0]['stock'], 1)
        first = self.event(first, 'confirm')
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['variants'][0]['stock'], 0)
        bad = self.write('POST', f"/api/admin/orders/{second['id']}/events", {'action': 'confirm', 'version': second['version'], 'reason': 'No inventory'})
        self.assertEqual(bad.status_code, 409)
        first = self.event(first, 'cancel')
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['variants'][0]['stock'], 1)
        self.assertEqual(self.event(second, 'confirm')['sale_status'], 'confirmed')

    def test_referral_attribution_commission_snapshot_and_reversal(self):
        partner = self.partner()
        p = self.product()
        o, _, receipt = self.submit(p, referral='usta01')
        self.assertTrue(receipt['referral_verified'])
        self.assertEqual(o['partner_id'], partner['id'])
        self.assertEqual(o['commission_snapshot'], 200)
        self.assertEqual(o['ledger'], [])
        updated = {**partner, 'commission': '9.00', 'active': False}
        self.assertEqual(self.write('PUT', '/api/admin/partners/' + partner['id'], updated).status_code, 200)
        o = self.event(o, 'confirm')
        o = self.event(o, 'deliver')
        self.assertEqual(o['ledger'], [])
        o = self.event(o, 'mark_paid')
        self.assertEqual([(e['kind'], e['amount']) for e in o['ledger']], [('earned', 200)])
        o = self.event(o, 'pay_commission')
        self.assertEqual(o['ledger'][-1]['amount'], -200)
        o = self.event(o, 'refund')
        self.assertEqual(o['ledger'][-1]['kind'], 'reversed')
        self.assertEqual(sum(e['amount'] for e in o['ledger']), -200)
        o = self.event(o, 'return')
        self.assertEqual(self.client.get('/api/catalog').json['products'][0]['variants'][0]['stock'], 10)
        self.assertEqual(len(o['ledger']), 3)

    def test_unverified_inactive_and_ineligible_referrals_earn_nothing(self):
        self.partner(active=False)
        p = self.product()
        for code in ('UNKNOWN01', 'USTA01', ''):
            o, _, receipt = self.submit(p, referral=code)
            self.assertFalse(receipt['referral_verified'])
            self.assertIsNone(o['partner_id'])
            for action in ('confirm', 'mark_paid', 'deliver'): o = self.event(o, action)
            self.assertEqual(o['ledger'], [])
        active = self.partner(name='Other worker', code='WORKER02')
        o, _, _ = self.submit(p, referral=active['code'])
        o = self.event(o, 'eligibility', eligible=False)
        for action in ('confirm', 'mark_paid', 'deliver'): o = self.event(o, action)
        self.assertEqual(o['ledger'], [])
        o = self.event(o, 'eligibility', eligible=True)
        self.assertEqual(o['ledger'][0]['amount'], 200)
        o = self.event(o, 'eligibility', eligible=True)
        self.assertEqual(len(o['ledger']), 1)

    def test_categories_partners_qr_search_and_filters(self):
        c = self.write('POST', '/api/admin/categories', {'name': 'Avto'}).json
        p = self.product(category_id=c['id'])
        self.product(name='Digər məhsul', status='draft')
        self.assertEqual(len(self.client.get('/api/admin/products?status=published').json['products']), 1)
        self.assertEqual(len(self.client.get('/api/admin/products?category_id=' + c['id']).json['products']), 1)
        self.assertEqual(len(self.client.get('/api/admin/products?q=Dig').json['products']), 1)
        self.assertEqual(self.write('DELETE', '/api/admin/categories/' + c['id'], {}).status_code, 409)
        self.assertEqual(self.write('PUT', '/api/admin/categories/' + c['id'], {'name': 'Dəsmallar'}).status_code, 200)
        partner = self.partner()
        self.assertEqual(self.client.get('/api/referrals/usta01').json, {'code': 'USTA01', 'verified': True})
        qr = self.client.get('/api/admin/partners/' + partner['id'] + '/qr.svg')
        self.assertEqual(qr.status_code, 200)
        self.assertIn('<svg', qr.get_data(as_text=True))
        self.assertEqual(self.app.test_client().get('/api/admin/partners/' + partner['id'] + '/qr.svg').status_code, 401)
        self.assertEqual(self.write('POST', '/api/admin/partners', {'name': 'Another', 'code': 'usta01', 'commission': '3', 'active': True}).status_code, 409)

    def test_image_upload_reencode_privacy_and_duplicate(self):
        p = self.product()
        image = io.BytesIO()
        Image.new('RGB', (2000, 1000), 'green').save(image, 'PNG')
        image.seek(0)
        r = self.client.post('/api/admin/products/' + p['id'] + '/images', data={'version': str(p['version']), 'images': (image, 'arbitrary-name.png')}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        p = r.json
        im = p['images'][0]
        self.assertEqual(im['width'], 1600)
        self.assertEqual(im['height'], 800)
        media = self.client.get(im['url'])
        self.assertEqual(media.mimetype, 'image/webp')
        self.assertEqual(Image.open(io.BytesIO(media.data)).format, 'WEBP')
        invalid = self.client.post('/api/admin/products/' + p['id'] + '/images', data={'version': str(p['version']), 'images': (io.BytesIO(b'<svg onload="alert(1)"></svg>'), 'bad.svg')}, headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(invalid.status_code, 400)
        duplicated = self.write('POST', '/api/admin/products/' + p['id'] + '/duplicate', {'version': p['version']}).json
        self.assertEqual(duplicated['images'][0]['url'], im['url'])
        self.assertEqual(self.write('DELETE', '/api/admin/products/' + p['id'] + '/images/' + im['id'], {'version': p['version']}).status_code, 200)
        duplicate_media = self.client.get(duplicated['images'][0]['url'])
        self.assertEqual(duplicate_media.status_code, 200)
        duplicate_media.close()
        media.close()

    def test_audit_and_snapshot_immutability(self):
        p = self.product()
        o, _, _ = self.submit(p)
        with self.app.app_context():
            db = get_db()
            for query, args in [('DELETE FROM audit_events', ()), ('UPDATE order_items SET unit_price=1 WHERE order_id=?', (o['id'],)), ('UPDATE orders SET total=1 WHERE id=?', (o['id'],)), ('DELETE FROM orders WHERE id=?', (o['id'],))]:
                with self.assertRaises(sqlite3.IntegrityError): db.execute(query, args)
        events = self.client.get('/api/admin/audit').json['events']
        self.assertIn('created', [e['action'] for e in events])
        self.assertIn('submitted', [e['action'] for e in events])

    def test_backup_restore_includes_orders_images_and_admin(self):
        with self.app.app_context(): seed(self.app)
        p = self.product()
        self.submit(p)
        archive = backup(self.app, self.root / 'backups')
        restored = self.root / 'restored'
        with tarfile.open(archive) as f:
            f.extractall(restored, filter='data')
        db = sqlite3.connect(restored / 'shop.sqlite3')
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM admins').fetchone()[0], 1)
        files = db.execute('SELECT filename,thumbnail FROM images').fetchall()
        self.assertEqual(len(files), 3)
        for row in files:
            for name in row: self.assertTrue((restored / 'media' / name).is_file())
        db.close()
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_original_import_repeatable_and_bundle_rounding(self):
        seed(self.app)
        seed(self.app)
        p = self.client.get('/api/admin/products').json['products'][0]
        self.assertEqual(len(self.client.get('/api/admin/products').json['products']), 1)
        self.assertFalse(p['available'])
        self.assertEqual(len(p['images']), 3)
        data = self.edit_data(p)
        data['available'] = True
        data['variants'][0]['stock'] = 10
        p = self.write('PUT', '/api/admin/products/' + p['id'], data).json
        order = self.order_data(p, quantity=3)
        order['expected_total'] = 3312
        r = self.client.post('/api/orders', json=order)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json['total'], 3312)

    def test_parallel_order_retry_commits_one_request(self):
        p = self.product()
        data = self.order_data(p)
        barrier = threading.Barrier(2)
        def submit():
            with self.app.test_client() as client:
                barrier.wait()
                return client.post('/api/orders', json=data).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(results), [200, 201])
        self.assertEqual(len(self.client.get('/api/admin/orders').json['orders']), 1)

    def test_confirmation_is_atomic_and_stale_stock_edit_is_rejected(self):
        first = self.product(name='Birinci məhsul')
        second = self.product(name='İkinci məhsul')
        data = self.order_data(first)
        data['items'] += self.order_data(second)['items']
        data['expected_total'] *= 2
        self.assertEqual(self.client.post('/api/orders', json=data).status_code, 201)
        order = self.client.get('/api/admin/orders').json['orders'][0]
        edit = self.edit_data(second)
        edit['variants'][0]['stock'] = 0
        self.assertEqual(self.write('PUT', '/api/admin/products/' + second['id'], edit).status_code, 200)
        r = self.write('POST', '/api/admin/orders/' + order['id'] + '/events', {'version': order['version'], 'action': 'confirm', 'reason': 'No second item stock'})
        self.assertEqual(r.status_code, 409)
        # Failure on the second line rolls back any deduction on the first.
        self.assertEqual(self.client.get('/api/admin/products/' + first['id']).json['variants'][0]['stock'], 10)
        self.assertEqual(self.client.get('/api/admin/orders/' + order['id']).json['sale_status'], 'submitted')
        single, _, _ = self.submit(first)
        self.event(single, 'confirm')
        self.assertEqual(self.write('PUT', '/api/admin/products/' + first['id'], self.edit_data(first)).status_code, 409)
        # Azerbaijani uppercase search is not limited to SQLite's ASCII lower().
        self.assertEqual(len(self.client.get('/api/admin/products', query_string={'q': 'İKİNCİ'}).json['products']), 1)


if __name__ == '__main__':
    unittest.main()
