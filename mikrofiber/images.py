import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import abort
from .catalog import uid

Image.MAX_IMAGE_PIXELS = 24000000


def store_image(stream, directory):
    """Decode and re-encode; never serve uploaded source bytes or metadata."""
    raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        abort(413, 'Hər şəkil ən çox 8 MB ola bilər.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ('JPEG', 'PNG', 'WEBP') or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError
                original.load()
                image = ImageOps.exif_transpose(original).convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        abort(400, 'Etibarlı, animasiyasız JPG, PNG və ya WebP şəkli seçin (ən çox 24 MP).')
    image.thumbnail((1600, 1600))
    name = uid()
    directory = Path(directory)
    main, thumb = directory / (name + '.webp'), directory / (name + '-small.webp')
    try:
        image.save(main, 'WEBP', quality=84, method=4)
        width, height = image.size
        image.thumbnail((480, 480))
        image.save(thumb, 'WEBP', quality=80, method=4)
    except BaseException:
        main.unlink(missing_ok=True)
        thumb.unlink(missing_ok=True)
        raise
    return {'id': name, 'filename': main.name, 'thumbnail': thumb.name, 'width': width, 'height': height}
