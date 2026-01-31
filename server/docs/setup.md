# ByteBuddhi Setup Guide

Complete guide to setting up ByteBuddhi locally for development, including all dependencies, configuration, and troubleshooting.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Environment Configuration](#environment-configuration)
4. [Database Setup](#database-setup)
5. [Running the Application](#running-the-application)
6. [Development Workflow](#development-workflow)
7. [Testing](#testing)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before you begin, ensure you have the following installed:

### Required Software

- **Python 3.13+**: [Download Python](https://www.python.org/downloads/)
- **Docker & Docker Compose**: [Install Docker](https://docs.docker.com/get-docker/)
- **uv** (Package Manager): [Install uv](https://github.com/astral-sh/uv)
- **Git**: [Install Git](https://git-scm.com/downloads)

### External Services

You'll need accounts and API keys for:

1. **Supabase** (Database): [Sign up](https://supabase.com/)
2. **OpenAI** (LLM): [Get API key](https://platform.openai.com/api-keys)
3. **Anthropic** (Optional, Claude): [Get API key](https://console.anthropic.com/)
4. **Tavily** (Web Search): [Get API key](https://tavily.com/)
5. **LangSmith** (Optional, Observability): [Get API key](https://smith.langchain.com/)

---

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/bytebuddhi.git
cd bytebuddhi/server
```

### Step 2: Install uv Package Manager

**macOS/Linux**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows**:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Verify installation:

```bash
uv --version
# Output: uv 0.1.x
```

### Step 3: Create Virtual Environment

```bash
uv venv
```

**Activate the virtual environment**:

**macOS/Linux**:

```bash
source .venv/bin/activate
```

**Windows**:

```powershell
.venv\Scripts\activate
```

You should see `(.venv)` in your terminal prompt.

### Step 4: Install Dependencies

```bash
uv pip install -r requirements.txt
```

This installs all required packages including:

- FastAPI, Uvicorn (Web framework)
- LangChain, LangGraph (AI framework)
- SQLAlchemy, Alembic (Database)
- OpenAI, Anthropic (LLM providers)
- Tavily (Web search)
- Redis (Caching)
- And more...

**Verify installation**:

```bash
python -c "import fastapi; print(f'FastAPI {fastapi.__version__}')"
# Output: FastAPI 0.115.x
```

---

## Environment Configuration

### Step 1: Create .env File

Copy the example environment file:

```bash
cp .env.example .env
```

If `.env.example` doesn't exist, create `.env` manually:

```bash
touch .env
```

### Step 2: Configure Environment Variables

Open `.env` in your editor and configure the following:

```bash
# Application Settings
APP_NAME=ByteBuddhi
APP_ENV=development
DEBUG=true
LOG_LEVEL=INFO

# Server Configuration
HOST=0.0.0.0
PORT=8000
WORKERS=4

# Database Configuration (Supabase PostgreSQL)
DATABASE_URL=postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis Configuration
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=50

# JWT Authentication
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# OpenAI Configuration
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4-turbo-preview
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Anthropic Configuration (Optional)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Tavily Search Configuration
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxx
TAVILY_MAX_RESULTS=5

# LangSmith Configuration (Optional - for observability)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxxxxxxx
LANGCHAIN_PROJECT=bytebuddhi-dev

# CORS Configuration
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_HOUR=1000

# File Upload Configuration
MAX_UPLOAD_SIZE_MB=50
ALLOWED_EXTENSIONS=[".py",".js",".ts",".java",".go",".rs",".cpp",".c",".h"]
```

### Step 3: Get API Keys

#### Supabase (Database)

1. Go to [Supabase Dashboard](https://app.supabase.com/)
2. Create a new project
3. Go to **Settings** → **Database**
4. Copy the **Connection String** (Transaction mode)
5. Replace `postgresql://` with `postgresql+asyncpg://`
6. Update `DATABASE_URL` in `.env`

**Example**:

```
Original: postgresql://postgres.abc123:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
Updated:  postgresql+asyncpg://postgres.abc123:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

#### OpenAI

1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Click **Create new secret key**
3. Copy the key (starts with `sk-proj-`)
4. Update `OPENAI_API_KEY` in `.env`

#### Tavily (Web Search)

1. Go to [Tavily](https://tavily.com/)
2. Sign up for an account
3. Get your API key from the dashboard
4. Update `TAVILY_API_KEY` in `.env`

#### Generate JWT Secret

Generate a secure random key for JWT:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output and update `JWT_SECRET_KEY` in `.env`.

---

## Database Setup

### Step 1: Start Docker Services

ByteBuddhi uses Docker for Redis (and optionally PostgreSQL for local development).

```bash
docker-compose up -d
```

This starts:

- **Redis**: Cache service on port 6379

**Verify services are running**:

```bash
docker-compose ps
```

### Step 2: Test Database Connection

```bash
python scripts/test_connection.py
```

**Expected output**:

```
✅ Database connection successful!
Database: postgres
PostgreSQL version: 16.x
```

If you see errors, verify your `DATABASE_URL` in `.env`.

### Step 3: Run Database Migrations

Initialize the database schema:

```bash
python scripts/migrate.py
```

**Expected output**:

```
INFO  [alembic.runtime.migration] Running upgrade -> abc123, initial schema
INFO  [alembic.runtime.migration] Running upgrade abc123 -> def456, add users table
✅ Migrations completed successfully
```

### Step 4: Verify Database Setup

```bash
python scripts/setup_db.py
```

This script:

- Enables pgvector extension
- Creates necessary indexes
- Sets up Row Level Security (RLS) policies

---

## Running the Application

### Development Mode

**Option 1: Using the development script**:

```bash
python scripts/start_dev.py
```

**Option 2: Using uvicorn directly**:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Option 3: Using Docker Compose**:

```bash
docker-compose up
```

### Verify the Server is Running

Open your browser and navigate to:

- **API Docs**: <http://localhost:8000/api/docs>
- **Health Check**: <http://localhost:8000/api/v1/health>

**Test with curl**:

```bash
curl http://localhost:8000/api/v1/health
```

**Expected response**:

```json
{
  "status": "healthy",
  "timestamp": "2026-01-30T02:00:00Z",
  "version": "0.1.0"
}
```

---

## Development Workflow

### Code Quality Tools

ByteBuddhi uses several tools to maintain code quality:

#### Format Code

```bash
black app/ tests/
```

#### Lint Code

```bash
ruff check app/ tests/
```

#### Type Checking

```bash
mypy app/
```

#### Sort Imports

```bash
isort app/ tests/
```

#### Run All Quality Checks

```bash
# Format
black app/ tests/

# Sort imports
isort app/ tests/

# Lint
ruff check app/ tests/ --fix

# Type check
mypy app/
```

### Database Migrations

#### Create a New Migration

```bash
python scripts/create_migration.py "add user preferences table"
```

This creates a new migration file in `alembic/versions/`.

#### Run Migrations

```bash
python scripts/migrate.py
```

#### Rollback Migration

```bash
python scripts/rollback_migration.py
```

### Hot Reload

When running in development mode (`--reload`), the server automatically restarts when you make code changes.

**Example workflow**:

1. Start server: `python scripts/start_dev.py`
2. Edit `app/interfaces/api/v1/chat.py`
3. Save the file
4. Server automatically reloads
5. Test your changes immediately

---

## Testing

### Run All Tests

```bash
python scripts/run_tests.py
```

### Run Specific Test File

```bash
pytest tests/test_agent.py -v
```

### Run with Coverage

```bash
pytest --cov=app --cov-report=html
```

View coverage report:

```bash
open htmlcov/index.html
```

### Test Categories

- **Unit Tests**: Test individual functions/classes
- **Integration Tests**: Test component interactions
- **E2E Tests**: Test complete workflows

**Example - Test the Agent**:

```bash
pytest tests/application/test_agent.py -v
```

**Example - Test API Endpoints**:

```bash
pytest tests/interfaces/test_chat_api.py -v
```

### Test Tavily Integration

```bash
python scripts/test_tavily.py
```

**Expected output**:

```
✅ Tavily service initialized
🔍 Searching for: What are the latest features in Python 3.13?
✅ Search completed successfully!
📝 Quick Answer: Python 3.13 introduces a new JIT compiler...
```

---

## Troubleshooting

### Common Issues

#### 1. ModuleNotFoundError

**Error**:

```
ModuleNotFoundError: No module named 'fastapi'
```

**Solution**:

```bash
# Ensure virtual environment is activated
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows

# Reinstall dependencies
uv pip install -r requirements.txt
```

---

#### 2. Database Connection Failed

**Error**:

```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Solutions**:

**Check DATABASE_URL format**:

```bash
# Must use asyncpg driver
postgresql+asyncpg://user:password@host:port/database
```

**Verify Supabase credentials**:

1. Go to Supabase Dashboard
2. Settings → Database
3. Copy connection string
4. Ensure password is correct

**Test connection**:

```bash
python scripts/test_connection.py
```

---

#### 3. Redis Connection Failed

**Error**:

```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**Solution**:

```bash
# Start Redis with Docker
docker-compose up -d redis

# Verify Redis is running
docker ps | grep redis

# Test connection
redis-cli ping
# Expected: PONG
```

---

#### 4. Tavily API Key Invalid

**Error**:

```
Unauthorized: missing or invalid API key
```

**Solution**:

```bash
# Verify API key in .env
cat .env | grep TAVILY_API_KEY

# Ensure it starts with 'tvly-'
TAVILY_API_KEY=tvly-xxxxxxxxxxxxx

# Test Tavily
python scripts/test_tavily.py
```

---

#### 5. Port Already in Use

**Error**:

```
OSError: [Errno 48] Address already in use
```

**Solution**:

```bash
# Find process using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>

# Or use a different port
uvicorn app.main:app --port 8001
```

---

#### 6. Migration Conflicts

**Error**:

```
alembic.util.exc.CommandError: Target database is not up to date
```

**Solution**:

```bash
# Check current migration version
alembic current

# Upgrade to latest
python scripts/migrate.py

# If still failing, reset migrations (CAUTION: loses data)
alembic downgrade base
python scripts/migrate.py
```

---

### Debug Mode

Enable detailed logging:

```bash
# In .env
DEBUG=true
LOG_LEVEL=DEBUG
```

Restart the server to see detailed logs:

```bash
python scripts/start_dev.py
```

---

## Production Deployment

### Environment Variables

Update `.env` for production:

```bash
APP_ENV=production
DEBUG=false
LOG_LEVEL=WARNING

# Use strong JWT secret
JWT_SECRET_KEY=<generate-new-secret>

# Production database
DATABASE_URL=postgresql+asyncpg://...

# Production Redis
REDIS_URL=redis://production-redis:6379/0
```

### Build Docker Image

```bash
docker build -t bytebuddhi:latest .
```

### Run in Production

```bash
docker run -d \
  --name bytebuddhi \
  -p 8000:8000 \
  --env-file .env \
  bytebuddhi:latest
```

### Health Checks

Set up monitoring:

```bash
curl http://your-domain.com/api/v1/health
curl http://your-domain.com/api/v1/health/db
```

---

## Quick Start Summary

For the impatient, here's the TL;DR:

```bash
# 1. Clone and setup
git clone https://github.com/yourusername/bytebuddhi.git
cd bytebuddhi/server
uv venv && source .venv/bin/activate

# 2. Install dependencies
uv pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Start services
docker-compose up -d

# 5. Setup database
python scripts/migrate.py

# 6. Run server
python scripts/start_dev.py

# 7. Open browser
open http://localhost:8000/api/docs
```

---

## Next Steps

Now that you have ByteBuddhi running:

1. **Read the [Architecture Documentation](architecture.md)** to understand the codebase
2. **Explore the [API Documentation](api.md)** to learn about available endpoints
3. **Try the interactive API docs** at <http://localhost:8000/api/docs>
4. **Create your first project** and start chatting with the AI agent
5. **Contribute** by submitting issues or pull requests

---

## Getting Help

If you encounter issues:

1. **Check the logs**: Look for error messages in the console
2. **Review this guide**: Ensure all steps were followed
3. **Search existing issues**: [GitHub Issues](https://github.com/yourusername/bytebuddhi/issues)
4. **Ask for help**: Create a new issue with:
   - Error message
   - Steps to reproduce
   - Environment details (OS, Python version, etc.)

---

## Summary

You now have:

- ByteBuddhi installed and running locally
- Database configured with Supabase
- AI capabilities with OpenAI/Anthropic
- Web search with Tavily
- Development tools configured
- Testing framework ready

Happy coding! 🚀
