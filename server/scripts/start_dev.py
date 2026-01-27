#!/usr/bin/env python3
"""Start ByteBuddhi development server.

This script starts the FastAPI development server with auto-reload
and proper configuration from environment variables.
"""

import subprocess
import sys
from pathlib import Path

# Add the server directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.infrastructure.config.settings import settings


def main():
    """Start the development server."""
    # Change to server directory to ensure correct imports
    server_dir = Path(__file__).parent.parent
    
    cmd = [
        "uvicorn",
        "app.interfaces.api.main:app",
        "--host", settings.host,
        "--port", str(settings.port),
        "--reload",
        "--log-level", settings.log_level.lower(),
    ]
    
    print("="*60)
    print(" Starting ByteBuddhi Development Server")
    print("="*60)
    print(f"\nEnvironment: {settings.app_env}")
    print(f"Server: http://{settings.host}:{settings.port}")
    print(f"API Docs: http://{settings.host}:{settings.port}/api/docs")
    print(f"Health: http://{settings.host}:{settings.port}/api/health")
    print("\nPress Ctrl+C to stop the server\n")
    print("="*60 + "\n")
    
    try:
        subprocess.run(cmd, cwd=server_dir)
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print(" Shutting down server...")
        print("="*60)
        sys.exit(0)
    except Exception as e:
        print(f"\n Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
