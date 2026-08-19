"""Shared Flask extension instances, created here to avoid circular imports
between the main app module and the individual game blueprints."""
from flask_socketio import SocketIO

socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")
