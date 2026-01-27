#!/usr/bin/env python3
"""Create a new Alembic migration.

This script creates a new database migration file using Alembic's
autogenerate feature to detect schema changes.
"""

import subprocess
import sys


def main():
    """Create a new migration."""
    if len(sys.argv) < 2:
        print(" Usage: python scripts/create_migration.py \"migration description\"")
        print("\nExample:")
        print("  python scripts/create_migration.py \"add user table\"")
        sys.exit(1)
    
    description = sys.argv[1]
    
    print("="*60)
    print(f"Creating Migration: {description}")
    print("="*60)
    
    try:
        # Run alembic revision with autogenerate
        result = subprocess.run(
            ["alembic", "revision", "--autogenerate", "-m", description],
            check=True,
            capture_output=True,
            text=True,
        )
        
        print(result.stdout)
        
        print("\n" + "="*60)
        print("Migration created successfully!")
        print("="*60)
        print("\nNext steps:")
        print("1. Review the generated migration file")
        print("2. Make any necessary manual adjustments")
        print("3. Run: python scripts/migrate.py")
        sys.exit(0)
        
    except subprocess.CalledProcessError as e:
        print("\n Migration creation failed!")
        print(f"Error: {e.stderr}")
        print("\nTroubleshooting:")
        print("1. Ensure database is running and accessible")
        print("2. Check that models are properly defined")
        print("3. Verify alembic.ini configuration")
        sys.exit(1)
    except FileNotFoundError:
        print("\n Alembic not found!")
        print("Install it with: pip install alembic")
        sys.exit(1)


if __name__ == "__main__":
    main()
