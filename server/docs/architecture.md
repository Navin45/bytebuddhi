# ByteBuddhi Architecture - Complete Guide

This document provides an exhaustive explanation of ByteBuddhi's architecture, explaining every concept, pattern, and file with real-life examples.

## Table of Contents

1. [Core Concepts Explained](#core-concepts-explained)
2. [Clean Architecture Pattern](#clean-architecture-pattern)
3. [Domain Layer - Complete Breakdown](#domain-layer---complete-breakdown)
4. [Application Layer - Complete Breakdown](#application-layer---complete-breakdown)
5. [Infrastructure Layer - Complete Breakdown](#infrastructure-layer---complete-breakdown)
6. [Interface Layer - Complete Breakdown](#interface-layer---complete-breakdown)
7. [File-by-File Explanation](#file-by-file-explanation)
8. [Real-World Examples](#real-world-examples)

---

## Core Concepts Explained

### What is a Domain?

**Domain** = The core business logic and rules of your application, completely independent of technical details.

**Real-Life Analogy**: Think of a restaurant's kitchen. The domain is the recipes and cooking rules - they don't care if you're using a gas stove or electric, or whether orders come via phone or app. The recipe for making pizza is the same regardless of technology.

**In ByteBuddhi**: The domain includes concepts like "User", "Project", "Conversation" - these exist regardless of whether we use PostgreSQL or MongoDB, FastAPI or Flask.

---

### What is a DTO (Data Transfer Object)?

**DTO** = A simple object that carries data between layers, with no business logic.

**Real-Life Analogy**: Like a delivery box. It just carries items from point A to point B. It doesn't cook food, it doesn't process orders - it just transports data.

**Example**:

```python
# This is a DTO - just data, no logic
class CreateProjectDTO:
    name: str
    description: str
    language: str
```

**Why use DTOs?**

- **Validation**: Ensure data is correct before it reaches business logic
- **Decoupling**: API can change without affecting domain
- **Security**: Only expose what's needed (hide password_hash, etc.)

---

### What is a Model/Entity?

**Model/Entity** = A domain object with business logic and rules.

**Real-Life Analogy**: A car. It's not just data (color, brand, year) - it has behaviors (start engine, accelerate, brake) and rules (can't drive without fuel).

**Example**:

```python
# This is a Model - has data AND behavior
class User:
    email: str
    password_hash: str
    is_active: bool
    
    def deactivate(self):  # Business logic
        self.is_active = False
        
    def can_create_project(self):  # Business rule
        return self.is_active and self.usage_quota > 0
```

---

### What is a Value Object?

**Value Object** = An immutable object defined by its value, not identity.

**Real-Life Analogy**: Money. Two $10 bills are the same - you don't care which specific bill you have, just that it's $10. Compare to a person - two people named "Navin" are NOT the same person.

**Example**:

```python
# Value Object - defined by value
class Email:
    def __init__(self, value: str):
        if "@" not in value:
            raise ValueError("Invalid email")
        self.value = value
    
# Two emails with same value are equal
email1 = Email("user@example.com")
email2 = Email("user@example.com")
# email1 == email2  (same value = same object)

# Compare to Entity - defined by identity
user1 = User(id=1, email="user@example.com")
user2 = User(id=2, email="user@example.com")
# user1 != user2  (different IDs = different users)
```

---

### What is a Repository?

**Repository** = An interface for accessing and storing domain objects, hiding database details.

**Real-Life Analogy**: A library. You ask the librarian for a book, you don't care if it's stored on shelf A or B, or in what order. The librarian handles the details.

**Example**:

```python
# Repository interface (what you want to do)
class UserRepository:
    def find_by_email(self, email: str) -> User:
        pass
    
    def save(self, user: User) -> User:
        pass

# Implementation (how it's done - hidden from business logic)
class PostgresUserRepository(UserRepository):
    def find_by_email(self, email: str) -> User:
        # SQL query details here
        result = db.execute("SELECT * FROM users WHERE email = ?", email)
        return User(**result)
```

---

### What is a Use Case?

**Use Case** = A specific action a user wants to perform, orchestrating domain logic.

**Real-Life Analogy**: Ordering food at a restaurant. The use case is "Place Order" which involves: check menu (domain), verify payment (domain), create order (domain), notify kitchen (infrastructure).

**Example**:

```python
class CreateProjectUseCase:
    def execute(self, user_id: str, project_data: CreateProjectDTO):
        # 1. Get user (repository)
        user = self.user_repo.find_by_id(user_id)
        
        # 2. Check business rules (domain)
        if not user.can_create_project():
            raise QuotaExceededError()
        
        # 3. Create project (domain)
        project = Project.create(user_id, project_data.name)
        
        # 4. Save (repository)
        return self.project_repo.save(project)
```

---

### What is a Handler?

**Handler** = Processes incoming requests and delegates to use cases.

**Real-Life Analogy**: A receptionist. They receive your request, understand what you need, direct you to the right department, and give you the response.

**Example**:

```python
# Handler (in FastAPI route)
@router.post("/projects")
async def create_project(
    request: CreateProjectRequest,  # DTO from API
    user: User = Depends(get_current_user)  # Authentication
):
    # 1. Convert API DTO to application DTO
    dto = CreateProjectDTO(
        user_id=user.id,
        name=request.name,
        description=request.description
    )
    
    # 2. Call use case
    project = await create_project_use_case.execute(dto)
    
    # 3. Convert domain model to API response
    return ProjectResponseDTO.from_domain(project)
```

---

### What is a Service?

**Service** = Contains business logic that doesn't belong to a single entity.

**Real-Life Analogy**: A shipping company. It's not part of the product or the customer, but it handles the logic of getting products to customers.

**Example**:

```python
# Domain Service - business logic involving multiple entities
class ProjectIndexingService:
    def index_project_files(self, project: Project, files: List[File]):
        # Logic that involves both Project and Files
        for file in files:
            # Parse file
            chunks = self.parse_file(file)
            
            # Generate embeddings
            embeddings = self.embedding_service.generate(chunks)
            
            # Store in vector database
            self.vector_store.save(project.id, embeddings)
```

---

### What is a Port?

**Port** = An interface that defines what the application needs from external services.

**Real-Life Analogy**: An electrical outlet. It defines the interface (voltage, plug shape) but doesn't care if the power comes from solar, coal, or nuclear.

**Example**:

```python
# Port (interface) - what we need
class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: List[Dict]) -> str:
        pass

# Adapter (implementation) - how it's done
class OpenAIProvider(LLMProvider):
    async def generate(self, messages: List[Dict]) -> str:
        response = await openai.chat.completions.create(
            model="gpt-4",
            messages=messages
        )
        return response.choices[0].message.content

class AnthropicProvider(LLMProvider):
    async def generate(self, messages: List[Dict]) -> str:
        response = await anthropic.messages.create(
            model="claude-3-5-sonnet",
            messages=messages
        )
        return response.content[0].text
```

---

## Clean Architecture Pattern

### The Four Layers

```
┌─────────────────────────────────────────────────────────┐
│                   Interface Layer                        │
│         (HTTP, CLI, GraphQL - How users interact)        │
│                                                          │
│  Files: routes, controllers, request/response models    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Application Layer                       │
│        (Use cases, DTOs, Ports - What app does)         │
│                                                          │
│  Files: use_cases, dto, ports, agent                    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Domain Layer                           │
│       (Business logic, Entities - Core rules)            │
│                                                          │
│  Files: models, value_objects, services, exceptions     │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                Infrastructure Layer                      │
│    (Database, APIs, External - How things are done)     │
│                                                          │
│  Files: persistence, llm, external, auth, config        │
└─────────────────────────────────────────────────────────┘
```

### Dependency Rule

**Rule**: Dependencies point INWARD. Outer layers depend on inner layers, never the reverse.

- Interface Layer → Application Layer ✓
- Application Layer → Domain Layer ✓
- Infrastructure Layer → Application Layer (via interfaces) ✓
- Domain Layer → Infrastructure Layer ✗ NEVER

**Why?** Business logic should be independent of technical details. You should be able to change databases without changing business rules.

---

## Domain Layer - Complete Breakdown

**Location**: `app/domain/`

**Purpose**: Pure business logic with ZERO external dependencies.

### Directory Structure

```
domain/
├── models/              # Entities with business logic
│   ├── user.py         # User entity
│   ├── project.py      # Project entity
│   ├── file.py         # File entity
│   ├── conversation.py # Conversation entity
│   ├── message.py      # Message entity
│   ├── code_chunk.py   # Code chunk entity
│   └── embedding.py    # Embedding entity
├── value_objects/      # Immutable value objects
│   ├── email.py        # Email value object
│   ├── file_path.py    # File path value object
│   └── language.py     # Programming language value object
├── services/           # Domain services
│   ├── project_indexing_service.py
│   ├── conversation_context_service.py
│   └── quota_management_service.py
└── exceptions/         # Domain-specific exceptions
    ├── base.py
    ├── project_exceptions.py
    └── conversation_exceptions.py
```

### File Explanations

#### `domain/models/user.py`

**What it is**: The User entity representing a ByteBuddhi user.

**Real-Life Example**:

```python
class User:
    """A user in the ByteBuddhi system."""
    
    def __init__(self, id, email, username, password_hash, ...):
        self.id = id
        self.email = email
        self.username = username
        self.password_hash = password_hash
        self.is_active = True
        self.usage_quota = 1000
    
    # Business logic methods
    def deactivate(self):
        """Deactivate user account - business rule"""
        self.is_active = False
        self.updated_at = datetime.utcnow()
    
    def can_create_project(self) -> bool:
        """Business rule: active users with quota can create projects"""
        return self.is_active and self.usage_quota > 0
    
    def consume_quota(self, amount: int):
        """Business rule: decrease quota when using AI features"""
        if amount > self.usage_quota:
            raise QuotaExceededError()
        self.usage_quota -= amount
```

**Why it's in Domain**: These rules exist regardless of technology. Whether we use PostgreSQL or MongoDB, a deactivated user can't create projects.

---

#### `domain/models/project.py`

**What it is**: Represents a coding project with files and metadata.

**Real-Life Example**:

```python
class Project:
    """A coding project in ByteBuddhi."""
    
    def __init__(self, id, user_id, name, description, ...):
        self.id = id
        self.user_id = user_id
        self.name = name
        self.description = description
        self.files = []
        self.is_active = True
        self.last_indexed_at = None
    
    def add_file(self, file: File):
        """Business rule: add file to project"""
        if not self.is_active:
            raise ProjectInactiveError()
        self.files.append(file)
    
    def mark_as_indexed(self):
        """Business rule: update indexing timestamp"""
        self.last_indexed_at = datetime.utcnow()
    
    def needs_reindexing(self) -> bool:
        """Business rule: reindex if > 24 hours old"""
        if not self.last_indexed_at:
            return True
        age = datetime.utcnow() - self.last_indexed_at
        return age.total_seconds() > 86400  # 24 hours
```

---

#### `domain/value_objects/email.py`

**What it is**: Email value object with validation.

**Real-Life Example**:

```python
class Email:
    """Email value object - immutable and validated."""
    
    def __init__(self, value: str):
        # Validation logic
        if not self._is_valid(value):
            raise InvalidEmailError(f"Invalid email: {value}")
        self._value = value
    
    @property
    def value(self) -> str:
        return self._value
    
    def _is_valid(self, email: str) -> bool:
        """Business rule: email format validation"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def domain(self) -> str:
        """Extract domain from email"""
        return self._value.split('@')[1]
    
    def __eq__(self, other):
        """Two emails are equal if values match"""
        return isinstance(other, Email) and self._value == other._value
```

**Usage**:

```python
# Valid email
email = Email("user@example.com")
print(email.domain())  # "example.com"

# Invalid email - raises exception
email = Email("invalid-email")  # ❌ InvalidEmailError
```

---

#### `domain/services/project_indexing_service.py`

**What it is**: Service for indexing project files (business logic involving multiple entities).

**Real-Life Example**:

```python
class ProjectIndexingService:
    """Service for indexing project files into vector store."""
    
    def index_project(self, project: Project, files: List[File]):
        """
        Business logic for indexing a project.
        
        This involves:
        1. Parsing files into chunks
        2. Generating embeddings
        3. Storing in vector database
        """
        # Business rule: only index active projects
        if not project.is_active:
            raise ProjectInactiveError()
        
        all_chunks = []
        
        for file in files:
            # Business rule: only index supported languages
            if not self._is_supported_language(file.language):
                continue
            
            # Parse file into chunks
            chunks = self._parse_file(file)
            all_chunks.extend(chunks)
        
        # Mark project as indexed
        project.mark_as_indexed()
        
        return all_chunks
    
    def _is_supported_language(self, language: str) -> bool:
        """Business rule: supported programming languages"""
        return language in ['python', 'javascript', 'typescript', 'java']
    
    def _parse_file(self, file: File) -> List[CodeChunk]:
        """Parse file into semantic chunks"""
        # Parsing logic here
        pass
```

---

#### `domain/exceptions/project_exceptions.py`

**What it is**: Domain-specific exceptions for project operations.

**Real-Life Example**:

```python
class ProjectException(Exception):
    """Base exception for project domain."""
    pass

class ProjectNotFoundError(ProjectException):
    """Raised when project doesn't exist."""
    def __init__(self, project_id: str):
        super().__init__(f"Project not found: {project_id}")

class ProjectInactiveError(ProjectException):
    """Raised when trying to use inactive project."""
    def __init__(self, project_id: str):
        super().__init__(f"Project is inactive: {project_id}")

class QuotaExceededError(ProjectException):
    """Raised when user exceeds usage quota."""
    def __init__(self):
        super().__init__("Usage quota exceeded")
```

**Usage**:

```python
# In business logic
if not project.is_active:
    raise ProjectInactiveError(project.id)
```

---

## Application Layer - Complete Breakdown

**Location**: `app/application/`

**Purpose**: Orchestrates business logic and defines interfaces for external dependencies.

### Directory Structure

```
application/
├── dto/                # Data Transfer Objects
│   ├── project_dto.py  # Project DTOs
│   └── chat_dto.py     # Chat DTOs
├── ports/              # Interfaces for external dependencies
│   ├── input/          # Input ports (use case interfaces)
│   └── output/         # Output ports (repository, LLM interfaces)
├── use_cases/          # Application use cases
│   ├── create_project_use_case.py
│   ├── chat_use_case.py
│   └── index_project_use_case.py
└── agent/              # LangGraph AI agent
    ├── state.py        # Agent state definition
    ├── nodes.py        # Agent nodes (processing steps)
    └── graph.py        # Agent graph (workflow)
```

### File Explanations

#### `application/dto/project_dto.py`

**What it is**: DTOs for transferring project data between layers.

**Real-Life Example**:

```python
from pydantic import BaseModel

# DTO for creating a project (from API to application)
class CreateProjectDTO(BaseModel):
    """Data needed to create a project."""
    user_id: UUID
    name: str
    description: Optional[str] = None
    repository_url: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None

# DTO for updating a project
class UpdateProjectDTO(BaseModel):
    """Data for updating a project."""
    name: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None

# DTO for project response (from application to API)
class ProjectResponseDTO(BaseModel):
    """Project data to send to client."""
    id: UUID
    name: str
    description: Optional[str]
    language: Optional[str]
    created_at: datetime
    file_count: int
    
    class Config:
        from_attributes = True  # Can create from domain model
```

**Why DTOs?**

1. **Validation**: Pydantic validates data automatically
2. **Decoupling**: API can change without affecting domain
3. **Security**: Don't expose internal fields (password_hash, etc.)

**Usage**:

```python
# API receives request
request_data = {"name": "My Project", "language": "python"}

# Convert to DTO (validation happens here)
dto = CreateProjectDTO(
    user_id=current_user.id,
    **request_data
)

# Use case processes DTO
project = create_project_use_case.execute(dto)

# Convert domain model to response DTO
response = ProjectResponseDTO.from_orm(project)
return response
```

---

#### `application/ports/output/llm/llm_provider.py`

**What it is**: Interface defining what we need from an LLM provider.

**Real-Life Example**:

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """Port (interface) for LLM providers."""
    
    @abstractmethod
    async def generate(self, messages: List[Dict[str, str]]) -> str:
        """Generate text from messages."""
        pass
    
    @abstractmethod
    async def stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """Stream generated text."""
        pass
    
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding vector for text."""
        pass
```

**Why a Port?** The application layer says "I need something that can generate text" but doesn't care if it's OpenAI, Anthropic, or a local model.

---

#### `application/use_cases/create_project_use_case.py`

**What it is**: Use case for creating a new project.

**Real-Life Example**:

```python
class CreateProjectUseCase:
    """Use case: Create a new project."""
    
    def __init__(
        self,
        user_repository: UserRepository,
        project_repository: ProjectRepository,
    ):
        self.user_repo = user_repository
        self.project_repo = project_repository
    
    async def execute(self, dto: CreateProjectDTO) -> Project:
        """
        Execute the create project use case.
        
        Steps:
        1. Verify user exists and is active
        2. Check user quota
        3. Create project (domain logic)
        4. Save project (infrastructure)
        5. Return created project
        """
        # 1. Get user
        user = await self.user_repo.find_by_id(dto.user_id)
        if not user:
            raise UserNotFoundError(dto.user_id)
        
        # 2. Check business rules
        if not user.is_active:
            raise UserInactiveError()
        
        if not user.can_create_project():
            raise QuotaExceededError()
        
        # 3. Create project (domain logic)
        project = Project.create(
            user_id=user.id,
            name=dto.name,
            description=dto.description,
            language=dto.language,
            framework=dto.framework,
        )
        
        # 4. Save project
        saved_project = await self.project_repo.save(project)
        
        # 5. Consume user quota
        user.consume_quota(1)
        await self.user_repo.update(user)
        
        return saved_project
```

**Usage Flow**:

```
API Request → DTO → Use Case → Domain Logic → Repository → Database
                                     ↓
                              Business Rules Applied
```

---

#### `application/agent/state.py`

**What it is**: Defines the state structure for the LangGraph agent.

**Real-Life Example**:

```python
from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """
    State that flows through the agent graph.
    
    Think of this as a clipboard that gets passed between
    different processing steps, with each step adding information.
    """
    
    # Conversation
    messages: List[BaseMessage]          # Chat history
    user_query: str                      # Current question
    
    # Classification
    intent: Optional[str]                # What user wants (code gen, debug, etc.)
    
    # Context
    project_id: Optional[str]            # Which project
    retrieved_context: List[Dict]        # Relevant code from vector store
    search_results: Optional[Dict]       # Web search results
    
    # Generated outputs
    generated_code: Optional[str]        # Generated code
    explanation: Optional[str]           # AI response
    
    # Error handling
    error: Optional[str]                 # Error message if any
    
    # Metadata
    metadata: Dict[str, Any]             # Additional info
```

**Real-Life Analogy**: Like a form that gets filled out as it moves through different departments. Each department adds their information.

---

#### `application/agent/nodes.py`

**What it is**: Individual processing steps (nodes) in the agent workflow.

**Real-Life Example**:

```python
class AgentNodes:
    """Collection of agent processing nodes."""
    
    def __init__(self, llm_provider: LLMProvider, search_service: TavilySearchService):
        self.llm = llm_provider
        self.search = search_service
    
    async def classify_intent(self, state: AgentState) -> Dict:
        """
        Node 1: Classify what the user wants.
        
        Input: user_query
        Output: intent
        """
        user_query = state["user_query"]
        
        # Ask LLM to classify
        prompt = f"""Classify this request:
        - code_generation: Generate new code
        - code_explanation: Explain code
        - code_debug: Fix bugs
        - web_search: Current information needed
        - general_chat: Casual conversation
        
        Request: {user_query}
        
        Respond with only the category."""
        
        intent = await self.llm.generate([{"role": "user", "content": prompt}])
        
        return {"intent": intent.strip().lower()}
    
    async def web_search(self, state: AgentState) -> Dict:
        """
        Node 2: Search the web for current information.
        
        Input: user_query
        Output: search_results
        """
        query = state["user_query"]
        
        # Use Tavily to search
        results = await self.search.search(
            query=query,
            max_results=5,
            include_answer=True
        )
        
        return {"search_results": results}
    
    async def retrieve_context(self, state: AgentState) -> Dict:
        """
        Node 3: Get relevant code from vector store.
        
        Input: user_query, project_id
        Output: retrieved_context
        """
        # Search vector store for relevant code
        # (Implementation depends on vector store)
        context = []
        return {"retrieved_context": context}
    
    async def generate_response(self, state: AgentState) -> Dict:
        """
        Node 4: Generate final response using LLM.
        
        Input: user_query, intent, search_results, retrieved_context
        Output: explanation
        """
        query = state["user_query"]
        intent = state.get("intent")
        search_results = state.get("search_results")
        context = state.get("retrieved_context", [])
        
        # Build prompt based on intent
        if intent == "web_search":
            # Include search results
            search_context = self.search.format_results_for_context(search_results)
            prompt = f"Answer based on these search results:\n{search_context}\n\nQuestion: {query}"
        else:
            # Use code context
            code_context = "\n".join([c["content"] for c in context])
            prompt = f"Code context:\n{code_context}\n\nQuestion: {query}"
        
        # Generate response
        response = await self.llm.generate([
            {"role": "system", "content": "You are a helpful coding assistant."},
            {"role": "user", "content": prompt}
        ])
        
        return {"explanation": response}
```

---

#### `application/agent/graph.py`

**What it is**: Connects nodes into a workflow using LangGraph.

**Real-Life Example**:

```python
from langgraph.graph import StateGraph, END

def create_agent_graph(llm_provider, search_service):
    """
    Create the agent workflow graph.
    
    Workflow:
    1. Classify intent
    2. If web_search → search web
       If code-related → retrieve code
       Else → skip to response
    3. Generate response
    """
    
    # Initialize nodes
    nodes = AgentNodes(llm_provider, search_service)
    
    # Create graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("classify_intent", nodes.classify_intent)
    workflow.add_node("web_search", nodes.web_search)
    workflow.add_node("retrieve_context", nodes.retrieve_context)
    workflow.add_node("generate_response", nodes.generate_response)
    
    # Set entry point
    workflow.set_entry_point("classify_intent")
    
    # Add conditional routing
    def route_after_classification(state: AgentState) -> str:
        """Decide next step based on intent."""
        intent = state.get("intent")
        
        if intent == "web_search":
            return "web_search"
        elif intent in ["code_explanation", "code_debug"]:
            return "retrieve_context"
        else:
            return "generate_response"
    
    workflow.add_conditional_edges(
        "classify_intent",
        route_after_classification,
        {
            "web_search": "web_search",
            "retrieve_context": "retrieve_context",
            "generate_response": "generate_response",
        }
    )
    
    # After web search or context retrieval, generate response
    workflow.add_edge("web_search", "generate_response")
    workflow.add_edge("retrieve_context", "generate_response")
    
    # After response, end
    workflow.add_edge("generate_response", END)
    
    return workflow.compile()
```

**Visual Workflow**:

```
User Query
    ↓
[Classify Intent]
    ↓
    ├─ web_search? → [Web Search] ──┐
    ├─ code-related? → [Retrieve Context] ──┤
    └─ other? ──────────────────────────────┘
                                            ↓
                                  [Generate Response]
                                            ↓
                                      Return Answer
```

---

## Infrastructure Layer - Complete Breakdown

**Location**: `app/infrastructure/`

**Purpose**: Implements external service integrations (adapters for ports).

### Directory Structure

```
infrastructure/
├── persistence/        # Database implementations
│   ├── postgres/      # PostgreSQL repositories
│   ├── redis/         # Redis cache
│   └── models/        # SQLAlchemy models
├── llm/               # LLM provider implementations
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   └── provider_factory.py
├── external/          # External services
│   └── tavily_search.py
├── auth/              # Authentication
│   ├── jwt_handler.py
│   └── password_hasher.py
├── config/            # Configuration
│   ├── settings.py
│   └── logger.py
└── monitoring/        # Observability
    └── langsmith.py
```

### File Explanations

#### `infrastructure/persistence/postgres/user_repository.py`

**What it is**: PostgreSQL implementation of UserRepository.

**Real-Life Example**:

```python
from app.application.ports.output.repositories.user_repository import UserRepository
from app.domain.models.user import User

class PostgresUserRepository(UserRepository):
    """PostgreSQL implementation of user repository."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def find_by_id(self, user_id: UUID) -> Optional[User]:
        """Find user by ID."""
        # SQL query
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            return None
        
        # Convert database model to domain model
        return User(
            id=db_user.id,
            email=db_user.email,
            username=db_user.username,
            password_hash=db_user.password_hash,
            created_at=db_user.created_at,
            updated_at=db_user.updated_at,
            is_active=db_user.is_active,
        )
    
    async def find_by_email(self, email: str) -> Optional[User]:
        """Find user by email."""
        result = await self.session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        db_user = result.scalar_one_or_none()
        
        if not db_user:
            return None
        
        return self._to_domain(db_user)
    
    async def save(self, user: User) -> User:
        """Save user to database."""
        # Convert domain model to database model
        db_user = UserModel(
            id=user.id,
            email=user.email,
            username=user.username,
            password_hash=user.password_hash,
            created_at=user.created_at,
            updated_at=user.updated_at,
            is_active=user.is_active,
        )
        
        self.session.add(db_user)
        await self.session.commit()
        await self.session.refresh(db_user)
        
        return self._to_domain(db_user)
    
    def _to_domain(self, db_user: UserModel) -> User:
        """Convert database model to domain model."""
        return User(
            id=db_user.id,
            email=db_user.email,
            username=db_user.username,
            password_hash=db_user.password_hash,
            created_at=db_user.created_at,
            updated_at=db_user.updated_at,
            is_active=db_user.is_active,
        )
```

**Why separate?** The domain doesn't know about SQL. If we switch to MongoDB, we only change this file, not the domain logic.

---

#### `infrastructure/llm/openai_provider.py`

**What it is**: OpenAI implementation of LLMProvider port.

**Real-Life Example**:

```python
from app.application.ports.output.llm.llm_provider import LLMProvider
from openai import AsyncOpenAI

class OpenAIProvider(LLMProvider):
    """OpenAI implementation of LLM provider."""
    
    def __init__(self, api_key: str, model: str = "gpt-4-turbo-preview"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def generate(self, messages: List[Dict[str, str]]) -> str:
        """Generate text using OpenAI."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content
    
    async def stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """Stream generated text."""
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding vector."""
        response = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
```

---

#### `infrastructure/external/tavily_search.py`

**What it is**: Tavily web search service implementation.

**Real-Life Example**:

```python
from tavily import TavilyClient

class TavilySearchService:
    """Service for web search using Tavily API."""
    
    def __init__(self, api_key: str, max_results: int = 5):
        self.client = TavilyClient(api_key=api_key)
        self.max_results = max_results
    
    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        include_answer: bool = True,
    ) -> Dict[str, Any]:
        """
        Search the web for information.
        
        Args:
            query: Search query
            max_results: Max results to return
            include_answer: Include AI-generated answer
        
        Returns:
            {
                "query": str,
                "answer": str,
                "results": [
                    {"title": str, "url": str, "content": str, "score": float}
                ]
            }
        """
        response = self.client.search(
            query=query,
            max_results=max_results or self.max_results,
            include_answer=include_answer,
        )
        
        return response
    
    def format_results_for_context(self, search_response: Dict) -> str:
        """
        Format search results for LLM context.
        
        Converts JSON to readable text that LLM can understand.
        """
        formatted = []
        
        # Add quick answer
        if answer := search_response.get("answer"):
            formatted.append(f"**Quick Answer:** {answer}\n")
        
        # Add search results
        results = search_response.get("results", [])
        if results:
            formatted.append("**Web Search Results:**\n")
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "")
                
                formatted.append(f"{i}. **{title}**")
                formatted.append(f"   URL: {url}")
                formatted.append(f"   {content}\n")
        
        return "\n".join(formatted)
```

**Usage in Agent**:

```python
# In agent node
search_results = await tavily_service.search("What's new in Python 3.13?")
formatted = tavily_service.format_results_for_context(search_results)

# Pass to LLM
prompt = f"Answer based on these search results:\n{formatted}\n\nQuestion: {query}"
response = await llm.generate([{"role": "user", "content": prompt}])
```

---

#### `infrastructure/auth/jwt_handler.py`

**What it is**: JWT token creation and validation.

**Real-Life Example**:

```python
from jose import jwt
from datetime import datetime, timedelta

class JWTHandler:
    """Handler for JWT token operations."""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
    
    def create_access_token(
        self,
        user_id: str,
        expires_delta: timedelta = timedelta(minutes=30)
    ) -> str:
        """
        Create JWT access token.
        
        Token contains:
        - user_id: Who the user is
        - exp: When token expires
        - type: "access" (vs "refresh")
        """
        expire = datetime.utcnow() + expires_delta
        
        payload = {
            "sub": str(user_id),  # Subject (user ID)
            "exp": expire,         # Expiration time
            "type": "access",      # Token type
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token
    
    def create_refresh_token(
        self,
        user_id: str,
        expires_delta: timedelta = timedelta(days=7)
    ) -> str:
        """Create JWT refresh token (longer lived)."""
        expire = datetime.utcnow() + expires_delta
        
        payload = {
            "sub": str(user_id),
            "exp": expire,
            "type": "refresh",
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token
    
    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate JWT token.
        
        Raises:
            JWTError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError()
        except jwt.JWTError:
            raise InvalidTokenError()
    
    def get_user_id_from_token(self, token: str) -> str:
        """Extract user ID from token."""
        payload = self.decode_token(token)
        return payload["sub"]
```

**Usage**:

```python
# Login endpoint
jwt_handler = JWTHandler(secret_key="your-secret")

# Create tokens
access_token = jwt_handler.create_access_token(user.id)
refresh_token = jwt_handler.create_refresh_token(user.id)

# Return to client
return {
    "access_token": access_token,
    "refresh_token": refresh_token,
    "token_type": "bearer"
}

# Protected endpoint
token = request.headers["Authorization"].replace("Bearer ", "")
user_id = jwt_handler.get_user_id_from_token(token)
```

---

#### `infrastructure/config/settings.py`

**What it is**: Application configuration using Pydantic settings.

**Real-Life Example**:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "ByteBuddhi"
    app_env: str = "development"
    debug: bool = True
    
    # Database
    database_url: str
    database_pool_size: int = 20
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4-turbo-preview"
    
    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    
    # Tavily
    tavily_api_key: Optional[str] = None
    tavily_max_results: int = 5
    
    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: Optional[str] = None
    langchain_project: str = "bytebuddhi-dev"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()
```

**Usage**:

```python
from app.infrastructure.config.settings import settings

# Access configuration
database_url = settings.database_url
openai_key = settings.openai_api_key

# Different values in different environments
if settings.app_env == "production":
    # Production logic
    pass
else:
    # Development logic
    pass
```

---

## Interface Layer - Complete Breakdown

**Location**: `app/interfaces/`

**Purpose**: Exposes the application via HTTP API (FastAPI).

### Directory Structure

```
interfaces/
└── api/
    └── v1/
        ├── routes/
        │   ├── auth.py        # Authentication endpoints
        │   ├── projects.py    # Project endpoints
        │   ├── chat.py        # Chat endpoints
        │   └── health.py      # Health check endpoints
        ├── dependencies/
        │   ├── auth.py        # Auth dependencies
        │   └── database.py    # Database dependencies
        └── schemas/
            ├── auth_schemas.py     # Auth request/response models
            ├── project_schemas.py  # Project request/response models
            └── chat_schemas.py     # Chat request/response models
```

### File Explanations

#### `interfaces/api/v1/routes/auth.py`

**What it is**: Authentication API endpoints.

**Real-Life Example**:

```python
from fastapi import APIRouter, Depends, HTTPException
from app.interfaces.api.v1.schemas.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    AuthResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    request: RegisterRequest,
    user_repo: UserRepository = Depends(get_user_repository),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    Register a new user.
    
    Steps:
    1. Validate request data (automatic via Pydantic)
    2. Check if user exists
    3. Hash password
    4. Create user
    5. Generate JWT tokens
    6. Return response
    """
    # Check if user exists
    existing_user = await user_repo.find_by_email(request.email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")
    
    # Hash password
    password_hasher = PasswordHasher()
    password_hash = password_hasher.hash(request.password)
    
    # Create user (domain logic)
    user = User.create(
        email=request.email,
        username=request.username,
        password_hash=password_hash,
    )
    
    # Save user
    saved_user = await user_repo.save(user)
    
    # Generate tokens
    access_token = jwt_handler.create_access_token(saved_user.id)
    refresh_token = jwt_handler.create_refresh_token(saved_user.id)
    
    # Return response
    return AuthResponse(
        user_id=saved_user.id,
        email=saved_user.email,
        username=saved_user.username,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )

@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repository),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """Login user and return JWT tokens."""
    # Find user
    user = await user_repo.find_by_email(request.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    password_hasher = PasswordHasher()
    if not password_hasher.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if active
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    
    # Generate tokens
    access_token = jwt_handler.create_access_token(user.id)
    refresh_token = jwt_handler.create_refresh_token(user.id)
    
    return AuthResponse(
        user_id=user.id,
        email=user.email,
        username=user.username,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )
```

---

#### `interfaces/api/v1/routes/chat.py`

**What it is**: Chat/conversation API endpoints.

**Real-Life Example**:

```python
from fastapi import APIRouter, Depends
from app.application.agent.graph import ByteBuddhiAgent

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    agent: ByteBuddhiAgent = Depends(get_agent),
):
    """
    Send a message to the AI agent.
    
    Flow:
    1. Validate user has access to conversation
    2. Process message through agent
    3. Save message and response
    4. Return response
    """
    # Process through agent
    result = await agent.process_query(
        user_query=request.content,
        project_id=request.project_id,
        conversation_history=request.history,
    )
    
    # Return response
    return {
        "message_id": str(uuid4()),
        "content": result["explanation"],
        "intent": result.get("intent"),
        "metadata": {
            "has_code": result.get("generated_code") is not None,
            "has_search_results": result.get("search_results") is not None,
        }
    }
```

---

#### `interfaces/api/v1/schemas/auth_schemas.py`

**What it is**: Pydantic schemas for authentication API.

**Real-Life Example**:

```python
from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    """Request schema for user registration."""
    email: EmailStr  # Validates email format
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=100)

class LoginRequest(BaseModel):
    """Request schema for user login."""
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    """Response schema for authentication."""
    user_id: UUID
    email: str
    username: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
```

**Why separate schemas from DTOs?**

- **Schemas**: API-specific (HTTP layer)
- **DTOs**: Application-specific (use case layer)
- Allows API to change without affecting application logic

---

## Real-World Examples

### Example 1: User Asks "What's new in Python 3.13?"

**Complete Flow**:

```
1. HTTP Request (Interface Layer)
   POST /api/v1/chat/conversations/123/messages
   {
     "content": "What's new in Python 3.13?"
   }
   
2. Route Handler (interfaces/api/v1/routes/chat.py)
   - Validates request (Pydantic schema)
   - Authenticates user (JWT)
   - Calls agent
   
3. Agent Entry (application/agent/graph.py)
   - Initializes state with user query
   - Starts workflow
   
4. Classify Intent Node (application/agent/nodes.py)
   - Calls LLM to classify
   - LLM responds: "web_search"
   - Updates state: {"intent": "web_search"}
   
5. Conditional Routing (application/agent/graph.py)
   - Checks intent == "web_search"
   - Routes to web_search node
   
6. Web Search Node (application/agent/nodes.py)
   - Calls Tavily service (infrastructure/external/tavily_search.py)
   - Tavily searches the web
   - Returns: {
       "answer": "Python 3.13 introduces JIT compiler...",
       "results": [...]
     }
   - Updates state: {"search_results": {...}}
   
7. Generate Response Node (application/agent/nodes.py)
   - Formats search results for LLM
   - Calls LLM with search context
   - LLM generates comprehensive answer
   - Updates state: {"explanation": "Python 3.13 introduces..."}
   
8. Return Response (Interface Layer)
   - Converts state to API response
   - Returns JSON to client
```

**Code Path**:

```
interfaces/api/v1/routes/chat.py (HTTP)
    ↓
application/agent/graph.py (Agent orchestration)
    ↓
application/agent/nodes.py (Processing steps)
    ↓
infrastructure/llm/openai_provider.py (LLM calls)
infrastructure/external/tavily_search.py (Web search)
    ↓
application/agent/graph.py (Return result)
    ↓
interfaces/api/v1/routes/chat.py (HTTP response)
```

---

### Example 2: User Creates a Project

**Complete Flow**:

```
1. HTTP Request
   POST /api/v1/projects
   {
     "name": "My FastAPI App",
     "language": "python",
     "framework": "fastapi"
   }
   
2. Route Handler (interfaces/api/v1/routes/projects.py)
   - Validates request (CreateProjectRequest schema)
   - Authenticates user (get_current_user dependency)
   - Converts to DTO
   
3. Use Case (application/use_cases/create_project_use_case.py)
   - Gets user from repository
   - Checks business rules (is_active, quota)
   - Creates Project domain model
   - Saves via repository
   
4. Repository (infrastructure/persistence/postgres/project_repository.py)
   - Converts domain model to database model
   - Executes SQL INSERT
   - Returns saved project
   
5. Response
   - Converts domain model to response DTO
   - Returns to client
```

**Code Path**:

```
interfaces/api/v1/routes/projects.py
    ↓
application/use_cases/create_project_use_case.py
    ↓
domain/models/project.py (Business logic)
domain/models/user.py (Business rules)
    ↓
infrastructure/persistence/postgres/project_repository.py
    ↓
Database (PostgreSQL)
```

---

## Summary

ByteBuddhi's architecture provides:

- **Clean separation** between business logic and infrastructure
- **Flexible LLM integration** via provider pattern
- **Intelligent agent** using LangGraph for stateful workflows
- **Web search capability** for current information
- **Scalable design** that grows with your needs
- **Testable code** at every layer

### Key Takeaways

1. **Domain Layer**: Pure business logic, no dependencies
2. **Application Layer**: Orchestrates domain logic, defines interfaces
3. **Infrastructure Layer**: Implements external services
4. **Interface Layer**: Exposes API to users

5. **DTOs**: Transfer data between layers
6. **Entities**: Domain objects with behavior
7. **Value Objects**: Immutable objects defined by value
8. **Repositories**: Abstract data access
9. **Use Cases**: Application-specific business logic
10. **Ports/Adapters**: Decouple from external dependencies

This architecture ensures ByteBuddhi remains maintainable, testable, and adaptable as requirements evolve.
