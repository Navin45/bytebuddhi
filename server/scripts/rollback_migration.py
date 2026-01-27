#!/usr/bin/env python3
"""Rollback the last database migration.

This script rolls back the most recent Alembic migration,
reverting the database schema to the previous state.
"""

import subprocess
import sys


def main():
    """Rollback the last migration."""
    print("="*60)
    print("Rolling Back Last Migration")
    print("="*60)
    
    # Ask for confirmation
    response = input("\nThis will revert the last migration. Continue? (y/N): ")
    if response.lower() != 'y':
        print("Rollback cancelled.")
        sys.exit(0)
    
    try:
        # Run alembic downgrade -1
        result = subprocess.run(
            ["alembic", "downgrade", "-1"],
            check=True,
            capture_output=True,
            text=True,
        )
        
        print(result.stdout)
        
        print("\n" + "="*60)
        print("Rollback completed successfully!")
        print("="*60)
        sys.exit(0)
        
    except subprocess.CalledProcessError as e:
        print("\n Rollback failed!")
        print(f"Error: {e.stderr}")
        print("\nTroubleshooting:")
        print("1. Ensure database is running and accessible")
        print("2. Check that there are migrations to rollback")
        print("3. Verify alembic.ini configuration")
        sys.exit(1)
    except FileNotFoundError:
        print("\n Alembic not found!")
        print("Install it with: pip install alembic")
        sys.exit(1)


if __name__ == "__main__":
    main()
