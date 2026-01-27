#!/usr/bin/env python3
"""Run database migrations using Alembic.

This script runs all pending Alembic migrations to bring
the database schema up to date.
"""

import subprocess
import sys


def main():
    """Run database migrations."""
    print("="*60)
    print("Running Database Migrations")
    print("="*60)
    
    try:
        # Run alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True,
        )
        
        print(result.stdout)
        
        print("\n" + "="*60)
        print("Migrations completed successfully!")
        print("="*60)
        sys.exit(0)
        
    except subprocess.CalledProcessError as e:
        print("\n Migration failed!")
        print(f"Error: {e.stderr}")
        print("\nTroubleshooting:")
        print("1. Ensure database is running and accessible")
        print("2. Check DATABASE_URL in .env file")
        print("3. Verify alembic.ini configuration")
        print("4. Run: python scripts/test_connection.py")
        sys.exit(1)
    except FileNotFoundError:
        print("\n Alembic not found!")
        print("Install it with: pip install alembic")
        sys.exit(1)


if __name__ == "__main__":
    main()
