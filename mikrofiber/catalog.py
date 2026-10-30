import re
import uuid
from decimal import Decimal, InvalidOperation
from flask import abort
from .db import audit, now


def uid():
    return uuid.uuid4().hex


def text(value, label, minimum=0, maximum=1000):
    if not isinstance(value, str):
        abort(400, f'{label}: mətn daxil edin.')
    value = value.strip()
    if not minimum <= len(value) <= maximum or re.search(r'[\x00-\x08\x0b-\x1f\x7f]', value):
        abort(400, f'{label}: {minimum}–{maximum} simvol daxil edin.')
    return value


def money(value, label='Qiymət', optional=False, minimum=0):
    if optional and (value is None or value == ''):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        abort(400, f'{label}: düzgün AZN məbləği daxil edin.')
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < Decimal(minimum) / 100 or d > 1000000 or d * 100 != (d * 100).to_integral_value():
            raise InvalidOperation
        return int(d * 100)
    except (InvalidOperation, ValueError, OverflowError):
        abort(400, f'{label}: ən çox iki onluq rəqəm və düzgün məbləğ daxil edin.')


def integer(value, label, minimum=0, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        abort(400, f'{label}: {minimum}–{maximum} aralığında tam ədəd daxil edin.')
    return value


def boolean(value, label):
    if type(value) is not bool:
        abort(400, f'{label}: doğru/yanlış olmalıdır.')
    return int(value)


def require_version(data, row):
    if type(data.get('version')) is not int or data['version'] != row['version']:
        abort(409, 'Məlumat başqa əməliyyatda dəyişib. Səhifəni yeniləyin.')


def product_json(db, row, private=False):
    p = dict(row)
    variants = [dict(v) for v in db.execute('SELECT * FROM variants WHERE product_id=? AND active=1 ORDER BY rowid', (p['id'],))]
    images = [dict(i) for i in db.execute('SELECT * FROM images WHERE product_id=? ORDER BY position,rowid', (p['id'],))]
    for im in images:
        im['url'] = '/media/' + im.pop('filename')
        im['thumbnail_url'] = '/media/' + im.pop('thumbnail')
    p['images'] = images
    p['variants'] = variants
    p['available'] = bool(p['available'])
    p['legacy_towel'] = bool(p['legacy_towel'])
    for v in variants:
        v['available'] = bool(v['available'])
        v['effective_price'] = v['price'] if v['price'] is not None else p['price']
        v['effective_compare_at'] = v['compare_at'] if v['compare_at'] is not None else p['compare_at']
        v.pop('active', None)
    if not private:
        # Explicit allowlist: costs and future private columns cannot leak into public JSON.
        p = {k: p[k] for k in ('id', 'name', 'description', 'price', 'compare_at', 'category_id', 'available', 'legacy_towel', 'images', 'variants')}
        p['variants'] = [{k: v[k] for k in ('id', 'size', 'colour', 'stock', 'available', 'effective_price', 'effective_compare_at')} for v in variants]
    return p


def save_product(db, data, actor, identity=None):
    if not isinstance(data, dict):
        abort(400, 'Məhsul məlumatı düzgün deyil.')
    old = None
    if identity:
        old = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
        if not old:
            abort(404)
        require_version(data, old)
    name = text(data.get('name'), 'Ad', 2, 180)
    description = text(data.get('description'), 'Təsvir', 1, 10000)
    price = money(data.get('price'), minimum=1)
    cost = money(data.get('cost'), 'Maya dəyəri', optional=True)
    compare = money(data.get('compare_at'), 'Əvvəlki qiymət', optional=True, minimum=1)
    if compare is not None and compare < price:
        abort(400, 'Əvvəlki qiymət satış qiymətindən az ola bilməz.')
    status = data.get('status', 'draft')
    if status not in ('draft', 'published', 'hidden', 'archived'):
        abort(400, 'Məhsul statusu düzgün deyil.')
    available = boolean(data.get('available', False), 'Mövcudluq')
    category = data.get('category_id') or None
    if category is not None and (not isinstance(category, str) or not db.execute('SELECT id FROM categories WHERE id=?', (category,)).fetchone()):
        abort(400, 'Kateqoriya tapılmadı.')
    variants = data.get('variants')
    if not isinstance(variants, list) or not 1 <= len(variants) <= 100:
        abort(400, '1–100 variant daxil edin (standart variant da ola bilər).')
    identity = identity or uid()
    before = product_json(db, old, True) if old else None
    known = {v['id'] for v in db.execute('SELECT id FROM variants WHERE product_id=?', (identity,))}
    prepared, seen, labels = [], set(), set()
    for v in variants:
        if not isinstance(v, dict):
            abort(400, 'Variant düzgün deyil.')
        vid = v.get('id')
        if vid is not None and (not isinstance(vid, str) or vid not in known or vid in seen):
            abort(400, 'Variant ID düzgün deyil.')
        vid = vid or uid()
        seen.add(vid)
        size, colour = text(v.get('size', ''), 'Ölçü', 0, 80), text(v.get('colour', ''), 'Rəng', 0, 80)
        label = (size.casefold(), colour.casefold())
        if label in labels:
            abort(400, 'Eyni ölçü və rəng təkrarlanır.')
        labels.add(label)
        vp = money(v.get('price'), 'Variant qiyməti', optional=True, minimum=1)
        vc = money(v.get('cost'), 'Variant maya dəyəri', optional=True)
        vo = money(v.get('compare_at'), 'Variant əvvəlki qiyməti', optional=True, minimum=1)
        effective_price = vp if vp is not None else price
        effective_compare = vo if vo is not None else compare
        if effective_compare is not None and effective_compare < effective_price:
            abort(400, 'Variantın əvvəlki qiymətini də yeniləyin və ya silin.')
        stock = integer(v.get('stock'), 'Stok')
        va = boolean(v.get('available', True), 'Variant mövcudluğu')
        prepared.append((vid, identity, size, colour, vp, vc, vo, stock, va))
    stamp = now()
    if old:
        db.execute('UPDATE products SET name=?,description=?,price=?,cost=?,compare_at=?,category_id=?,status=?,available=?,version=version+1,updated_at=? WHERE id=?',
                   (name, description, price, cost, compare, category, status, available, stamp, identity))
        db.execute('UPDATE variants SET active=0 WHERE product_id=?', (identity,))
    else:
        db.execute('INSERT INTO products(id,name,description,price,cost,compare_at,category_id,status,available,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (identity, name, description, price, cost, compare, category, status, available, stamp, stamp))
    for v in prepared:
        db.execute('INSERT INTO variants(id,product_id,size,colour,price,cost,compare_at,stock,available) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET size=excluded.size,colour=excluded.colour,price=excluded.price,cost=excluded.cost,compare_at=excluded.compare_at,stock=excluded.stock,available=excluded.available,active=1', v)
    row = db.execute('SELECT * FROM products WHERE id=?', (identity,)).fetchone()
    after = product_json(db, row, True)
    audit(db, 'product', identity, actor, 'updated' if old else 'created', {'before': before, 'after': after})
    return after
