"""CLI application adapter over application use cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TextIO
from uuid import UUID

from app.application.agent.types import AgentStatus
from app.application.ports.output.llm.model_catalog import ModelCatalog
from app.application.ports.output.repository.user_repository import UserRepository
from app.application.runtime.cancellation import CancellationToken
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskUseCase
from app.application.use_cases.project.get_project import GetProjectUseCase
from app.application.use_cases.project.list_projects import ListProjectsUseCase
from app.application.use_cases.project.resolve_project_by_local_path import ResolveProjectByLocalPathUseCase
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.render import (
    envelope_from_result,
    json_health_payload,
    json_models_payload,
    json_project_payload,
    json_projects_payload,
    write_human_models,
    write_human_project,
    write_human_projects,
    write_human_result,
    write_json,
    write_progress,
)


class CliApp:
    """Thin CLI adapter. All execution goes through application use cases."""

    def __init__(
        self,
        *,
        execute_task: ExecuteTaskUseCase | None,
        list_projects: ListProjectsUseCase,
        get_project: GetProjectUseCase,
        resolve_local_project: ResolveProjectByLocalPathUseCase,
        user_repository: UserRepository,
        health_check: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        model_catalog: ModelCatalog | None = None,
        stdout: TextIO,
        stderr: TextIO,
    ) -> None:
        self.execute_task = execute_task
        self.list_projects = list_projects
        self.get_project = get_project
        self.resolve_local_project = resolve_local_project
        self.user_repository = user_repository
        self.health_check = health_check
        self.model_catalog = model_catalog
        self.stdout = stdout
        self.stderr = stderr
        self.last_conversation_id: UUID | str | None = None
        self.cancellation_token: CancellationToken | None = None

    async def authenticate(self, user_id: UUID) -> UUID:
        user = await self.user_repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise CliError("User not found or inactive", ExitCode.AUTH_FAILURE)
        return user.id

    async def resolve_project_id(
        self,
        *,
        user_id: UUID,
        project_id: UUID | None,
        cwd: str | None,
    ) -> UUID | None:
        if project_id is not None and cwd:
            raise CliError("Use either --project or --cwd, not both", ExitCode.USAGE_ERROR)
        if cwd:
            return await self.resolve_local_project.execute(user_id, cwd)
        return project_id

    async def run_task(
        self,
        *,
        prompt: str,
        user_id: UUID,
        project_id: UUID | None,
        conversation_id: UUID | None,
        json_mode: bool,
        quiet: bool,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> int:
        if self.execute_task is None:
            raise CliError("Task execution is not available for this command", ExitCode.CONFIG_FAILURE)
        write_progress("Running task...", quiet=quiet, json_mode=json_mode, stream=self.stderr)
        self.cancellation_token = CancellationToken()
        try:
            result = await self.execute_task.execute(
                ExecuteTaskCommand(
                    prompt=prompt,
                    user_id=user_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    cancellation_token=self.cancellation_token,
                    model_provider=model_provider,
                    model_name=model_name,
                )
            )
        finally:
            self.cancellation_token = None
        self.last_conversation_id = result.conversation_id
        if json_mode:
            write_json(envelope_from_result(result), stream=self.stdout)
        else:
            write_human_result(result, stream=self.stdout)
        if result.run_state.status == AgentStatus.CANCELLED:
            return int(ExitCode.TIMEOUT_CANCELLED)
        if result.run_state.status != AgentStatus.COMPLETED:
            return int(ExitCode.EXECUTION_FAILURE)
        return int(ExitCode.SUCCESS)

    async def list_user_projects(self, *, user_id: UUID, json_mode: bool) -> int:
        projects = await self.list_projects.execute(user_id)
        if json_mode:
            write_json(json_projects_payload(projects), stream=self.stdout)
        else:
            write_human_projects(projects, stream=self.stdout)
        return int(ExitCode.SUCCESS)

    async def show_project(self, *, user_id: UUID, project_id: UUID, json_mode: bool) -> int:
        project = await self.get_project.execute(user_id, project_id)
        if json_mode:
            write_json(json_project_payload(project), stream=self.stdout)
        else:
            write_human_project(project, stream=self.stdout)
        return int(ExitCode.SUCCESS)

    async def health(self, *, json_mode: bool) -> int:
        if self.health_check is None:
            payload: dict[str, Any] = {"status": "healthy", "service": "bytebuddhi-cli"}
        else:
            payload = await self.health_check()
        if json_mode:
            write_json(json_health_payload(payload), stream=self.stdout)
        else:
            self.stdout.write(f"status: {payload.get('status', 'unknown')}\n")
            for key, value in payload.items():
                if key == "status":
                    continue
                self.stdout.write(f"{key}: {value}\n")
        return int(ExitCode.SUCCESS if payload.get("status") == "healthy" else ExitCode.EXECUTION_FAILURE)

    async def list_models(self, *, json_mode: bool) -> int:
        if self.model_catalog is None:
            raise CliError("Model catalog is not available", ExitCode.CONFIG_FAILURE)
        default = self.model_catalog.default_ref()
        models = [
            {
                "provider": item.provider,
                "model": item.model,
                "display_name": item.display_name,
                "available": item.available,
                "capabilities": [cap.value for cap in item.capabilities],
            }
            for item in self.model_catalog.list_models()
        ]
        if json_mode:
            write_json(
                json_models_payload(
                    default_provider=default.provider,
                    default_model=default.model,
                    models=models,
                ),
                stream=self.stdout,
            )
        else:
            write_human_models(
                default_provider=default.provider,
                default_model=default.model,
                models=models,
                stream=self.stdout,
            )
        return int(ExitCode.SUCCESS)
