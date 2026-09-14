"""Routes package initialization."""

from app.interfaces.api.routes import agent, auth, chat, files, health, models, oauth, projects

__all__ = ["agent", "auth", "chat", "files", "health", "models", "oauth", "projects"]
