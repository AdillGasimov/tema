import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode
from flask import abort, current_app
from .catalog import integer, text, uid, require_version
from .db import audit, now


def azn(cents):
    return f'{cents / 100:.2f} AZN'


def normalize_code(value):
    value = text(value, 'Referal kodu', 0, 40).upper()
    if value and not re.fullmatch(r'[A-Z0-9_-]{3,40}', value):
        abort(400, 'Referal kodunun formatı düzgün deyil.')
    return value


def order_json(db, row):
    order = dict(row)
    order.pop('request_hash', None)
    order.pop('idempotency_key', None)
    order['items'] = [dict(i) for i in db.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY rowid', (row['id'],))]
    order['ledger'] = [dict(i) for i in db.execute('SELECT * FROM commission_ledger WHERE order_id=? ORDER BY sequence', (row['id'],))]
    return order


def receipt(db, row):
    items = db.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY rowid', (row['id'],)).fetchall()
    lines = ['*SİFARİŞ SORĞUSU* — hələ təsdiqlənməyib', f"İstinad: {row['reference']}", '',
             f"Müştəri: {row['customer_name']}", f"Telefon: {row['phone']}", f"Ünvan/təhvil yeri: {row['address']}", '']
    for i in items:
        lines.append(f"• {i['product_name']} ({i['variant_name']}) × {i['quantity']} — vahid: {azn(i['unit_price'])}; endirim: {azn(i['discount'])}; cəm: {azn(i['line_total'])}")
    lines += ['', f"Məhsullar: {azn(row['subtotal'])}", f"Endirim: {azn(row['discount'])}",
              f"Çatdırılma: {'28 May metrosu' if row['delivery'] == 'metro' else 'Ünvana kuryer'} — {azn(row['delivery_fee'])}",
              f"Yekun: {azn(row['total'])}", f"Qeyd: {row['note'] or 'Xüsusi qeyd yoxdur'}"]
    if row['referral_submitted']:
        lines.append(f"Referal: {row['referral_submitted']} ({'yoxlanılıb' if row['partner_id'] else 'təsdiqlənməyib, komissiya hesablanmır'})")
    lines += ['', 'Mikrofiber.shop — operator təsdiqi gözlənilir. Ödəniş qapıda.']
    message = '\n'.join(lines)
    return {'reference': row['reference'], 'sale_status': row['sale_status'], 'total': row['total'],
            'referral_verified': bool(row['partner_id']), 'message': message,
            'whatsapp_url': 'https://api.whatsapp.com/send?' + urlencode({'phone': current_app.config['WHATSAPP_NUMBER'], 'text': message})}


def create_order(db, data):
    if not isinstance(data, dict):
        abort(400, 'Sifariş məlumatı düzgün deyil.')
    key = data.get('idempotency_key')
    try:
        if not isinstance(key, str) or str(uuid.UUID(key)) != key:
            raise ValueError
    except (ValueError, AttributeError):
        abort(400, 'Sifariş açarı düzgün deyil.')
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    prior = db.execute('SELECT * FROM orders WHERE idempotency_key=?', (key,)).fetchone()
    if prior:
        if prior['request_hash'] != digest:
            abort(409, 'Bu sifariş açarı başqa məlumatla istifadə olunub.')
        return receipt(db, prior), False
    customer = data.get('customer')
    if not isinstance(customer, dict):
        abort(400, 'Müştəri məlumatı yoxdur.')
    name = text(customer.get('name'), 'Ad və soyad', 3, 120)
    phone = text(customer.get('phone'), 'Telefon', 9, 30)
    phone = re.sub(r'[\s()+-]', '', phone)
    if not re.fullmatch(r'(?:994|0)?(?:10|50|51|55|60|70|77|99)\d{7}', phone):
        abort(400, 'Azərbaycan mobil nömrəsini düzgün daxil edin.')
    address = text(customer.get('address'), 'Ünvan', 3, 500)
    note = text(customer.get('note', ''), 'Qeyd', 0, 2000)
    delivery = data.get('delivery')
    if delivery not in ('metro', 'courier'):
        abort(400, 'Çatdırılma növü düzgün deyil.')
    fee = 0 if delivery == 'metro' else current_app.config['DELIVERY_FEE']
    code = normalize_code(data.get('referral_code', ''))
    partner = db.execute('SELECT * FROM partners WHERE code=? AND active=1', (code,)).fetchone() if code else None
    items = data.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        abort(400, '1–20 məhsul sətri seçin.')
    prepared, seen, subtotal, discount = [], set(), 0, 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('variant_id'), str) or not isinstance(item.get('product_id'), str):
            abort(400, 'Məhsul seçimi düzgün deyil.')
        vid, pid = item['variant_id'], item['product_id']
        if vid in seen:
            abort(400, 'Təkrarlanan variantı bir sətirdə birləşdirin.')
        seen.add(vid)
        quantity = integer(item.get('quantity'), 'Say', 1, 99)
        p = db.execute('SELECT * FROM products WHERE id=? AND status=\'published\' AND available=1', (pid,)).fetchone()
        v = db.execute('SELECT * FROM variants WHERE id=? AND product_id=? AND active=1 AND available=1', (vid, pid)).fetchone()
        if not p or not v:
            abort(409, 'Seçilmiş məhsul artıq satışda deyil. Kataloqu yeniləyin.')
        if quantity > v['stock']:
            abort(409, f"{p['name']}: kifayət qədər stok yoxdur.")
        price = v['price'] if v['price'] is not None else p['price']
        line_subtotal = price * quantity
        percent = (15 if quantity >= 3 else 10 if quantity == 2 else 0) if p['legacy_towel'] else 0
        line_discount = (line_subtotal * percent + 50) // 100
        label = ' / '.join(x for x in (v['size'], v['colour']) if x) or 'Standart'
        prepared.append((uid(), pid, vid, p['name'], label, price, quantity, line_discount, line_subtotal - line_discount))
        subtotal += line_subtotal
        discount += line_discount
    total = subtotal - discount + fee
    integer(data.get('expected_total'), 'Gözlənilən yekun', 1, 10000000000)
    if total != data['expected_total']:
        abort(409, 'Qiymət və ya çatdırılma haqqı dəyişib. Kataloqu yeniləyib məbləği yoxlayın.')
    identity = uid()
    reference = 'MF-' + datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:12].upper()
    db.execute('''INSERT INTO orders(id,reference,idempotency_key,request_hash,customer_name,phone,address,note,delivery,delivery_fee,
               subtotal,discount,total,referral_submitted,partner_id,referral_code,partner_name,commission_snapshot,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (identity, reference, key, digest, name, phone, address, note, delivery, fee, subtotal, discount, total, code,
                partner['id'] if partner else None, partner['code'] if partner else None,
                partner['name'] if partner else None, partner['commission'] if partner else 0, now()))
    for i in prepared:
        db.execute('INSERT INTO order_items(id,order_id,product_id,variant_id,product_name,variant_name,unit_price,quantity,discount,line_total) VALUES(?,?,?,?,?,?,?,?,?,?)', (i[0], identity, *i[1:]))
    audit(db, 'order', identity, 'storefront', 'submitted', {'reference': reference, 'total': total, 'partner_id': partner['id'] if partner else None})
    row = db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone()
    return receipt(db, row), True


def update_order(db, identity, data, actor):
    o = db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone()
    if not o:
        abort(404)
    require_version(data, o)
    action = data.get('action')
    reason = text(data.get('reason', ''), 'Səbəb/qəbz istinadı', 3, 500)
    sale, fulfillment, payment, eligible, deducted = (o[k] for k in ('sale_status', 'fulfillment', 'payment', 'eligible', 'stock_deducted'))
    stock_change = 0
    if action == 'confirm' and sale == 'submitted':
        sale, deducted, stock_change = 'confirmed', 1, -1
    elif action == 'cancel' and sale in ('submitted', 'confirmed') and fulfillment == 'pending' and payment != 'paid':
        sale, deducted, stock_change = 'cancelled', 0, 1 if deducted else 0
    elif action == 'deliver' and sale == 'confirmed' and fulfillment == 'pending':
        fulfillment = 'delivered'
    elif action == 'mark_paid' and sale == 'confirmed' and payment == 'unpaid':
        payment = 'paid'
    elif action == 'refund' and payment == 'paid':
        payment = 'refunded'
    elif action == 'return' and fulfillment == 'delivered':
        fulfillment, deducted, stock_change = 'returned', 0, 1 if deducted else 0
    elif action == 'eligibility' and type(data.get('eligible')) is bool:
        eligible = int(data['eligible'])
    elif action == 'pay_commission':
        earned = db.execute("SELECT COALESCE(SUM(amount),0) FROM commission_ledger WHERE order_id=? AND kind!='payout'", (identity,)).fetchone()[0]
        paid = -db.execute("SELECT COALESCE(SUM(amount),0) FROM commission_ledger WHERE order_id=? AND kind='payout'", (identity,)).fetchone()[0]
        if not o['partner_id'] or earned <= paid or not (sale == 'confirmed' and fulfillment == 'delivered' and payment == 'paid' and eligible):
            abort(409, 'Ödəniləcək uyğun komissiya yoxdur.')
        db.execute("INSERT INTO commission_ledger(order_id,partner_id,kind,amount,actor,reason,created_at) VALUES(?,?,'payout',?,?,?,?)", (identity, o['partner_id'], -(earned - paid), actor, reason, now()))
    else:
        abort(409, 'Bu statusda seçilmiş əməliyyat mümkün deyil.')
    if stock_change:
        for item in db.execute('SELECT * FROM order_items WHERE order_id=?', (identity,)).fetchall():
            if stock_change == -1:
                ok = db.execute('''UPDATE variants SET stock=stock-? WHERE id=? AND active=1 AND available=1 AND stock>=?
                                   AND EXISTS(SELECT 1 FROM products WHERE id=variants.product_id AND status='published' AND available=1)''',
                                (item['quantity'], item['variant_id'], item['quantity'])).rowcount
                if not ok:
                    abort(409, 'Təsdiq üçün məhsul satışda olmalı və kifayət qədər stok olmalıdır.')
            else:
                db.execute('UPDATE variants SET stock=stock+? WHERE id=?', (item['quantity'], item['variant_id']))
            db.execute('UPDATE products SET version=version+1,updated_at=? WHERE id=?', (now(), item['product_id']))
            audit(db, 'product', item['product_id'], actor, 'order_stock_change', {'order_id': identity, 'variant_id': item['variant_id'], 'delta': stock_change * item['quantity']})
    db.execute('UPDATE orders SET sale_status=?,fulfillment=?,payment=?,eligible=?,stock_deducted=?,version=version+1 WHERE id=?', (sale, fulfillment, payment, eligible, deducted, identity))
    if o['partner_id']:
        should_earn = o['commission_snapshot'] if (sale == 'confirmed' and fulfillment == 'delivered' and payment == 'paid' and eligible) else 0
        earned = db.execute("SELECT COALESCE(SUM(amount),0) FROM commission_ledger WHERE order_id=? AND kind!='payout'", (identity,)).fetchone()[0]
        delta = should_earn - earned
        if delta:
            db.execute('INSERT INTO commission_ledger(order_id,partner_id,kind,amount,actor,reason,created_at) VALUES(?,?,?,?,?,?,?)',
                       (identity, o['partner_id'], 'earned' if delta > 0 else 'reversed', delta, actor, reason, now()))
    audit(db, 'order', identity, actor, action, {'reason': reason, 'before': {k: o[k] for k in ('sale_status', 'fulfillment', 'payment', 'eligible')}, 'after': {'sale_status': sale, 'fulfillment': fulfillment, 'payment': payment, 'eligible': eligible}})
    return order_json(db, db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone())
