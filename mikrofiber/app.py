import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import io
import ipaddress
import qrcode
import qrcode.image.svg
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, make_response, render_template, request, send_from_directory, redirect
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from .catalog import boolean, money, product_json, require_version, save_product, text, uid
from .db import audit, get_db, init_db, is_postgres, now, transaction
from .images import store_image
from .storage import StorageError, validate_storage, remote, media_url, persist_image, discard_new_image
from .orders import create_order, normalize_code, order_json, update_order

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(__name__, static_folder=str(ROOT / 'static'), template_folder=str(ROOT / 'templates'))
    on_vercel = os.environ.get('VERCEL') == '1'
    default_origin = 'http://localhost:8000'
    if on_vercel and os.environ.get('VERCEL_URL'):
        default_origin = 'https://' + os.environ['VERCEL_URL']
    data_dir = Path(os.environ.get('DATA_DIR', '/tmp/mikrofiber' if on_vercel else str(ROOT / 'var'))).resolve()
    app.config.update(DATA_DIR=str(data_dir), DATABASE=os.environ.get('DATABASE_URL') or str(data_dir / 'shop.sqlite3'),
                      MEDIA_DIR=str(data_dir / 'media'), COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1') == '1',
                      PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', default_origin).rstrip('/'),
                      WHATSAPP_NUMBER=os.environ.get('WHATSAPP_NUMBER', '994994350013'),
                      DELIVERY_FEE=399, MAX_CONTENT_LENGTH=(4 if on_vercel else 32) * 1024 * 1024,
                      STORAGE_BACKEND=os.environ.get('STORAGE_BACKEND', 'supabase' if on_vercel else 'local'),
                      SUPABASE_URL=os.environ.get('SUPABASE_URL', '').rstrip('/'),
                      SUPABASE_SERVICE_ROLE_KEY=os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''),
                      SUPABASE_STORAGE_BUCKET=os.environ.get('SUPABASE_STORAGE_BUCKET', 'product-images'),
                      MAX_FORM_MEMORY_SIZE=100000, MAX_FORM_PARTS=30)
    if config:
        app.config.update(config)
    if on_vercel and not (is_postgres(app.config['DATABASE']) and app.config['STORAGE_BACKEND'] == 'supabase'):
        raise ValueError('Vercel requires DATABASE_URL (PostgreSQL) and Supabase image storage; local disk is not persistent.')
    validate_storage(app.config)
    base = urlsplit(app.config['PUBLIC_BASE_URL'])
    if base.scheme not in ('http', 'https') or not base.netloc or base.path or base.query or base.fragment or base.username:
        raise ValueError('PUBLIC_BASE_URL must be an http(s) origin without a path or credentials.')
    if on_vercel and (base.scheme != 'https' or not app.config['COOKIE_SECURE']):
        raise ValueError('Vercel deployments require HTTPS and COOKIE_SECURE=1.')
    if not re.fullmatch(r'\d{9,15}', app.config['WHATSAPP_NUMBER']):
        raise ValueError('WHATSAPP_NUMBER must contain only international phone digits.')
    # Read a non-secret fee override through the same exact decimal validation as the API.
    with app.app_context():
        if os.environ.get('DELIVERY_FEE_AZN'):
            app.config['DELIVERY_FEE'] = money(os.environ['DELIVERY_FEE_AZN'], 'Delivery fee')
    Path(app.config['DATA_DIR']).mkdir(parents=True, exist_ok=True, mode=0o700)
    Path(app.config['MEDIA_DIR']).mkdir(parents=True, exist_ok=True, mode=0o700)
    if not is_postgres(app.config['DATABASE']):
        init_db(app.config['DATABASE'])
        os.chmod(app.config['DATABASE'], 0o600)
    # Hosted schema initialization is an explicit one-time operator action, not
    # a cold-start side effect. Never create/reset live tables on a web request.
    if os.environ.get('TRUST_PROXY') == '1':
        # Enable only behind exactly one trusted reverse proxy; bind Gunicorn to loopback.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    initial_username = os.environ.get('INITIAL_ADMIN_USERNAME', '')
    initial_password = os.environ.get('INITIAL_ADMIN_PASSWORD', '')
    initial_hash = None
    if initial_username or initial_password:
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', initial_username) or not 14 <= len(initial_password) <= 1024:
            raise ValueError('INITIAL_ADMIN_USERNAME and a strong 14–1024 character INITIAL_ADMIN_PASSWORD must both be configured.')
        initial_hash = generate_password_hash(initial_password)

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        app.logger.warning('Database constraint rejected an operation: %s', type(error).__name__)
        return jsonify(error='Əməliyyat məlumat məhdudiyyəti ilə ziddiyyət təşkil edir.'), 409

    @app.errorhandler(sqlite3.OperationalError)
    def db_unavailable(error):
        app.logger.error('Database unavailable: %s', type(error).__name__)
        return jsonify(error='Məlumat bazası hazırda əlçatan deyil. Bir az sonra yenidən yoxlayın.'), 503

    @app.errorhandler(StorageError)
    def storage_unavailable(error):
        app.logger.warning('Persistent photo storage operation failed.')
        return jsonify(error='Şəkil yaddaşı hazırda əlçatan deyil. Yenidən yoxlayın.'), 503

    @app.after_request
    def secure_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # No inline scripts or event handlers; CSS from the original page is retained.
        image_origin = (' ' + app.config['SUPABASE_URL']) if app.config['STORAGE_BACKEND'] == 'supabase' else ''
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' blob: data:" + image_origin + "; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if app.config['COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith('/api/') or request.path.startswith('/admin'):
            response.headers['Cache-Control'] = 'no-store'
        elif request.path.startswith('/media/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'no-cache'
        return response

    def json_body():
        if not request.is_json:
            abort(415, 'JSON göndərin.')
        if request.content_length and request.content_length > 256 * 1024:
            abort(413)
        data = request.get_json()
        if not isinstance(data, dict):
            abort(400)
        return data

    def same_origin():
        origin = request.headers.get('Origin')
        allowed_origins = {app.config['PUBLIC_BASE_URL']}
        # Allow testing a new immutable Vercel deployment before promoting its
        # domain. This is a platform-provided hostname, never the request Host.
        deployment_host = os.environ.get('VERCEL_URL', '') if on_vercel else ''
        if re.fullmatch(r'[a-z0-9.-]+\.vercel\.app', deployment_host):
            allowed_origins.add('https://' + deployment_host)
        if origin and origin not in allowed_origins:
            abort(403, 'Sorğunun mənbəyi uyğun deyil.')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403)

    def session_row():
        token = request.cookies.get('mf_session', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        return get_db().execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',
                                (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()

    def csrf_session(admin=False):
        same_origin()
        row = session_row()
        if not row or (admin and not row['username']):
            abort(401, 'Daxil olun.')
        token = request.headers.get('X-CSRF-Token', '')
        if not hmac.compare_digest(token, row['csrf']):
            abort(403, 'Sessiya yoxlanışı uğursuz oldu. Səhifəni yeniləyin.')
        return row

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            row = session_row()
            if not row or not row['username']:
                abort(401, 'Daxil olun.')
            if request.method not in ('GET', 'HEAD'):
                csrf_session(admin=True)
            g.actor = row['username']
            return fn(*args, **kwargs)
        return wrapped

    def new_session(username=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = int(time.time()) + (43200 if username else 3600)
        db = get_db()
        db.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), csrf, username, expires))
        response = jsonify(authenticated=bool(username), username=username, csrf=csrf)
        response.set_cookie('mf_session', token, max_age=43200 if username else 3600, secure=app.config['COOKIE_SECURE'], httponly=True, samesite='Strict', path='/')
        return response

    def rate_limit(bucket, maximum, seconds):
        # Persist across workers/restarts. Proxy client IP is trusted only with TRUST_PROXY=1.
        address = request.remote_addr or 'unknown'
        if on_vercel:
            # Vercel sets this trusted platform header; do not enable this on
            # directly exposed hosts or accept arbitrary X-Forwarded-For values.
            forwarded = request.headers.get('X-Vercel-Forwarded-For', '').split(',')[0].strip()
            try:
                address = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        client = hashlib.sha256(address.encode()).hexdigest()
        with transaction() as db:
            stamp = int(time.time())
            db.execute('DELETE FROM rate_limits WHERE happened<?', (stamp - 86400,))
            count = db.execute('SELECT COUNT(*) FROM rate_limits WHERE bucket=? AND client=? AND happened>?', (bucket, client, stamp - seconds)).fetchone()[0]
            if count >= maximum:
                abort(429, 'Çox sayda cəhd. Bir az sonra yenidən yoxlayın.')
            db.execute('INSERT INTO rate_limits VALUES(?,?,?)', (bucket, client, stamp))

    @app.get('/')
    @app.get('/mikrofiber-desmal.html')
    def index():
        return render_template('index.html', whatsapp_number=app.config['WHATSAPP_NUMBER'])

    @app.get('/admin')
    @app.get('/admin/')
    def admin_page():
        response = make_response(render_template('admin.html'))
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/robots.txt')
    def robots():
        return 'User-agent: *\nDisallow: /admin\nDisallow: /api/\n', 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.get('/media/<filename>')
    def media(filename):
        if not re.fullmatch(r'[0-9a-f]{32}(?:-small)?\.webp', filename):
            abort(404)
        if remote():
            return redirect(media_url(filename), code=302)
        return send_from_directory(app.config['MEDIA_DIR'], filename, mimetype='image/webp', conditional=True)

    @app.get('/api/catalog')
    def catalog():
        db = get_db()
        return jsonify(products=[product_json(db, p) for p in db.execute("SELECT * FROM products WHERE status='published' ORDER BY legacy_towel DESC,created_at,id")],
                       categories=[dict(c) for c in db.execute('SELECT * FROM categories ORDER BY name')],
                       settings={'delivery_fee': app.config['DELIVERY_FEE'], 'whatsapp_number': app.config['WHATSAPP_NUMBER'],
                                 'towel_bundle_discounts': {'2': 10, '3_plus': 15}})

    @app.get('/api/referrals/<code>')
    def referral_check(code):
        normalized = normalize_code(code)
        found = get_db().execute('SELECT code FROM partners WHERE code=? AND active=1', (normalized,)).fetchone()
        return jsonify(verified=bool(found), code=normalized)

    @app.post('/api/orders')
    def submit_order():
        same_origin()
        rate_limit('orders', 30, 3600)
        data = json_body()
        with transaction() as db:
            result, created = create_order(db, data)
        return jsonify(result), 201 if created else 200

    @app.get('/api/admin/session')
    def get_session():
        row = session_row()
        if row:
            return jsonify(authenticated=bool(row['username']), username=row['username'], csrf=row['csrf'])
        rate_limit('sessions', 120, 3600)
        return new_session()

    @app.post('/api/admin/login')
    def login():
        row = csrf_session()
        rate_limit('login', 10, 900)
        data = json_body()
        username = text(data.get('username'), 'İstifadəçi', 1, 80)
        password = data.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 1024:
            abort(400, 'Şifrə 1–1024 simvol olmalıdır.')
        admin = get_db().execute('SELECT * FROM admins WHERE username=?', (username,)).fetchone()
        # Always run an expensive hash check, including unknown users.
        initial_candidate = not admin and initial_hash and username == initial_username
        target = admin['password_hash'] if admin else initial_hash if initial_candidate else app.config['DUMMY_PASSWORD_HASH']
        if not check_password_hash(target, password) or (not admin and not initial_candidate):
            abort(401, 'İstifadəçi adı və ya şifrə yanlışdır.')
        if not admin:
            with transaction() as db:
                if db.execute('SELECT username FROM admins LIMIT 1').fetchone():
                    abort(409, 'İlk hesab artıq yaradılıb. Saxlanılmış hesabla daxil olun.')
                db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', (username, initial_hash))
                audit(db, 'admin', username, 'initial-setup', 'created', {})
        get_db().execute('DELETE FROM sessions WHERE token_hash=?', (row['token_hash'],))
        audit(get_db(), 'admin', username, username, 'login', {})
        return new_session(username)

    @app.post('/api/admin/logout')
    @admin_required
    def logout():
        row = session_row()
        get_db().execute('DELETE FROM sessions WHERE token_hash=?', (row['token_hash'],))
        audit(get_db(), 'admin', g.actor, g.actor, 'logout', {})
        response = jsonify(ok=True)
        response.delete_cookie('mf_session', path='/', secure=app.config['COOKIE_SECURE'], httponly=True, samesite='Strict')
        return response

    @app.get('/api/admin/products')
    @admin_required
    def products_list():
        db = get_db()
        q = request.args.get('q', '').strip()[:180]
        status, category = request.args.get('status', ''), request.args.get('category_id', '')
        rows = db.execute('''SELECT * FROM products WHERE (?='' OR status=?) AND (?='' OR category_id=?) ORDER BY updated_at DESC,id''', (status, status, category, category))
        # SQLite's built-in lower() is ASCII-only; catalog descriptions are Azerbaijani.
        def folded(value):
            return value.replace('İ', 'i').replace('I', 'ı').casefold()
        needle = folded(q)
        return jsonify(products=[product_json(db, p, True) for p in rows if not needle or needle in folded(p['name'] + ' ' + p['description'])])

    @app.post('/api/admin/products')
    @admin_required
    def product_create():
        data = json_body()
        with transaction() as db:
            p = save_product(db, data, g.actor)
        return jsonify(p), 201

    @app.post('/api/admin/import-original')
    @admin_required
    def import_original():
        json_body()
        from .import_original import seed
        return jsonify(imported=seed(app, actor=g.actor))

    @app.get('/api/admin/products/<identity>')
    @admin_required
    def product_detail(identity):
        db = get_db()
        row = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
        if not row:
            abort(404)
        return jsonify(product_json(db, row, True))

    @app.get('/api/admin/products/<identity>/preview')
    @admin_required
    def product_preview(identity):
        db = get_db()
        row = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
        if not row:
            abort(404)
        return jsonify(product_json(db, row))

    @app.put('/api/admin/products/<identity>')
    @admin_required
    def product_update(identity):
        data = json_body()
        with transaction() as db:
            p = save_product(db, data, g.actor, identity)
        return jsonify(p)

    @app.post('/api/admin/products/<identity>/duplicate')
    @admin_required
    def product_duplicate(identity):
        data = json_body()
        with transaction() as db:
            original = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
            if not original:
                abort(404)
            require_version(data, original)
            p = product_json(db, original, True)
            for k in ('price', 'cost', 'compare_at'):
                p[k] = p[k] / 100 if p[k] is not None else None
            for v in p['variants']:
                v.pop('id')
                v['stock'] = 0  # Never duplicate physical inventory.
                for k in ('price', 'cost', 'compare_at'):
                    v[k] = v[k] / 100 if v[k] is not None else None
            p['name'] = p['name'][:165] + ' (surət)'
            p.update(status='draft', available=False)
            copied = save_product(db, p, g.actor)
            db.execute('UPDATE products SET legacy_towel=? WHERE id=?', (original['legacy_towel'], copied['id']))
            for i, im in enumerate(p['images']):
                db.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?)', (uid(), copied['id'], Path(im['url']).name, Path(im['thumbnail_url']).name, im['width'], im['height'], i))
            audit(db, 'product', copied['id'], g.actor, 'duplicated', {'source_id': identity})
            copied = product_json(db, db.execute('SELECT * FROM products WHERE id=?', (copied['id'],)).fetchone(), True)
        return jsonify(copied), 201

    @app.post('/api/admin/products/<identity>/images')
    @admin_required
    def upload_images(identity):
        files = request.files.getlist('images')
        if not 1 <= len(files) <= 10:
            abort(400, 'Bir dəfəyə 1–10 şəkil seçin.')
        generated = []
        try:
            for file in files:
                generated.append(store_image(file.stream, app.config['MEDIA_DIR']))
                persist_image(generated[-1])
            with transaction() as db:
                row = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
                if not row:
                    abort(404)
                try:
                    version = int(request.form.get('version', ''))
                except ValueError:
                    abort(400)
                require_version({'version': version}, row)
                count = db.execute('SELECT COUNT(*) FROM images WHERE product_id=?', (identity,)).fetchone()[0]
                if count + len(generated) > 10:
                    abort(400, 'Məhsulda ən çox 10 şəkil ola bilər.')
                for i, im in enumerate(generated):
                    db.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?)', (im['id'], identity, im['filename'], im['thumbnail'], im['width'], im['height'], count + i))
                db.execute('UPDATE products SET version=version+1,updated_at=? WHERE id=?', (now(), identity))
                audit(db, 'product', identity, g.actor, 'images_uploaded', {'images': [i['id'] for i in generated]})
                result = product_json(db, db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone(), True)
        except BaseException:
            for im in generated:
                discard_new_image(im)
            raise
        return jsonify(result), 201

    @app.delete('/api/admin/products/<identity>/images/<image_id>')
    @admin_required
    def delete_image(identity, image_id):
        data = json_body()
        with transaction() as db:
            row = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
            if not row:
                abort(404)
            require_version(data, row)
            if not db.execute('DELETE FROM images WHERE product_id=? AND id=?', (identity, image_id)).rowcount:
                abort(404)
            db.execute('UPDATE products SET version=version+1,updated_at=? WHERE id=?', (now(), identity))
            audit(db, 'product', identity, g.actor, 'image_removed', {'image_id': image_id})
        # Immutable media remains on disk for shared duplicate references and backups.
        return jsonify(ok=True)

    @app.get('/api/admin/categories')
    @admin_required
    def categories_list():
        return jsonify(categories=[dict(c) for c in get_db().execute('SELECT * FROM categories ORDER BY name')])

    @app.post('/api/admin/categories')
    @admin_required
    def category_create():
        name = text(json_body().get('name'), 'Kateqoriya', 1, 100)
        identity = uid()
        with transaction() as db:
            db.execute('INSERT INTO categories VALUES(?,?)', (identity, name))
            audit(db, 'category', identity, g.actor, 'created', {'name': name})
        return jsonify(id=identity, name=name), 201

    @app.put('/api/admin/categories/<identity>')
    @app.delete('/api/admin/categories/<identity>')
    @admin_required
    def category_change(identity):
        with transaction() as db:
            if not db.execute('SELECT id FROM categories WHERE id=?', (identity,)).fetchone():
                abort(404)
            if request.method == 'DELETE':
                if db.execute('SELECT id FROM products WHERE category_id=?', (identity,)).fetchone():
                    abort(409, 'Əvvəlcə bu kateqoriyadakı məhsulları başqa kateqoriyaya keçirin.')
                db.execute('DELETE FROM categories WHERE id=?', (identity,))
                detail = {}
            else:
                detail = {'name': text(json_body().get('name'), 'Kateqoriya', 1, 100)}
                db.execute('UPDATE categories SET name=? WHERE id=?', (detail['name'], identity))
            audit(db, 'category', identity, g.actor, 'deleted' if request.method == 'DELETE' else 'renamed', detail)
        return jsonify(ok=True)

    @app.get('/api/admin/partners')
    @admin_required
    def partners_list():
        db = get_db()
        partners = []
        for row in db.execute('SELECT * FROM partners ORDER BY name'):
            p = dict(row)
            p['referral_url'] = app.config['PUBLIC_BASE_URL'] + '/?ref=' + p['code']
            p['balance'] = db.execute('SELECT COALESCE(SUM(amount),0) FROM commission_ledger WHERE partner_id=?', (p['id'],)).fetchone()[0]
            partners.append(p)
        return jsonify(partners=partners)

    @app.post('/api/admin/partners')
    @app.put('/api/admin/partners/<identity>')
    @admin_required
    def partner_save(identity=None):
        data = json_body()
        name = text(data.get('name'), 'Partnyor adı', 2, 160)
        code = normalize_code(data.get('code', ''))
        if not code:
            abort(400, 'Referal kodu tələb olunur.')
        commission = money(data.get('commission'), 'Sabit komissiya')
        active = boolean(data.get('active', True), 'Aktivlik')
        with transaction() as db:
            before = None
            if identity:
                before = db.execute('SELECT * FROM partners WHERE id=?', (identity,)).fetchone()
                if not before:
                    abort(404)
                require_version(data, before)
                db.execute('UPDATE partners SET name=?,code=?,commission=?,active=?,version=version+1 WHERE id=?', (name, code, commission, active, identity))
            else:
                identity = uid()
                db.execute('INSERT INTO partners(id,name,code,commission,active) VALUES(?,?,?,?,?)', (identity, name, code, commission, active))
            audit(db, 'partner', identity, g.actor, 'updated' if before else 'created', {'before': dict(before) if before else None, 'after': {'name': name, 'code': code, 'commission': commission, 'active': active}})
        return jsonify(ok=True, id=identity)

    @app.get('/api/admin/partners/<identity>/qr.svg')
    @admin_required
    def partner_qr(identity):
        row = get_db().execute('SELECT code FROM partners WHERE id=?', (identity,)).fetchone()
        if not row:
            abort(404)
        image = qrcode.make(app.config['PUBLIC_BASE_URL'] + '/?ref=' + row['code'], image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=4)
        output = io.BytesIO()
        image.save(output)
        return output.getvalue(), 200, {'Content-Type': 'image/svg+xml', 'Content-Disposition': 'inline; filename="referral-' + row['code'] + '.svg"'}

    @app.get('/api/admin/orders')
    @admin_required
    def orders_list():
        db = get_db()
        q, status = request.args.get('q', '')[:180], request.args.get('status', '')
        rows = db.execute('''SELECT * FROM orders WHERE (?='' OR instr(reference,?)>0 OR instr(customer_name,?)>0 OR instr(phone,?)>0)
                          AND (?='' OR sale_status=?) ORDER BY created_at DESC,rowid DESC LIMIT 200''', (q, q, q, q, status, status))
        return jsonify(orders=[order_json(db, r) for r in rows], limit=200)

    @app.get('/api/admin/orders/<identity>')
    @admin_required
    def order_detail(identity):
        db = get_db()
        row = db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone()
        if not row:
            abort(404)
        return jsonify(order_json(db, row))

    @app.post('/api/admin/orders/<identity>/events')
    @admin_required
    def order_event(identity):
        data = json_body()
        with transaction() as db:
            result = update_order(db, identity, data, g.actor)
        return jsonify(result)

    @app.get('/api/admin/audit')
    @admin_required
    def audit_list():
        try:
            before = int(request.args.get('before', '9223372036854775807'))
        except ValueError:
            abort(400)
        rows = get_db().execute('SELECT * FROM audit_events WHERE sequence<? ORDER BY sequence DESC LIMIT 100', (before,))
        return jsonify(events=[dict(r) for r in rows])

    app.config['DUMMY_PASSWORD_HASH'] = generate_password_hash(secrets.token_urlsafe(32))
    return app
