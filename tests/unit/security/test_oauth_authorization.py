"""OAuth must not weaken project, artifact, or memory ownership."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.exceptions.project_exceptions import ProjectOwnershipException
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.project import Project
from app.domain.models.user import User
from app.infrastructure.auth.jwt_handler import JWTHandler


def test_oauth_user_jwt_feeds_execution_context() -> None:
    user = User.create(email="oauth-a@noreply.example", username="oauth-a", password_hash=None)
    handler = JWTHandler(secret_key="unit-test-secret-key-32-chars-min", algorithm="HS256")
    token = handler.create_access_token(user.id, additional_claims={"sub": "google-sub", "provider": "google"})
    resolved = handler.verify_token(token)
    assert resolved == user.id
    ctx = ExecutionContext(
        user_id=resolved,
        project_id=None,
        conversation_id=None,
        run_id="run_1",
        workspace_id=f"user_{resolved}",
    )
    assert ctx.user_id == user.id
    assert ctx.artifact_scope_id == f"user_{user.id}"


@pytest.mark.asyncio
async def test_oauth_user_cannot_access_another_users_project(tmp_path: Path) -> None:
    user_a = User.create(email="a@noreply.example", username="oa", password_hash=None)
    user_b = User.create(email="b@noreply.example", username="ob", password_hash=None)
    project_b = Project.create(user_id=user_b.id, name="b", local_path=str(tmp_path / "b"))
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=project_b)
    service = WorkspaceResolutionService(project_repo=repo, base_storage_dir=str(tmp_path / "ws"))
    with pytest.raises(ProjectOwnershipException):
        await service.resolve_workspace(user_id=user_a.id, project_id=uuid4())


def test_oauth_secrets_not_in_ci_or_compose() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "GOOGLE_CLIENT_SECRET: ${" in compose or "GOOGLE_CLIENT_SECRET:" in compose
    assert "sk_live" not in ci
    assert "client_secret: " not in ci.lower()
    assert "COPY .env" not in dockerfile
    assert "GOOGLE_CLIENT_SECRET=" not in Path("vscode-extension/src/extension.ts").read_text(encoding="utf-8")
    assert "GITHUB_CLIENT_SECRET" not in Path("vscode-extension/src/extension.ts").read_text(encoding="utf-8")
