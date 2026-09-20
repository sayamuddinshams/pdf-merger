"""WSGI entry point for gunicorn:  gunicorn -w 2 -b 0.0.0.0:8000 wsgi:application"""

from app import app as application  # noqa: F401