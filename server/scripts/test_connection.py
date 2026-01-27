#!/usr/bin/env python3
"""Test database connection with detailed diagnostics.

This script tests the database connection and provides
troubleshooting information if the connection fails.
"""

import asyncio
import os

import asyncpg
from dotenv import load_dotenv


async def test_connection(url: str) -> bool:
    """Test database connection.
    
    Args:
        url: Database connection URL
        
    Returns:
        bool: True if connection successful
    """
    print(f"\n{'='*60}")
    print("Testing Database Connection")
    print(f"{'='*60}")
    
    # Show sanitized URL
    if '@' in url:
        parts = url.split('@')
        user_pass = parts[0].split('://')[-1]
        user = user_pass.split(':')[0]
        sanitized = f"postgresql://{user}:****@{parts[1]}"
        print(f"URL: {sanitized}")
    
    try:
        conn = await asyncpg.connect(url)
        version = await conn.fetchval("SELECT version()")
        print(f"\n SUCCESS! Connected to:")
        print(f"   {version.split(',')[0]}")
        
        # Check for pgvector
        has_vector = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        if has_vector:
            vector_version = await conn.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            print(f"   pgvector: {vector_version} ")
        else:
            print(f"   pgvector: not installed ")
        
        await conn.close()
        return True
        
    except asyncpg.InvalidPasswordError:
        print("\n FAILED: Invalid password")
        return False
    except asyncpg.InvalidCatalogNameError:
        print("\n FAILED: Database not found")
        return False
    except Exception as e:
        print(f"\n FAILED: {type(e).__name__}: {e}")
        return False


def print_troubleshooting():
    """Print troubleshooting information."""
    print("\n" + "="*60)
    print("Troubleshooting Steps")
    print("="*60)
    print("\n1. Verify your DATABASE_URL in .env file:")
    print("   - Should start with: postgresql+asyncpg://")
    print("   - Format: postgresql+asyncpg://user:password@host:port/database")
    
    print("\n2. Check your database credentials:")
    print("   - Username is correct")
    print("   - Password is correct (no typos)")
    print("   - Database name exists")
    
    print("\n3. For Supabase users:")
    print("   - Go to: Settings → Database")
    print("   - Copy 'Connection string' (Session pooler)")
    print("   - Replace [YOUR-PASSWORD] with actual password")
    print("   - Change postgresql:// to postgresql+asyncpg://")
    
    print("\n4. Test network connectivity:")
    print("   - Ensure firewall allows database connections")
    print("   - Check if database host is reachable")
    
    print("\n5. For local PostgreSQL:")
    print("   - Ensure PostgreSQL is running")
    print("   - Default: postgresql+asyncpg://postgres:postgres@localhost:5432/bytebuddhi")


async def main():
    """Main function."""
    load_dotenv()
    
    print("="*60)
    print(" ByteBuddhi Database Connection Tester")
    print("="*60)
    
    # Get database URL
    database_url = os.getenv("DATABASE_URL", "")
    
    if not database_url:
        print("\n DATABASE_URL not found in .env file")
        print("\nPlease create a .env file with your database connection string:")
        print("DATABASE_URL=postgresql+asyncpg://user:password@host:port/database")
        return
    
    # Convert to asyncpg format for testing
    test_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    # Test connection
    success = await test_connection(test_url)
    
    if success:
        print("\n" + "="*60)
        print(" CONNECTION SUCCESSFUL!")
        print("="*60)
        print("\nYour database is ready!")
        print("Next step: python scripts/setup_db.py")
    else:
        print_troubleshooting()


if __name__ == "__main__":
    asyncio.run(main())
