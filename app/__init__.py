"""ByteBuddhi application package.

ByteBuddhi is an AI-powered coding assistant that helps developers
understand, debug, and improve their code using advanced LLM technology.

Architecture:
- Domain: Core business logic and models
- Application: Use cases and orchestration
- Infrastructure: External services and persistence
- Interfaces: API and user-facing adapters
"""

from app._version import APP_VERSION as __version__
from app._version import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION

__all__ = ["__version__", "PROTOCOL_VERSION", "MIN_PROTOCOL_VERSION"]
