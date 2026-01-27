#!/usr/bin/env python3
"""Setup script for ByteBuddhi development environment.

This script helps set up the development environment by:
1. Checking for virtual environment
2. Installing dependencies
3. Verifying configuration
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: str, description: str) -> bool:
    """Run a shell command and return success status.
    
    Args:
        cmd: Command to execute
        description: Human-readable description
        
    Returns:
        bool: True if command succeeded
    """
    print(f"\n{'='*60}")
    print(f" {description}")
    print(f"{'='*60}")
    try:
        subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=False,
            text=True,
        )
        print(f"{description} - SUCCESS")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{description} - FAILED")
        print(f"Error: {e}")
        return False


def check_virtual_env() -> bool:
    """Check if running in a virtual environment.
    
    Returns:
        bool: True if in virtual environment or user wants to continue
    """
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    
    if not in_venv:
        print("\n  WARNING: Not in a virtual environment!")
        print("It's recommended to activate your virtual environment first:")
        print("  python -m venv .venv")
        print("  source .venv/bin/activate  # On Unix/macOS")
        print("  .venv\\Scripts\\activate     # On Windows")
        response = input("\nContinue anyway? (y/N): ")
        return response.lower() == 'y'
    
    return True


def main():
    """Main setup function."""
    print("\n" + "="*60)
    print(" ByteBuddhi Setup Script")
    print("="*60)
    
    # Check virtual environment
    if not check_virtual_env():
        print("Setup cancelled.")
        sys.exit(0)
    
    # Check if requirements.txt exists
    if not Path("requirements.txt").exists():
        print(" requirements.txt not found!")
        print("Make sure you're running this from the server directory.")
        sys.exit(1)
    
    # Install dependencies
    steps = [
        ("pip install --upgrade pip", "Upgrading pip"),
        ("pip install -r requirements.txt", "Installing dependencies"),
    ]
    
    for cmd, desc in steps:
        if not run_command(cmd, desc):
            print(f"\n Setup failed at: {desc}")
            sys.exit(1)
    
    print("\n" + "="*60)
    print(" Setup completed successfully!")
    print("="*60)
    print("\nNext steps:")
    print("1. Copy .env.example to .env and configure your settings")
    print("2. Run: python scripts/setup_db.py")
    print("3. Run: alembic upgrade head")
    print("4. Run: python scripts/start_dev.py")
    print("\nHappy coding! ")


if __name__ == "__main__":
    main()
