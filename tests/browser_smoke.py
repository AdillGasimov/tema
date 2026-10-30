"""Real Chromium workflow. Run with a Python that has Playwright; no WhatsApp message is sent."""
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv' / 'bin' / 'python'


def main():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'DATA_DIR': str(temp / 'data'), 'COOKIE_SECURE': '0', 'PUBLIC_BASE_URL': base, 'TRUST_PROXY': '0'}
        password = secrets.token_urlsafe(24)
        bootstrap = '''import sys,json
from mikrofiber.app import create_app
from mikrofiber.__main__ import seed
from mikrofiber.db import get_db
from werkzeug.security import generate_password_hash
from PIL import Image
from pathlib import Path
d=json.load(sys.stdin)
app=create_app()
with app.app_context(): get_db().execute('INSERT INTO admins VALUES(?,?)',('browser-test',generate_password_hash(d['password'])))
for i in (1,2): Image.new('RGB',(900,600),('navy' if i==1 else 'gray')).save(Path(d['directory'])/f'photo{i}.png')
'''
        subprocess.run([str(PYTHON), '-c', bootstrap], cwd=ROOT, env=env, input=json.dumps({'password': password, 'directory': str(temp)}), text=True, check=True)
        with (temp / 'server.log').open('w+') as log:
            server = subprocess.Popen([str(ROOT / '.venv/bin/gunicorn'), '--bind', f'127.0.0.1:{port}', '--workers', '2', 'wsgi:app'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(80):
                    try:
                        with urlopen(base + '/api/catalog', timeout=1) as response:
                            if response.status == 200: break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError('Gunicorn readiness failed')
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True, args=['--no-sandbox'])
                    context = browser.new_context(viewport={'width': 1280, 'height': 900})
                    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/admin')
                    page.locator('#username').fill('browser-test')
                    page.locator('#password').fill(password)
                    page.locator('#loginButton').click()
                    expect(page.locator('#dashboard')).to_be_visible()
                    expect(page.locator('.product-tile')).to_have_count(0)
                    page.locator('#importOriginal').click()
                    expect(page.locator('.product-tile')).to_have_count(1)
                    page.locator('#newProduct').click()
                    page.locator('#pName').fill('Şüşə üçün dəsmal')
                    page.locator('#pDescription').fill('Mavi mikrofiber. <script>alert("unsafe")</script> mətn kimi göstərilməlidir.')
                    page.locator('#pPrice').fill('8.50')
                    page.locator('#pCost').fill('3.25')
                    first = page.locator('.variant').nth(0)
                    first.locator('[name=size]').fill('40×40 sm')
                    first.locator('[name=colour]').fill('Mavi')
                    first.locator('[name=stock]').fill('8')
                    page.locator('#addVariant').click()
                    second = page.locator('.variant').nth(1)
                    second.locator('[name=size]').fill('60×60 sm')
                    second.locator('[name=colour]').fill('Boz')
                    second.locator('[name=stock]').fill('3')
                    second.locator('[name=price]').fill('13.00')
                    page.locator('#saveProduct').click()
                    expect(page.locator('#photosPanel')).to_be_visible()
                    page.locator('#photoFiles').set_input_files([str(temp / 'photo1.png'), str(temp / 'photo2.png')])
                    page.locator('#uploadPhotos').click()
                    expect(page.locator('#photoList .photo')).to_have_count(2)
                    with page.expect_popup() as popup:
                        page.locator('#previewProduct').click()
                    preview = popup.value
                    expect(preview.locator('#productName')).to_have_text('Şüşə üçün dəsmal')
                    expect(preview.locator('#previewBanner')).to_be_visible()
                    expect(preview.locator('#submitBtn')).to_be_disabled()
                    assert 'cost' not in json.dumps(preview.request.get(base + '/api/catalog').json())
                    preview.close()
                    page.locator('#pPrice').fill('9.00')
                    page.locator('.variant').nth(0).locator('[name=stock]').fill('7')
                    page.locator('#pStatus').select_option('published')
                    with page.expect_response(lambda r: r.request.method == 'PUT' and '/api/admin/products/' in r.url):
                        page.locator('#saveProduct').click()
                    expect(page.locator('#saveProduct')).to_be_enabled()
                    page.locator('[data-tab=partners]').click()
                    page.locator('#partnerName').fill('Avtoyuma işçisi Elvin')
                    page.locator('#partnerCode').fill('USTA01')
                    page.locator('#partnerCommission').fill('2.00')
                    page.locator('#partnerForm button.primary').click()
                    expect(page.locator('.partner')).to_have_count(1)
                    expect(page.locator('.partner img')).to_be_visible()
                    page.wait_for_function("document.querySelector('.partner img').naturalWidth > 0")
                    catalog = page.request.get(base + '/api/catalog').json()
                    assert 'cost' not in json.dumps(catalog)
                    product = next(p for p in catalog['products'] if p['name'] == 'Şüşə üçün dəsmal')
                    assert product['variants'][0]['stock'] == 7
                    assert product['variants'][0]['effective_price'] == 900

                    customer = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                    customer.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    customer.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    store = customer.new_page()
                    store.on('pageerror', lambda e: errors.append(str(e)))
                    store.add_init_script('window.open = (url) => {window.openedWhatsApp=url; return null;}')
                    store.goto(base + '/?ref=USTA01')
                    expect(store.locator('.product-card')).to_have_count(2)
                    store.wait_for_function("[...document.querySelectorAll('.product-card img')].every(i => i.complete && i.naturalWidth)")
                    assert store.locator('.product-card img').first.bounding_box()['height'] < 220
                    expect(store.locator('#submitBtn')).to_be_disabled()  # imported inventory unverified
                    store.locator(f'[data-product="{product["id"]}"]').click()
                    expect(store.locator('#productName')).to_have_text('Şüşə üçün dəsmal')
                    expect(store.locator('#pNow')).to_have_text('9.00 AZN')
                    expect(store.locator('#gTrack img')).to_have_count(2)
                    expect(store.locator('#productDescription')).to_contain_text('<script>')
                    assert not store.locator('#productDescription script').count()
                    assert not store.evaluate('document.documentElement.scrollWidth > window.innerWidth')
                    store.locator('[name=bundle][value="2"]').check(force=True)
                    store.locator('#addCart').click()
                    store.locator('[name=size]').nth(1).check(force=True)
                    store.locator('[name=bundle][value="1"]').check(force=True)
                    store.locator('#addCart').click()
                    expect(store.locator('.cart-row')).to_have_count(2)
                    store.locator('#dAddr').click()
                    expect(store.locator('#sum .sr.t')).to_contain_text('34.99 AZN')
                    store.locator('#inName').fill('Elvin Məmmədov')
                    store.locator('#inPhone').fill('050 123 45 67')
                    store.locator('#inAddr').fill('Bakı, Nizami küçəsi 12')
                    expect(store.locator('#referralStatus')).to_have_text('Referal kodu yoxlanılıb.')
                    with store.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/orders')) as response:
                        store.locator('#submitBtn').click()
                    assert response.value.status == 201
                    expect(store.locator('#done')).to_be_visible()
                    reference = store.locator('#orderRef').inner_text()
                    assert reference.startswith('MF-')
                    expect(store.locator('#submitBtn')).to_be_disabled()
                    store.wait_for_function('window.openedWhatsApp?.startsWith("https://api.whatsapp.com/send?")')
                    saved = page.request.get(base + '/api/admin/orders').json()['orders']
                    assert len(saved) == 1 and saved[0]['reference'] == reference
                    assert saved[0]['total'] == 3499 and saved[0]['partner_id']
                    assert saved[0]['sale_status'] == 'submitted' and saved[0]['payment'] == 'unpaid'
                    assert len(saved[0]['items']) == 2 and saved[0]['ledger'] == []
                    page.locator('[data-tab=orders]').click()
                    expect(page.locator('.order')).to_have_count(1)
                    page.locator('.order > summary').click()
                    for action in ('confirm', 'deliver', 'mark_paid'):
                        page.locator('[data-reason]').fill('Browser test, verified action')
                        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/events')) as response:
                            page.locator(f'[data-action="{action}"]').click()
                        assert response.value.status == 200
                        expect(page.locator('.order[open]')).to_have_count(1)
                        expect(page.locator('[data-reason]')).to_have_value('')
                    saved = page.request.get(base + '/api/admin/orders').json()['orders'][0]
                    assert saved['ledger'][0]['amount'] == 200
                    stock = page.request.get(base + '/api/catalog').json()['products']
                    variants = next(p for p in stock if p['id'] == product['id'])['variants']
                    assert [v['stock'] for v in variants] == [5, 2]
                    artifacts = ROOT / 'test-results'
                    artifacts.mkdir(exist_ok=True)
                    store.screenshot(path=str(artifacts / 'store-mobile.png'), full_page=True)
                    page.screenshot(path=str(artifacts / 'admin-orders.png'), full_page=True)
                    assert not errors, errors
                    browser.close()
                print('PASS: Chromium admin login, create/edit product, two variants, two uploads, private preview, publish, QR, mobile catalog/cart, saved WhatsApp request, verified referral, stock deduction and earned commission. No external message sent.')
            except BaseException:
                log.seek(0)
                print(log.read()[-5000:])
                raise
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait()


if __name__ == '__main__':
    main()
