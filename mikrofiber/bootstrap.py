"""Validate first-account configuration without exposing credential values."""
import re


def bootstrap_errors(username, password):
    if not username and not password:
        return []  # Normal after the initial admin has been created.
    errors = []
    if not username:
        errors.append('INITIAL_ADMIN_USERNAME is missing. Set its Production value to owner.')
    elif not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', username):
        errors.append('INITIAL_ADMIN_USERNAME is invalid. Use 3–80 ASCII letters, digits, dots, underscores or hyphens. For setup, type owner without quotes or spaces.')
    if not password:
        errors.append('INITIAL_ADMIN_PASSWORD is missing. Set a private Production password of 14–1024 characters.')
    elif len(password) < 14:
        errors.append('INITIAL_ADMIN_PASSWORD is too short. It must contain at least 14 characters; choose 16 or more.')
    elif len(password) > 1024:
        errors.append('INITIAL_ADMIN_PASSWORD is too long. It must contain at most 1024 characters.')
    return errors
