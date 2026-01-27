"""Routes package initialization."""

from app.interfaces.api.routes import agent, auth, chat, health, projects

__all__ = ["agent", "auth", "chat", "health", "projects"]
