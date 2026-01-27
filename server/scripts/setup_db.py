#!/usr/bin/env python3
"""Database setup script for ByteBuddhi.

This script:
1. Tests database connection
2. Enables required PostgreSQL extensions (pgvector, uuid-ossp)
3. Verifies setup is complete
"""

import asyncio
import sys
from pathlib import Path

# Add the server directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.infrastructure.config.logger import get_logger, setup_logging
from app.infrastructure.persistence.postgres.database import engine

setup_logging()
logger = get_logger(__name__)


async def test_connection() -> bool:
    """Test database connection.
    
    Returns:
        bool: True if connection successful
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
            return True
    except Exception as e:
        logger.error("❌ Database connection failed", error=str(e))
        return False


async def enable_extensions() -> bool:
    """Enable required PostgreSQL extensions.
    
    Returns:
        bool: True if all extensions enabled successfully
    """
    extensions = [
        ("vector", "pgvector - for vector similarity search"),
        ("uuid-ossp", "uuid-ossp - for UUID generation"),
    ]
    
    try:
        async with engine.begin() as conn:
            for ext_name, description in extensions:
                logger.info(f"Checking {description}...")
                
                # Check if extension exists
                result = await conn.execute(
                    text(f"SELECT * FROM pg_extension WHERE extname = '{ext_name}'")
                )
                
                if result.fetchone():
                    logger.info(f"✅ {ext_name} already enabled")
                else:
                    logger.info(f"Enabling {ext_name}...")
                    try:
                        if ext_name == "uuid-ossp":
                            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext_name}"'))
                        else:
                            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext_name}"))
                        logger.info(f"✅ {ext_name} enabled successfully")
                    except Exception as e:
                        logger.error(f"❌ Failed to enable {ext_name}", error=str(e))
                        if ext_name == "vector":
                            logger.info(
                                "Note: You may need to enable pgvector in your database dashboard"
                            )
                        return False
            
            return True
    except Exception as e:
        logger.error("❌ Failed to enable extensions", error=str(e))
        return False


async def verify_setup() -> bool:
    """Verify database setup is complete.
    
    Returns:
        bool: True if setup verified
    """
    try:
        async with engine.begin() as conn:
            # Check PostgreSQL version
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            logger.info(f"PostgreSQL version: {version.split(',')[0]}")
            
            # Check pgvector version
            result = await conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            vector_version = result.scalar()
            if vector_version:
                logger.info(f"pgvector version: {vector_version}")
            
            return True
    except Exception as e:
        logger.error("❌ Setup verification failed", error=str(e))
        return False


async def main():
    """Main setup function."""
    logger.info("="*60)
    logger.info("🗄️  ByteBuddhi Database Setup")
    logger.info("="*60)
    
    # Test connection
    if not await test_connection():
        logger.error("\nTroubleshooting:")
        logger.error("1. Check your DATABASE_URL in .env file")
        logger.error("2. Ensure it uses postgresql+asyncpg:// prefix")
        logger.error("3. Verify your database credentials")
        logger.error("4. Run: python scripts/test_connection.py for detailed diagnostics")
        await engine.dispose()
        sys.exit(1)
    
    # Enable extensions
    if not await enable_extensions():
        logger.error("\nSetup failed. Please check the errors above.")
        await engine.dispose()
        sys.exit(1)
    
    # Verify setup
    if not await verify_setup():
        await engine.dispose()
        sys.exit(1)
    
    logger.info("\n" + "="*60)
    logger.info("🎉 Database setup completed successfully!")
    logger.info("="*60)
    logger.info("\nNext steps:")
    logger.info("1. Run migrations: alembic upgrade head")
    logger.info("2. Start development server: python scripts/start_dev.py")
    
    await engine.dispose()
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
