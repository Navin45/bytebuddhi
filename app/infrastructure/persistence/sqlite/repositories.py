"""SQLite repositories for the standalone profile.

These implement the same application ports as the PostgreSQL repositories.
They are selected only at the composition boundary.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime
from uuid import UUID

from app.application.ports.output.repository.code_chunk_repository import CodeChunkRepository
from app.application.ports.output.repository.conversation_repository import ConversationRepository
from app.application.ports.output.repository.embedding_repository import EmbeddingRepository
from app.application.ports.output.repository.external_identity_repository import ExternalIdentityRepository
from app.application.ports.output.repository.file_repository import FileRepository
from app.application.ports.output.repository.message_repository import MessageRepository
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.application.ports.output.repository.user_repository import UserRepository
from app.domain.exceptions.auth_exceptions import DuplicateExternalIdentityError
from app.domain.models.code_chunk import CodeChunk
from app.domain.models.conversation import Conversation
from app.domain.models.embedding import Embedding
from app.domain.models.external_identity import ExternalIdentity
from app.domain.models.file import File
from app.domain.models.message import Message
from app.domain.models.project import Project
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import IdentityProvider
from app.infrastructure.persistence.sqlite.database import SqliteSession, transaction


class SqliteUserRepository(UserRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, user: User) -> User:
        return await asyncio.to_thread(self._create, user)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM users WHERE id = ?", (str(user_id),))

    async def get_by_email(self, email: str) -> User | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM users WHERE email = ?", (email,))

    async def get_by_username(self, username: str) -> User | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM users WHERE username = ?", (username,))

    async def update(self, user: User) -> User:
        return await asyncio.to_thread(self._update, user)

    async def delete(self, user_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, user_id)

    async def exists_by_email(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def exists_by_username(self, username: str) -> bool:
        return await self.get_by_username(username) is not None

    def _create(self, user: User) -> User:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, email, username, password_hash, created_at, updated_at, is_active, api_key, usage_quota
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _user_values(user),
            )
        return user

    def _update(self, user: User) -> User:
        with transaction(self.path) as connection:
            connection.execute(
                """
                UPDATE users
                SET email = ?, username = ?, password_hash = ?, updated_at = ?, is_active = ?, api_key = ?, usage_quota = ?
                WHERE id = ?
                """,
                (
                    user.email,
                    user.username,
                    user.password_hash,
                    _iso(user.updated_at),
                    int(user.is_active),
                    user.api_key,
                    user.usage_quota,
                    str(user.id),
                ),
            )
        return user

    def _delete(self, user_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM users WHERE id = ?", (str(user_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> User | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _user_from_row(row) if row is not None else None


class SqliteProjectRepository(ProjectRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, project: Project) -> Project:
        return await asyncio.to_thread(self._create, project)

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM projects WHERE id = ?", (str(project_id),))

    async def get_by_user_id(self, user_id: UUID) -> list[Project]:
        return await asyncio.to_thread(self._many, "SELECT * FROM projects WHERE user_id = ?", (str(user_id),))

    async def get_by_name(self, user_id: UUID, name: str) -> Project | None:
        return await asyncio.to_thread(
            self._one,
            "SELECT * FROM projects WHERE user_id = ? AND name = ?",
            (str(user_id), name),
        )

    async def update(self, project: Project) -> Project:
        return await asyncio.to_thread(self._update, project)

    async def delete(self, project_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, project_id)

    async def exists_by_name(self, user_id: UUID, name: str) -> bool:
        return await self.get_by_name(user_id, name) is not None

    def _create(self, project: Project) -> Project:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, user_id, name, description, repository_url, local_path, language, framework,
                    created_at, updated_at, last_indexed_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _project_values(project),
            )
        return project

    def _update(self, project: Project) -> Project:
        with transaction(self.path) as connection:
            connection.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, repository_url = ?, local_path = ?, language = ?, framework = ?,
                    updated_at = ?, last_indexed_at = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    project.name,
                    project.description,
                    project.repository_url,
                    project.local_path,
                    project.language,
                    project.framework,
                    _iso(project.updated_at),
                    _iso(project.last_indexed_at),
                    int(project.is_active),
                    str(project.id),
                ),
            )
        return project

    def _delete(self, project_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM projects WHERE id = ?", (str(project_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> Project | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _project_from_row(row) if row is not None else None

    def _many(self, sql: str, params: tuple[object, ...]) -> list[Project]:
        with transaction(self.path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_project_from_row(row) for row in rows]


class SqliteConversationRepository(ConversationRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, conversation: Conversation) -> Conversation:
        return await asyncio.to_thread(self._create, conversation)

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM conversations WHERE id = ?", (str(conversation_id),))

    async def get_by_user_id(self, user_id: UUID, include_archived: bool = False) -> list[Conversation]:
        sql = "SELECT * FROM conversations WHERE user_id = ?"
        params: tuple[object, ...] = (str(user_id),)
        if not include_archived:
            sql += " AND is_archived = 0"
        return await asyncio.to_thread(self._many, sql, params)

    async def update(self, conversation: Conversation) -> Conversation:
        return await asyncio.to_thread(self._update, conversation)

    async def delete(self, conversation_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, conversation_id)

    def _create(self, conversation: Conversation) -> Conversation:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO conversations (
                    id, user_id, project_id, title, created_at, updated_at, is_archived, extra_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _conversation_values(conversation),
            )
        return conversation

    def _update(self, conversation: Conversation) -> Conversation:
        with transaction(self.path) as connection:
            connection.execute(
                """
                UPDATE conversations
                SET project_id = ?, title = ?, updated_at = ?, is_archived = ?, extra_metadata = ?
                WHERE id = ?
                """,
                (
                    _uuid(conversation.project_id),
                    conversation.title,
                    _iso(conversation.updated_at),
                    int(conversation.is_archived),
                    json.dumps(conversation.metadata),
                    str(conversation.id),
                ),
            )
        return conversation

    def _delete(self, conversation_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (str(conversation_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> Conversation | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _conversation_from_row(row) if row is not None else None

    def _many(self, sql: str, params: tuple[object, ...]) -> list[Conversation]:
        with transaction(self.path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_conversation_from_row(row) for row in rows]


class SqliteMessageRepository(MessageRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, message: Message) -> Message:
        return await asyncio.to_thread(self._create, message)

    async def get_by_id(self, message_id: UUID) -> Message | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM messages WHERE id = ?", (str(message_id),))

    async def get_by_conversation_id(self, conversation_id: UUID, limit: int | None = None) -> list[Message]:
        sql = "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at"
        params: list[object] = [str(conversation_id)]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return await asyncio.to_thread(self._many, sql, tuple(params))

    async def update(self, message: Message) -> Message:
        return await asyncio.to_thread(self._update, message)

    async def delete(self, message_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, message_id)

    def _create(self, message: Message) -> Message:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, created_at, extra_metadata, parent_message_id, feedback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _message_values(message),
            )
        return message

    def _update(self, message: Message) -> Message:
        with transaction(self.path) as connection:
            connection.execute(
                """
                UPDATE messages
                SET role = ?, content = ?, extra_metadata = ?, parent_message_id = ?, feedback = ?
                WHERE id = ?
                """,
                (
                    message.role,
                    message.content,
                    json.dumps(message.metadata),
                    _uuid(message.parent_message_id),
                    message.feedback,
                    str(message.id),
                ),
            )
        return message

    def _delete(self, message_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM messages WHERE id = ?", (str(message_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> Message | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _message_from_row(row) if row is not None else None

    def _many(self, sql: str, params: tuple[object, ...]) -> list[Message]:
        with transaction(self.path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_message_from_row(row) for row in rows]


class SqliteExternalIdentityRepository(ExternalIdentityRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def get_by_provider_subject(
        self, provider: IdentityProvider, provider_subject: str
    ) -> ExternalIdentity | None:
        return await asyncio.to_thread(self._get, provider, provider_subject)

    async def list_by_user_id(self, user_id: UUID) -> list[ExternalIdentity]:
        return await asyncio.to_thread(self._list, user_id)

    async def create_with_user(self, user: User, identity: ExternalIdentity) -> ExternalIdentity:
        return await asyncio.to_thread(self._create_with_user, user, identity)

    async def create(self, identity: ExternalIdentity) -> ExternalIdentity:
        return await asyncio.to_thread(self._create, identity)

    async def delete(self, user_id: UUID, provider: IdentityProvider) -> bool:
        return await asyncio.to_thread(self._delete, user_id, provider)

    def _get(self, provider: IdentityProvider, provider_subject: str) -> ExternalIdentity | None:
        with transaction(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM external_identities WHERE provider = ? AND provider_subject = ?",
                (provider.value, provider_subject),
            ).fetchone()
        return _identity_from_row(row) if row is not None else None

    def _list(self, user_id: UUID) -> list[ExternalIdentity]:
        with transaction(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM external_identities WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
        return [_identity_from_row(row) for row in rows]

    def _create_with_user(self, user: User, identity: ExternalIdentity) -> ExternalIdentity:
        try:
            with transaction(self.path) as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        id, email, username, password_hash, created_at, updated_at, is_active, api_key, usage_quota
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _user_values(user),
                )
                _insert_identity(connection, identity)
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DuplicateExternalIdentityError() from exc
            raise
        return identity

    def _create(self, identity: ExternalIdentity) -> ExternalIdentity:
        try:
            with transaction(self.path) as connection:
                _insert_identity(connection, identity)
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DuplicateExternalIdentityError() from exc
            raise
        return identity

    def _delete(self, user_id: UUID, provider: IdentityProvider) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute(
                "DELETE FROM external_identities WHERE user_id = ? AND provider = ?",
                (str(user_id), provider.value),
            )
            return cursor.rowcount > 0


class SqliteFileRepository(FileRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, file: File) -> File:
        return await asyncio.to_thread(self._create, file)

    async def get_by_id(self, file_id: UUID) -> File | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM files WHERE id = ?", (str(file_id),))

    async def get_by_project_id(self, project_id: UUID, include_deleted: bool = False) -> list[File]:
        sql = "SELECT * FROM files WHERE project_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        return await asyncio.to_thread(self._many, sql, (str(project_id),))

    async def get_by_path(self, project_id: UUID, file_path: str) -> File | None:
        return await asyncio.to_thread(
            self._one,
            "SELECT * FROM files WHERE project_id = ? AND file_path = ?",
            (str(project_id), file_path),
        )

    async def update(self, file: File) -> File:
        return await asyncio.to_thread(self._update, file)

    async def delete(self, file_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, file_id)

    async def exists_by_path(self, project_id: UUID, file_path: str) -> bool:
        return await self.get_by_path(project_id, file_path) is not None

    def _create(self, file: File) -> File:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO files (
                    id, project_id, file_path, file_name, file_type, size_bytes, content_hash,
                    last_modified, created_at, is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(file.id),
                    str(file.project_id),
                    file.file_path,
                    file.file_name,
                    file.file_type,
                    file.size_bytes,
                    file.content_hash,
                    _iso(file.last_modified),
                    _iso(file.created_at),
                    int(file.is_deleted),
                ),
            )
        return file

    def _update(self, file: File) -> File:
        with transaction(self.path) as connection:
            connection.execute(
                """
                UPDATE files
                SET file_path = ?, file_name = ?, file_type = ?, size_bytes = ?, content_hash = ?,
                    last_modified = ?, is_deleted = ?
                WHERE id = ?
                """,
                (
                    file.file_path,
                    file.file_name,
                    file.file_type,
                    file.size_bytes,
                    file.content_hash,
                    _iso(file.last_modified),
                    int(file.is_deleted),
                    str(file.id),
                ),
            )
        return file

    def _delete(self, file_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM files WHERE id = ?", (str(file_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> File | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _file_from_row(row) if row is not None else None

    def _many(self, sql: str, params: tuple[object, ...]) -> list[File]:
        with transaction(self.path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_file_from_row(row) for row in rows]


class SqliteCodeChunkRepository(CodeChunkRepository):
    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, code_chunk: CodeChunk) -> CodeChunk:
        return await asyncio.to_thread(self._create, code_chunk)

    async def get_by_id(self, chunk_id: UUID) -> CodeChunk | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM code_chunks WHERE id = ?", (str(chunk_id),))

    async def get_by_file_id(self, file_id: UUID) -> list[CodeChunk]:
        return await asyncio.to_thread(self._many, "SELECT * FROM code_chunks WHERE file_id = ?", (str(file_id),))

    async def get_by_project_id(self, project_id: UUID) -> list[CodeChunk]:
        return await asyncio.to_thread(self._many, "SELECT * FROM code_chunks WHERE project_id = ?", (str(project_id),))

    async def delete_by_file_id(self, file_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, file_id)

    def _create(self, chunk: CodeChunk) -> CodeChunk:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO code_chunks (
                    id, file_id, project_id, chunk_text, chunk_index, start_line, end_line,
                    created_at, updated_at, extra_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(chunk.id),
                    str(chunk.file_id),
                    str(chunk.project_id),
                    chunk.chunk_text,
                    chunk.chunk_index,
                    chunk.start_line,
                    chunk.end_line,
                    _iso(chunk.created_at),
                    _iso(chunk.updated_at),
                    json.dumps(chunk.metadata),
                ),
            )
        return chunk

    def _delete(self, file_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM code_chunks WHERE file_id = ?", (str(file_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> CodeChunk | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _chunk_from_row(row) if row is not None else None

    def _many(self, sql: str, params: tuple[object, ...]) -> list[CodeChunk]:
        with transaction(self.path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_chunk_from_row(row) for row in rows]


class SqliteEmbeddingRepository(EmbeddingRepository):
    """Local embedding store. Similarity is computed in process, not with pgvector."""

    def __init__(self, session: SqliteSession) -> None:
        self.path = session.path

    async def create(self, embedding: Embedding) -> Embedding:
        return await asyncio.to_thread(self._create, embedding)

    async def get_by_id(self, embedding_id: UUID) -> Embedding | None:
        return await asyncio.to_thread(self._one, "SELECT * FROM code_embeddings WHERE id = ?", (str(embedding_id),))

    async def get_by_code_chunk_id(self, code_chunk_id: UUID) -> Embedding | None:
        return await asyncio.to_thread(
            self._one,
            "SELECT * FROM code_embeddings WHERE code_chunk_id = ?",
            (str(code_chunk_id),),
        )

    async def search_similar(
        self, project_id: UUID, query_vector: list[float], limit: int = 10
    ) -> list[tuple[Embedding, float]]:
        if not query_vector:
            raise ValueError("query embedding is required")
        return await asyncio.to_thread(self._search, project_id, query_vector, limit)

    async def delete_by_project_id(self, project_id: UUID) -> bool:
        return await asyncio.to_thread(self._delete, project_id)

    def _create(self, embedding: Embedding) -> Embedding:
        with transaction(self.path) as connection:
            connection.execute(
                """
                INSERT INTO code_embeddings (id, code_chunk_id, project_id, embedding, model_name, created_at, extra_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(embedding.id),
                    str(embedding.code_chunk_id),
                    str(embedding.project_id),
                    json.dumps(embedding.embedding_vector),
                    embedding.model_name,
                    _iso(embedding.created_at),
                    json.dumps(embedding.metadata),
                ),
            )
        return embedding

    def _search(self, project_id: UUID, query: list[float], limit: int) -> list[tuple[Embedding, float]]:
        with transaction(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM code_embeddings WHERE project_id = ?",
                (str(project_id),),
            ).fetchall()
        scored = [(_embedding_from_row(row), _cosine(query, json.loads(row["embedding"]))) for row in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _delete(self, project_id: UUID) -> bool:
        with transaction(self.path) as connection:
            cursor = connection.execute("DELETE FROM code_embeddings WHERE project_id = ?", (str(project_id),))
            return cursor.rowcount > 0

    def _one(self, sql: str, params: tuple[object, ...]) -> Embedding | None:
        with transaction(self.path) as connection:
            row = connection.execute(sql, params).fetchone()
        return _embedding_from_row(row) if row is not None else None


def _insert_identity(connection, identity: ExternalIdentity) -> None:
    connection.execute(
        """
        INSERT INTO external_identities (
            id, user_id, provider, provider_subject, email_snapshot, display_name_snapshot,
            avatar_url_snapshot, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(identity.id),
            str(identity.user_id),
            identity.provider.value,
            identity.provider_subject,
            identity.email_snapshot,
            identity.display_name_snapshot,
            identity.avatar_url_snapshot,
            _iso(identity.created_at),
            _iso(identity.updated_at),
        ),
    )


def _user_values(user: User) -> tuple[object, ...]:
    return (
        str(user.id),
        user.email,
        user.username,
        user.password_hash,
        _iso(user.created_at),
        _iso(user.updated_at),
        int(user.is_active),
        user.api_key,
        user.usage_quota,
    )


def _project_values(project: Project) -> tuple[object, ...]:
    return (
        str(project.id),
        str(project.user_id),
        project.name,
        project.description,
        project.repository_url,
        project.local_path,
        project.language,
        project.framework,
        _iso(project.created_at),
        _iso(project.updated_at),
        _iso(project.last_indexed_at),
        int(project.is_active),
    )


def _conversation_values(conversation: Conversation) -> tuple[object, ...]:
    return (
        str(conversation.id),
        str(conversation.user_id),
        _uuid(conversation.project_id),
        conversation.title,
        _iso(conversation.created_at),
        _iso(conversation.updated_at),
        int(conversation.is_archived),
        json.dumps(conversation.metadata),
    )


def _message_values(message: Message) -> tuple[object, ...]:
    return (
        str(message.id),
        str(message.conversation_id),
        message.role,
        message.content,
        _iso(message.created_at),
        json.dumps(message.metadata),
        _uuid(message.parent_message_id),
        message.feedback,
    )


def _user_from_row(row) -> User:
    return User(
        id=UUID(row["id"]),
        email=row["email"],
        username=row["username"],
        password_hash=row["password_hash"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        is_active=bool(row["is_active"]),
        api_key=row["api_key"],
        usage_quota=row["usage_quota"],
    )


def _project_from_row(row) -> Project:
    return Project(
        id=UUID(row["id"]),
        user_id=UUID(row["user_id"]),
        name=row["name"],
        description=row["description"],
        repository_url=row["repository_url"],
        local_path=row["local_path"],
        language=row["language"],
        framework=row["framework"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        last_indexed_at=_dt(row["last_indexed_at"]) if row["last_indexed_at"] else None,
        is_active=bool(row["is_active"]),
    )


def _conversation_from_row(row) -> Conversation:
    return Conversation(
        id=UUID(row["id"]),
        user_id=UUID(row["user_id"]),
        project_id=UUID(row["project_id"]) if row["project_id"] else None,
        title=row["title"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        is_archived=bool(row["is_archived"]),
        metadata=json.loads(row["extra_metadata"] or "{}"),
    )


def _message_from_row(row) -> Message:
    return Message(
        id=UUID(row["id"]),
        conversation_id=UUID(row["conversation_id"]),
        role=row["role"],
        content=row["content"],
        created_at=_dt(row["created_at"]),
        metadata=json.loads(row["extra_metadata"] or "{}"),
        parent_message_id=UUID(row["parent_message_id"]) if row["parent_message_id"] else None,
        feedback=row["feedback"],
    )


def _identity_from_row(row) -> ExternalIdentity:
    return ExternalIdentity(
        id=UUID(row["id"]),
        user_id=UUID(row["user_id"]),
        provider=IdentityProvider(row["provider"]),
        provider_subject=row["provider_subject"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        email_snapshot=row["email_snapshot"],
        display_name_snapshot=row["display_name_snapshot"],
        avatar_url_snapshot=row["avatar_url_snapshot"],
    )


def _file_from_row(row) -> File:
    return File(
        id=UUID(row["id"]),
        project_id=UUID(row["project_id"]),
        file_path=row["file_path"],
        file_name=row["file_name"],
        file_type=row["file_type"],
        size_bytes=row["size_bytes"],
        content_hash=row["content_hash"],
        last_modified=_dt(row["last_modified"]),
        created_at=_dt(row["created_at"]),
        is_deleted=bool(row["is_deleted"]),
    )


def _chunk_from_row(row) -> CodeChunk:
    return CodeChunk(
        id=UUID(row["id"]),
        file_id=UUID(row["file_id"]),
        project_id=UUID(row["project_id"]),
        chunk_text=row["chunk_text"],
        chunk_index=row["chunk_index"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        metadata=json.loads(row["extra_metadata"] or "{}"),
    )


def _embedding_from_row(row) -> Embedding:
    return Embedding(
        id=UUID(row["id"]),
        code_chunk_id=UUID(row["code_chunk_id"]),
        project_id=UUID(row["project_id"]),
        embedding_vector=json.loads(row["embedding"]),
        model_name=row["model_name"],
        created_at=_dt(row["created_at"]),
        metadata=json.loads(row["extra_metadata"] or "{}"),
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return numerator / (left_norm * right_norm)


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)
