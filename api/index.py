"""Vercel's WSGI entrypoint. All authorization remains in the Flask app."""
from mikrofiber.app import create_app

app = create_app()
