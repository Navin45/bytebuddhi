#!/usr/bin/env python3
"""ByteBuddhi Server Entry Point.

This is a convenience entry point that redirects to the actual FastAPI application.
The main application is located at: app/interfaces/api/main.py

For development, use: python scripts/start_dev.py
For production, use: uvicorn app.interfaces.api.main:app
"""

import sys
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    """Entry point that provides usage information."""
    print("=" * 60)
    print("ByteBuddhi Server")
    print("=" * 60)
    print("\nThis is not the main entry point.")
    print("\nTo start the development server, use:")
    print("  python scripts/start_dev.py")
    print("\nTo start with Docker:")
    print("  docker-compose up -d")
    print("\nTo run with uvicorn directly:")
    print("  uvicorn app.interfaces.api.main:app --reload")
    print("\nFor more information, see README.md")
    print("=" * 60)


if __name__ == "__main__":
    main()
