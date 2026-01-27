"""SQLAlchemy ORM models."""

from datetime import datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.infrastructure.persistence.postgres.database import Base


class UserModel(Base):
    """SQLAlchemy model for User."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, nullable=False, default=True)
    api_key = Column(String(255), unique=True, nullable=True, index=True)
    usage_quota = Column(Integer, nullable=False, default=1000)

    # Relationships
    projects = relationship("ProjectModel", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    conversations = relationship("ConversationModel", back_populates="user", cascade="all, delete-orphan", lazy="selectin")


class ProjectModel(Base):
    """SQLAlchemy model for Project."""

    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    repository_url = Column(String(500), nullable=True)
    local_path = Column(String(500), nullable=True)
    language = Column(String(50), nullable=True)
    framework = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_indexed_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    user = relationship("UserModel", back_populates="projects", lazy="selectin")
    files = relationship("FileModel", back_populates="project", cascade="all, delete-orphan", lazy="selectin")
    embeddings = relationship("EmbeddingModel", back_populates="project", cascade="all, delete-orphan", lazy="selectin")
    conversations = relationship("ConversationModel", back_populates="project", lazy="selectin")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_project_name"),
        Index("ix_projects_user_id", "user_id"),
    )


class FileModel(Base):
    """SQLAlchemy model for File."""

    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    last_modified = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    project = relationship("ProjectModel", back_populates="files", lazy="selectin")
    code_chunks = relationship("CodeChunkModel", back_populates="file", cascade="all, delete-orphan", lazy="selectin")

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_project_file_path"),
        Index("ix_files_project_id", "project_id"),
    )


class CodeChunkModel(Base):
    """SQLAlchemy model for Code Chunk."""

    __tablename__ = "code_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    extra_metadata = Column(JSON, nullable=True, default=dict)

    # Relationships
    file = relationship("FileModel", back_populates="code_chunks", lazy="selectin")
    embedding = relationship("EmbeddingModel", back_populates="code_chunk", uselist=False, cascade="all, delete-orphan", lazy="selectin")

    # Constraints
    __table_args__ = (
        Index("ix_code_chunks_file_id", "file_id"),
        Index("ix_code_chunks_project_id", "project_id"),
    )


class EmbeddingModel(Base):
    """SQLAlchemy model for Embedding."""

    __tablename__ = "code_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    code_chunk_id = Column(UUID(as_uuid=True), ForeignKey("code_chunks.id", ondelete="CASCADE"), nullable=False, unique=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    embedding = Column(Vector(1536), nullable=False)  # OpenAI embedding dimension
    model_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    extra_metadata = Column(JSON, nullable=True, default=dict)

    # Relationships
    code_chunk = relationship("CodeChunkModel", back_populates="embedding", lazy="selectin")
    project = relationship("ProjectModel", back_populates="embeddings", lazy="selectin")

    # Constraints
    __table_args__ = (
        Index("ix_embeddings_project_id", "project_id"),
        Index(
            "ix_embeddings_vector",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ConversationModel(Base):
    """SQLAlchemy model for Conversation."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_archived = Column(Boolean, nullable=False, default=False)
    extra_metadata = Column(JSON, nullable=True, default=dict)

    # Relationships
    user = relationship("UserModel", back_populates="conversations", lazy="selectin")
    project = relationship("ProjectModel", back_populates="conversations", lazy="selectin")
    messages = relationship("MessageModel", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin")

    # Constraints
    __table_args__ = (
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_project_id", "project_id"),
    )


class MessageModel(Base):
    """SQLAlchemy model for Message."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    extra_metadata = Column(JSON, nullable=True, default=dict)
    parent_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    feedback = Column(Integer, nullable=True)

    # Relationships
    conversation = relationship("ConversationModel", back_populates="messages", lazy="selectin")
    parent_message = relationship("MessageModel", remote_side=[id], backref="child_messages", lazy="selectin")

    # Constraints
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )
