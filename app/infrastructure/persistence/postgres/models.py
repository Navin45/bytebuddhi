"""SQLAlchemy ORM models using SQLAlchemy 2.0 Mapped type annotations."""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.postgres.database import Base


class UserModel(Base):
    """SQLAlchemy model for User."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)
    api_key: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    usage_quota: Mapped[int] = mapped_column(default=1000)

    # Relationships
    projects: Mapped[list["ProjectModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    conversations: Mapped[list["ConversationModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    external_identities: Mapped[list["ExternalIdentityModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class ExternalIdentityModel(Base):
    """SQLAlchemy model for linked external login identities."""

    __tablename__ = "external_identities"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    provider_subject: Mapped[str] = mapped_column(String(255))
    email_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["UserModel"] = relationship(back_populates="external_identities", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_external_identity_provider_subject"),
        Index("ix_external_identities_user_id", "user_id"),
    )


class ProjectModel(Base):
    """SQLAlchemy model for Project."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="projects", lazy="selectin")
    files: Mapped[list["FileModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    embeddings: Mapped[list["EmbeddingModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    conversations: Mapped[list["ConversationModel"]] = relationship(back_populates="project", lazy="selectin")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_project_name"),
        Index("ix_projects_user_id", "user_id"),
    )


class FileModel(Base):
    """SQLAlchemy model for File."""

    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(1000))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))
    last_modified: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_deleted: Mapped[bool] = mapped_column(default=False)

    # Relationships
    project: Mapped["ProjectModel"] = relationship(back_populates="files", lazy="selectin")
    code_chunks: Mapped[list["CodeChunkModel"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", lazy="selectin"
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_project_file_path"),
        Index("ix_files_project_id", "project_id"),
    )


class CodeChunkModel(Base):
    """SQLAlchemy model for Code Chunk."""

    __tablename__ = "code_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chunk_text: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column()
    start_line: Mapped[int] = mapped_column()
    end_line: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # Relationships
    file: Mapped["FileModel"] = relationship(back_populates="code_chunks", lazy="selectin")
    embedding: Mapped["EmbeddingModel | None"] = relationship(
        back_populates="code_chunk", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    # Constraints
    __table_args__ = (
        Index("ix_code_chunks_file_id", "file_id"),
        Index("ix_code_chunks_project_id", "project_id"),
    )


class EmbeddingModel(Base):
    """SQLAlchemy model for Embedding."""

    __tablename__ = "code_embeddings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code_chunk_id: Mapped[UUID] = mapped_column(ForeignKey("code_chunks.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    embedding = mapped_column(Vector(1536), nullable=False)  # OpenAI embedding dimension
    model_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # Relationships
    code_chunk: Mapped["CodeChunkModel"] = relationship(back_populates="embedding", lazy="selectin")
    project: Mapped["ProjectModel"] = relationship(back_populates="embeddings", lazy="selectin")

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

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_archived: Mapped[bool] = mapped_column(default=False)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)

    # Relationships
    user: Mapped["UserModel"] = relationship(back_populates="conversations", lazy="selectin")
    project: Mapped["ProjectModel | None"] = relationship(back_populates="conversations", lazy="selectin")
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )

    # Constraints
    __table_args__ = (
        Index("ix_conversations_user_id", "user_id"),
        Index("ix_conversations_project_id", "project_id"),
    )


class MessageModel(Base):
    """SQLAlchemy model for Message."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    parent_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    feedback: Mapped[int | None] = mapped_column(nullable=True)

    # Relationships
    conversation: Mapped["ConversationModel"] = relationship(back_populates="messages", lazy="selectin")
    parent_message: Mapped["MessageModel | None"] = relationship(
        remote_side=[id], backref="child_messages", lazy="selectin"
    )

    # Constraints
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class MemoryItemModel(Base):
    """SQLAlchemy model for durable and project memory items."""

    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scope: Mapped[str] = mapped_column(String(50), index=True)
    scope_id: Mapped[str] = mapped_column(String(100), index=True)
    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    embedding = mapped_column(Vector(1536), nullable=True)

    __table_args__ = (
        Index("ix_memory_items_scope_scope_id", "scope", "scope_id"),
        Index("ix_memory_items_type", "memory_type"),
        Index("ix_memory_items_importance", "importance"),
        Index("ix_memory_items_expires_at", "expires_at"),
        Index(
            "ix_memory_items_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
