"""Production WSGI import surface. Configure and run it in deployment tooling only."""

from app import app

__all__ = ["app"]
