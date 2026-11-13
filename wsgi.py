"""Entry point for hosted servers:  gunicorn wsgi:app  (keep ONE worker: run state and limits are kept in-process)."""
from app import create_app

app = create_app()
