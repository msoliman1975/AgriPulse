"""ASGI entry point. Hands construction to the app factory."""

from app.core.app_factory import create_app

app = create_app()
