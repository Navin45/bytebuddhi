# ByteBuddhi - AI-Powered Coding Assistant

A production-grade AI coding assistant built with FastAPI, LangGraph, and PostgreSQL with pgvector. ByteBuddhi provides intelligent code understanding, generation, and chat capabilities similar to Cursor/GitHub Copilot.

## Features

- AI-Powered Chat: Multi-turn conversations with context awareness
- Project Management: Organize and track multiple codebases
- Semantic Code Search: Vector-based code retrieval using pgvector
- Code Generation: LangGraph-powered agent for intelligent code generation
- Authentication: JWT-based auth with refresh tokens
- Real-time Streaming: SSE-based token streaming for LLM responses
- Clean Architecture: Hexagonal architecture with strict separation of concerns

## Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **AI Framework**: LangGraph + LangChain
- **LLM Providers**: OpenAI, Anthropic
- **Database**: Supabase (PostgreSQL 16+ with pgvector)
- **Cache**: Redis 7+
- **ORM**: SQLAlchemy 2.0+ (async)
- **Package Manager**: uv (Astral)
- **Observability**: LangSmith

## Project Structure

```text
server/
├── app/
│   ├── domain/              # Pure business logic
│   ├── application/         # Use cases and interfaces
│   ├── infrastructure/      # External integrations
│   └── interfaces/          # API endpoints
├── tests/                   # Unit, integration, e2e tests
├── scripts/                 # Utility scripts
└── docker-compose.yml       # Docker setup
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for Redis)
- uv package manager
- Supabase account (free tier works)

### Installation

1. **Clone the repository**

   ```bash
   cd bytebuddhi/server
   ```

2. **Install uv (if not already installed)**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Create virtual environment**

   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

4. **Install dependencies**

   ```bash
   uv pip install -r requirements.txt
   ```

5. **Setup environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

6. **Start services with Docker**

   ```bash
   docker-compose up -d
   ```

   This will start:
   - Redis (cache)
   - ByteBuddhi server (auto-reload enabled)

7. **Initialize database**

   ```bash
   python scripts/setup_db.py
   ```

8. **Run migrations**

   ```bash
   python scripts/migrate.py
   ```

The API will be available at `http://localhost:8000`
API documentation at `http://localhost:8000/api/docs`

> **Note**: For local development without Docker, use `python scripts/start_dev.py` instead of step 6.

## Development

### Running Tests

```bash
python scripts/run_tests.py
```

### Code Quality

```bash
# Format code
black app/ tests/

# Lint
ruff check app/ tests/

# Type check
mypy app/

# Sort imports
isort app/ tests/
```

### Database Migrations

```bash
# Create migration
python scripts/create_migration.py "description"

# Run migrations
python scripts/migrate.py

# Rollback
python scripts/rollback_migration.py
```

## API Endpoints

### Health

- `GET /api/v1/health` - Basic health check
- `GET /api/v1/health/db` - Database health check

### Authentication

- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login user
- `POST /api/v1/auth/refresh` - Refresh access token
- `GET /api/v1/auth/me` - Get current user info

### Projects

- `POST /api/v1/projects` - Create project
- `GET /api/v1/projects` - List user's projects
- `GET /api/v1/projects/{id}` - Get project details
- `PUT /api/v1/projects/{id}` - Update project
- `DELETE /api/v1/projects/{id}` - Delete project

### Chat

- `POST /api/v1/chat/conversations` - Create conversation
- `GET /api/v1/chat/conversations` - List conversations
- `GET /api/v1/chat/conversations/{id}` - Get conversation with messages
- `POST /api/v1/chat/conversations/{id}/messages` - Send message

## Configuration

All configuration is managed through environment variables. See `.env.example` for available options.

Key configurations:

- `DATABASE_URL`: Supabase PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY`: OpenAI API key
- `ANTHROPIC_API_KEY`: Anthropic API key
- `LANGCHAIN_API_KEY`: LangSmith API key
- `JWT_SECRET_KEY`: Secret for JWT tokens

## Architecture

ByteBuddhi follows hexagonal/clean architecture principles:

- **Domain Layer**: Pure business logic, zero dependencies
- **Application Layer**: Use cases and port interfaces
- **Infrastructure Layer**: External service implementations
- **Interface Layer**: API endpoints and entry points

This ensures:

- Testability
- Maintainability
- Flexibility to swap implementations
- Clear separation of concerns

## Contributing

1. Follow the existing code structure
2. Write tests for new features
3. Ensure all tests pass
4. Run code quality checks
5. Update documentation

## License

MIT

## Status

In Development - This project is actively being built.

Current Progress:

- Project structure
- Domain models
- Repository interfaces
- Database setup
- Basic API endpoints
- LangGraph agent (in progress)
- Authentication (in progress)
- Code indexing (in progress)
- Vector search (in progress)
- SSE streaming (in progress)

## Support

For issues and questions, please open an issue on GitHub.
