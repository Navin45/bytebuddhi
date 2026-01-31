# ByteBuddhi API Documentation

Complete API reference for ByteBuddhi with detailed examples, request/response formats, and real-world usage scenarios.

## Table of Contents

1. [Base URL](#base-url)
2. [Authentication](#authentication)
3. [Health Endpoints](#health-endpoints)
4. [Authentication Endpoints](#authentication-endpoints)
5. [Project Endpoints](#project-endpoints)
6. [File Endpoints](#file-endpoints)
7. [Chat Endpoints](#chat-endpoints)
8. [Error Handling](#error-handling)
9. [Rate Limiting](#rate-limiting)

---

## Base URL

```
Development: http://localhost:8000
Production: https://api.bytebuddhi.com
```

All API endpoints are prefixed with `/api/v1`

**Example**: `http://localhost:8000/api/v1/health`

---

## Authentication

ByteBuddhi uses **JWT (JSON Web Tokens)** for authentication.

### Authentication Flow

```
1. Register/Login → Receive access_token + refresh_token
2. Include access_token in Authorization header for protected endpoints
3. When access_token expires, use refresh_token to get new tokens
```

### Authorization Header Format

```http
Authorization: Bearer <access_token>
```

**Example**:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## Health Endpoints

### Check API Health

**Endpoint**: `GET /api/v1/health`

**Description**: Basic health check to verify the API is running.

**Authentication**: Not required

**Response**:

```json
{
  "status": "healthy",
  "timestamp": "2026-01-30T02:00:00Z",
  "version": "0.1.0"
}
```

**Example Request**:

```bash
curl http://localhost:8000/api/v1/health
```

---

### Check Database Health

**Endpoint**: `GET /api/v1/health/db`

**Description**: Verify database connectivity.

**Authentication**: Not required

**Response**:

```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-01-30T02:00:00Z"
}
```

**Example Request**:

```bash
curl http://localhost:8000/api/v1/health/db
```

---

## Authentication Endpoints

### Register New User

**Endpoint**: `POST /api/v1/auth/register`

**Description**: Create a new user account.

**Authentication**: Not required

**Request Body**:

```json
{
  "email": "developer@example.com",
  "username": "johndoe",
  "password": "SecurePassword123!"
}
```

**Response** (201 Created):

```json
{
  "user": {
    "id": "usr_1234567890",
    "email": "developer@example.com",
    "username": "johndoe",
    "created_at": "2026-01-30T02:00:00Z",
    "is_active": true
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Real-Life Example**:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "developer@example.com",
    "username": "johndoe",
    "password": "SecurePassword123!"
  }'
```

**Error Responses**:

- `400 Bad Request`: Invalid email format or weak password
- `409 Conflict`: Email or username already exists

---

### Login

**Endpoint**: `POST /api/v1/auth/login`

**Description**: Authenticate and receive access tokens.

**Authentication**: Not required

**Request Body**:

```json
{
  "email": "developer@example.com",
  "password": "SecurePassword123!"
}
```

**Response** (200 OK):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Real-Life Example**:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "developer@example.com",
    "password": "SecurePassword123!"
  }'
```

---

### Refresh Access Token

**Endpoint**: `POST /api/v1/auth/refresh`

**Description**: Get a new access token using refresh token.

**Authentication**: Requires refresh token

**Request Body**:

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response** (200 OK):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Real-Life Example**:

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

---

### Get Current User

**Endpoint**: `GET /api/v1/auth/me`

**Description**: Get authenticated user's information.

**Authentication**: Required

**Response** (200 OK):

```json
{
  "id": "usr_1234567890",
  "email": "developer@example.com",
  "username": "johndoe",
  "created_at": "2026-01-30T02:00:00Z",
  "is_active": true
}
```

**Real-Life Example**:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## Project Endpoints

### Create Project

**Endpoint**: `POST /api/v1/projects`

**Description**: Create a new coding project.

**Authentication**: Required

**Request Body**:

```json
{
  "name": "FastAPI E-commerce API",
  "description": "RESTful API for an e-commerce platform",
  "language": "python",
  "framework": "fastapi",
  "repository_url": "https://github.com/johndoe/ecommerce-api"
}
```

**Response** (201 Created):

```json
{
  "id": "proj_9876543210",
  "name": "FastAPI E-commerce API",
  "description": "RESTful API for an e-commerce platform",
  "language": "python",
  "framework": "fastapi",
  "repository_url": "https://github.com/johndoe/ecommerce-api",
  "user_id": "usr_1234567890",
  "created_at": "2026-01-30T02:00:00Z",
  "updated_at": "2026-01-30T02:00:00Z",
  "file_count": 0
}
```

**Real-Life Example**:

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "FastAPI E-commerce API",
    "description": "RESTful API for an e-commerce platform",
    "language": "python",
    "framework": "fastapi"
  }'
```

---

### List Projects

**Endpoint**: `GET /api/v1/projects`

**Description**: Get all projects for authenticated user.

**Authentication**: Required

**Query Parameters**:

- `limit` (optional): Number of projects to return (default: 20)
- `offset` (optional): Pagination offset (default: 0)

**Response** (200 OK):

```json
{
  "projects": [
    {
      "id": "proj_9876543210",
      "name": "FastAPI E-commerce API",
      "description": "RESTful API for an e-commerce platform",
      "language": "python",
      "framework": "fastapi",
      "created_at": "2026-01-30T02:00:00Z",
      "file_count": 15
    },
    {
      "id": "proj_1111111111",
      "name": "React Dashboard",
      "description": "Admin dashboard built with React",
      "language": "javascript",
      "framework": "react",
      "created_at": "2026-01-29T10:00:00Z",
      "file_count": 42
    }
  ],
  "total": 2,
  "limit": 20,
  "offset": 0
}
```

**Real-Life Example**:

```bash
curl http://localhost:8000/api/v1/projects?limit=10 \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### Get Project Details

**Endpoint**: `GET /api/v1/projects/{project_id}`

**Description**: Get detailed information about a specific project.

**Authentication**: Required

**Response** (200 OK):

```json
{
  "id": "proj_9876543210",
  "name": "FastAPI E-commerce API",
  "description": "RESTful API for an e-commerce platform",
  "language": "python",
  "framework": "fastapi",
  "repository_url": "https://github.com/johndoe/ecommerce-api",
  "user_id": "usr_1234567890",
  "created_at": "2026-01-30T02:00:00Z",
  "updated_at": "2026-01-30T02:00:00Z",
  "file_count": 15,
  "files": [
    {
      "id": "file_1111111111",
      "path": "app/main.py",
      "language": "python",
      "size_bytes": 2048
    }
  ]
}
```

**Real-Life Example**:

```bash
curl http://localhost:8000/api/v1/projects/proj_9876543210 \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### Update Project

**Endpoint**: `PUT /api/v1/projects/{project_id}`

**Description**: Update project information.

**Authentication**: Required

**Request Body**:

```json
{
  "name": "FastAPI E-commerce API v2",
  "description": "Updated description with new features"
}
```

**Response** (200 OK):

```json
{
  "id": "proj_9876543210",
  "name": "FastAPI E-commerce API v2",
  "description": "Updated description with new features",
  "updated_at": "2026-01-30T03:00:00Z"
}
```

---

### Delete Project

**Endpoint**: `DELETE /api/v1/projects/{project_id}`

**Description**: Delete a project and all associated files.

**Authentication**: Required

**Response** (204 No Content)

**Real-Life Example**:

```bash
curl -X DELETE http://localhost:8000/api/v1/projects/proj_9876543210 \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## Chat Endpoints

### Create Conversation

**Endpoint**: `POST /api/v1/chat/conversations`

**Description**: Start a new conversation with the AI agent.

**Authentication**: Required

**Request Body**:

```json
{
  "project_id": "proj_9876543210",
  "title": "Help with FastAPI authentication"
}
```

**Response** (201 Created):

```json
{
  "id": "conv_5555555555",
  "project_id": "proj_9876543210",
  "title": "Help with FastAPI authentication",
  "user_id": "usr_1234567890",
  "created_at": "2026-01-30T02:00:00Z",
  "message_count": 0
}
```

**Real-Life Example**:

```bash
curl -X POST http://localhost:8000/api/v1/chat/conversations \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_9876543210",
    "title": "Help with FastAPI authentication"
  }'
```

---

### List Conversations

**Endpoint**: `GET /api/v1/chat/conversations`

**Description**: Get all conversations for authenticated user.

**Authentication**: Required

**Query Parameters**:

- `project_id` (optional): Filter by project
- `limit` (optional): Number of conversations (default: 20)
- `offset` (optional): Pagination offset (default: 0)

**Response** (200 OK):

```json
{
  "conversations": [
    {
      "id": "conv_5555555555",
      "title": "Help with FastAPI authentication",
      "project_id": "proj_9876543210",
      "created_at": "2026-01-30T02:00:00Z",
      "message_count": 5,
      "last_message_at": "2026-01-30T02:15:00Z"
    }
  ],
  "total": 1
}
```

---

### Get Conversation with Messages

**Endpoint**: `GET /api/v1/chat/conversations/{conversation_id}`

**Description**: Get conversation details including all messages.

**Authentication**: Required

**Response** (200 OK):

```json
{
  "id": "conv_5555555555",
  "title": "Help with FastAPI authentication",
  "project_id": "proj_9876543210",
  "created_at": "2026-01-30T02:00:00Z",
  "messages": [
    {
      "id": "msg_1111111111",
      "role": "user",
      "content": "How do I implement JWT authentication in FastAPI?",
      "created_at": "2026-01-30T02:00:00Z"
    },
    {
      "id": "msg_2222222222",
      "role": "assistant",
      "content": "To implement JWT authentication in FastAPI, you'll need...",
      "created_at": "2026-01-30T02:00:05Z"
    }
  ]
}
```

---

### Send Message

**Endpoint**: `POST /api/v1/chat/conversations/{conversation_id}/messages`

**Description**: Send a message to the AI agent and get a response.

**Authentication**: Required

**Request Body**:

```json
{
  "content": "What are the latest features in Python 3.13?",
  "context": {
    "files": ["app/main.py"],
    "include_project_context": true
  }
}
```

**Response** (200 OK):

```json
{
  "message": {
    "id": "msg_3333333333",
    "role": "user",
    "content": "What are the latest features in Python 3.13?",
    "created_at": "2026-01-30T02:10:00Z"
  },
  "response": {
    "id": "msg_4444444444",
    "role": "assistant",
    "content": "Python 3.13 introduces several exciting features:\n\n1. **JIT Compiler**: A new just-in-time compiler for improved performance...\n2. **No-GIL Edition**: The first version without the Global Interpreter Lock...\n3. **Enhanced Error Messages**: Better debugging with improved traceback...",
    "created_at": "2026-01-30T02:10:05Z",
    "metadata": {
      "intent": "web_search",
      "search_results": {
        "query": "Python 3.13 features",
        "sources": [
          "https://www.python.org/downloads/release/python-3130/",
          "https://docs.python.org/3.13/whatsnew/3.13.html"
        ]
      }
    }
  }
}
```

**Real-Life Example - Code Generation**:

```bash
curl -X POST http://localhost:8000/api/v1/chat/conversations/conv_5555555555/messages \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Create a FastAPI endpoint for user registration with email validation"
  }'
```

**Response**:

```json
{
  "response": {
    "content": "Here's a FastAPI endpoint for user registration with email validation:\n\n```python\nfrom fastapi import APIRouter, HTTPException\nfrom pydantic import BaseModel, EmailStr\n\nrouter = APIRouter()\n\nclass UserRegister(BaseModel):\n    email: EmailStr\n    username: str\n    password: str\n\n@router.post('/register')\nasync def register_user(user: UserRegister):\n    # Email validation is automatic via EmailStr\n    # Add your registration logic here\n    return {'message': 'User registered successfully'}\n```",
    "metadata": {
      "intent": "code_generation",
      "generated_code": true
    }
  }
}
```

**Real-Life Example - Web Search**:

```bash
curl -X POST http://localhost:8000/api/v1/chat/conversations/conv_5555555555/messages \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What is the current stable version of FastAPI?"
  }'
```

**Response**:

```json
{
  "response": {
    "content": "The current stable version of FastAPI is 0.115.0, released in January 2026. This version includes improved type hints, better async support, and enhanced OpenAPI documentation generation.",
    "metadata": {
      "intent": "web_search",
      "search_results": {
        "answer": "FastAPI 0.115.0 is the latest stable release",
        "sources": [
          "https://fastapi.tiangolo.com/release-notes/",
          "https://github.com/tiangolo/fastapi/releases"
        ]
      }
    }
  }
}
```

---

## Error Handling

All errors follow a consistent format:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {
      "field": "Additional context"
    }
  }
}
```

### Common Error Codes

| Status Code | Error Code | Description |
|-------------|------------|-------------|
| 400 | `INVALID_REQUEST` | Request validation failed |
| 401 | `UNAUTHORIZED` | Missing or invalid authentication |
| 403 | `FORBIDDEN` | Insufficient permissions |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | Resource already exists |
| 422 | `VALIDATION_ERROR` | Request body validation failed |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Server error |

**Example Error Response**:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid email format",
    "details": {
      "field": "email",
      "value": "invalid-email"
    }
  }
}
```

---

## Rate Limiting

ByteBuddhi implements rate limiting to ensure fair usage:

- **Per Minute**: 60 requests
- **Per Hour**: 1000 requests

Rate limit headers are included in responses:

```http
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1706587200
```

When rate limit is exceeded:

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. Please try again in 30 seconds.",
    "details": {
      "retry_after": 30
    }
  }
}
```

---

## Complete Usage Example

Here's a complete workflow from registration to getting AI assistance:

```bash
# 1. Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "username": "developer", "password": "SecurePass123!"}'

# Save the access_token from response
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# 2. Create a project
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "My FastAPI App", "language": "python", "framework": "fastapi"}'

# Save project_id
export PROJECT_ID="proj_9876543210"

# 3. Start a conversation
curl -X POST http://localhost:8000/api/v1/chat/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"title\": \"Getting Started\"}"

# Save conversation_id
export CONV_ID="conv_5555555555"

# 4. Ask for help
curl -X POST http://localhost:8000/api/v1/chat/conversations/$CONV_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Create a user authentication endpoint with JWT"}'

# 5. Ask about current tech
curl -X POST http://localhost:8000/api/v1/chat/conversations/$CONV_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "What are the latest features in FastAPI?"}'
```

---

## Summary

ByteBuddhi's API provides:

- ✅ **RESTful design** with consistent patterns
- ✅ **JWT authentication** for secure access
- ✅ **Project management** for organizing code
- ✅ **Intelligent chat** with context-aware AI
- ✅ **Web search capability** for current information
- ✅ **Comprehensive error handling** with clear messages
- ✅ **Rate limiting** for fair usage

For more information, see the [Architecture Documentation](architecture.md) and [Setup Guide](setup.md).
