import base64
import io
import re
from pathlib import Path
from .catalog import save_product, uid
from .db import audit, transaction
from .images import store_image
from .storage import persist_image, discard_new_image


def seed(app, actor='import'):
    created = []
    with app.app_context():
        try:
            with transaction() as db:
                if db.execute('SELECT id FROM products WHERE legacy_towel=1').fetchone():
                    return False
                category = uid()
                db.execute('INSERT INTO categories VALUES(?,?)', (category, 'Avtomobilə qulluq'))
                p = save_product(db, {'name': 'Mikrofiber Avto Qurulama Dəsmalı',
                    'description': 'Maşını yuyandan sonra suyu bir-iki silişlə yığır. Lakı cızmır, üzərində tük və ləkə qoymur.',
                    'price': '12.99', 'cost': None, 'compare_at': '19.99', 'category_id': category,
                    'status': 'published', 'available': False,
                    'variants': [{'size': '50×60 sm', 'colour': '', 'price': '12.99', 'compare_at': '19.99', 'stock': 0, 'available': True},
                                 {'size': '60×90 sm', 'colour': '', 'price': '23.99', 'compare_at': '39.99', 'stock': 0, 'available': True}]}, actor)
                db.execute('UPDATE products SET legacy_towel=1 WHERE id=?', (p['id'],))
                original = (Path(__file__).resolve().parent.parent / 'seed/original.html').read_text()
                for i, data in enumerate(re.findall(r'\bsrc="data:image/webp;base64,([A-Za-z0-9+/=]+)"', original)):
                    im = store_image(io.BytesIO(base64.b64decode(data)), app.config['MEDIA_DIR'])
                    created.append(im)
                    persist_image(im)
                    db.execute('INSERT INTO images(id,product_id,filename,thumbnail,width,height,position) VALUES(?,?,?,?,?,?,?)',
                               (im['id'], p['id'], im['filename'], im['thumbnail'], im['width'], im['height'], i))
                audit(db, 'product', p['id'], actor, 'original_import', {'source': 'seed/original.html', 'stock': 'Unknown; zero and unavailable until verified.'})
            return True
        except BaseException:
            for im in created:
                discard_new_image(im)
            raise
