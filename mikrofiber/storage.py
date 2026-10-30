"""Persistent Supabase object storage, or local disk for development."""
import re
from pathlib import Path
from urllib.parse import quote
import httpx
from flask import current_app


class StorageError(RuntimeError):
    pass


def remote():
    return current_app.config['STORAGE_BACKEND'] == 'supabase'


def validate_storage(config):
    if config['STORAGE_BACKEND'] not in ('local', 'supabase'):
        raise ValueError('STORAGE_BACKEND must be local or supabase.')
    if config['STORAGE_BACKEND'] == 'supabase':
        if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', config['SUPABASE_URL']):
            raise ValueError('SUPABASE_URL must be the project HTTPS origin.')
        if not config['SUPABASE_SERVICE_ROLE_KEY']:
            raise ValueError('A server-only Supabase secret/service-role key is required.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', config['SUPABASE_STORAGE_BUCKET']):
            raise ValueError('Invalid image bucket name.')


def storage_request(method, path, *, data=None, body=None, authenticated=True):
    config = current_app.config
    headers = {}
    if authenticated:
        key = config['SUPABASE_SERVICE_ROLE_KEY']
        headers['apikey'] = key
        if key.startswith('eyJ'):  # legacy service-role JWT
            headers['Authorization'] = 'Bearer ' + key
    if data is not None:
        headers.update({'Content-Type': 'image/webp', 'Cache-Control': '31536000', 'x-upsert': 'false'})
    try:
        with httpx.Client(timeout=20, follow_redirects=False,
                          transport=config.get('STORAGE_HTTP_TRANSPORT')) as client:
            response = client.request(method, config['SUPABASE_URL'] + '/storage/v1/' + path,
                                      headers=headers, content=data, json=body)
    except httpx.HTTPError:
        raise StorageError('Photo storage could not be reached.') from None
    if response.status_code not in (200, 201, 204):
        # Never include keys, request headers, or remote error bodies in logs.
        raise StorageError(f'Photo storage rejected the operation (HTTP {response.status_code}).')
    return response


def media_url(filename):
    return (current_app.config['SUPABASE_URL'] + '/storage/v1/object/public/' +
            current_app.config['SUPABASE_STORAGE_BUCKET'] + '/' + quote(filename, safe=''))


def persist_image(image):
    if not remote():
        return
    directory = Path(current_app.config['MEDIA_DIR'])
    for field in ('filename', 'thumbnail'):
        storage_request('POST', 'object/' + current_app.config['SUPABASE_STORAGE_BUCKET'] + '/' + image[field],
                        data=(directory / image[field]).read_bytes())
        image.setdefault('_uploaded', []).append(image[field])
    for field in ('filename', 'thumbnail'):
        (directory / image[field]).unlink(missing_ok=True)


def discard_new_image(image):
    for name in image.get('_created_local', [image['filename'], image['thumbnail']]):
        Path(current_app.config['MEDIA_DIR'], name).unlink(missing_ok=True)
    if remote() and image.get('_uploaded'):
        try:
            storage_request('DELETE', 'object/' + current_app.config['SUPABASE_STORAGE_BUCKET'],
                            body={'prefixes': image['_uploaded']})
        except StorageError:
            current_app.logger.warning('An unreferenced new image needs storage cleanup.')


def download_image(filename):
    if remote():
        return storage_request('GET', 'object/' + current_app.config['SUPABASE_STORAGE_BUCKET'] + '/' + filename).content
    return Path(current_app.config['MEDIA_DIR'], filename).read_bytes()
