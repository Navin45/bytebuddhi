"""CLI stdout/stderr rendering. No business logic."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from typing import Any, TextIO
from uuid import UUID

from app.application.agent.types import AgentStatus
from app.application.dto.project_dto import ProjectResponseDTO
from app.application.use_cases.agent.execute_task import ExecuteTaskResult

_ARTIFACT_RE = re.compile(r"artifact[_:][\w.-]+", re.IGNORECASE)
_HTML_RE = re.compile(r"<[^>]+>")


def _status_name(result: ExecuteTaskResult) -> str:
    return result.run_state.status.value if result.run_state.status else "unknown"


def envelope_from_result(result: ExecuteTaskResult) -> dict[str, Any]:
    errors: list[str] = []
    if result.run_state.error is not None:
        errors.append(result.run_state.error.message)
    artifacts = _artifact_refs(result.response)
    tool_names = sorted({tc.name for tc in result.run_state.tool_calls})
    return {
        "status": "success" if result.run_state.status == AgentStatus.COMPLETED else _status_name(result),
        "run_id": result.run_id,
        "conversation_id": str(result.conversation_id),
        "workspace_id": result.workspace_id,
        "answer": result.response,
        "artifacts": artifacts,
        "tools": tool_names,
        "errors": errors,
    }


def _artifact_refs(text: str) -> list[str]:
    if not text:
        return []
    found = sorted(set(_ARTIFACT_RE.findall(text)))
    return found


def write_json(payload: dict[str, Any], *, stream: TextIO = sys.stdout) -> None:
    stream.write(json.dumps(payload, sort_keys=True, default=str))
    stream.write("\n")


def write_human_result(result: ExecuteTaskResult, *, stream: TextIO = sys.stdout) -> None:
    lines = [
        f"Run: {result.run_id}",
        f"Conversation: {result.conversation_id}",
        f"Workspace: {result.workspace_id}",
        f"Status: {_status_name(result)}",
        "",
        "Answer:",
        result.response or "(empty)",
    ]
    artifacts = _artifact_refs(result.response)
    if artifacts:
        lines.extend(["", "Artifacts:"])
        lines.extend(f"  - {item}" for item in artifacts)
        lines.append("Output may be truncated. Artifact bodies are not printed.")
    tools = sorted({tc.name for tc in result.run_state.tool_calls})
    if tools:
        lines.extend(["", "Tools:"])
        lines.extend(f"  - {name}" for name in tools)
    web_previews = _web_research_previews(result)
    if web_previews:
        lines.extend(["", "Web research:"])
        lines.extend(web_previews)
    stream.write("\n".join(lines) + "\n")


def _web_research_previews(result: ExecuteTaskResult) -> list[str]:
    previews: list[str] = []
    for item in result.run_state.tool_results:
        if item.name != "web_research" or not item.content:
            continue
        text = _HTML_RE.sub(" ", item.content)
        text = " ".join(text.split())
        if not text:
            continue
        previews.append(text[:800])
        artifacts = _artifact_refs(item.content)
        previews.extend(f"  Artifact: {ref}" for ref in artifacts)
    return previews


def write_human_projects(projects: Sequence[ProjectResponseDTO], *, stream: TextIO = sys.stdout) -> None:
    if not projects:
        stream.write("No projects.\n")
        return
    for project in projects:
        stream.write(f"{project.id}  {project.name}  {project.local_path or '-'}\n")


def write_human_project(project: ProjectResponseDTO, *, stream: TextIO = sys.stdout) -> None:
    stream.write(
        "\n".join(
            [
                f"Id: {project.id}",
                f"Name: {project.name}",
                f"Owner: {project.user_id}",
                f"Path: {project.local_path or '-'}",
                f"Active: {project.is_active}",
            ]
        )
        + "\n"
    )


def write_error(message: str, *, stream: TextIO = sys.stderr) -> None:
    stream.write(f"error: {message}\n")


def write_progress(message: str, *, quiet: bool, json_mode: bool, stream: TextIO = sys.stderr) -> None:
    if quiet or json_mode:
        return
    stream.write(f"{message}\n")


def json_error_payload(message: str, *, exit_code: int) -> dict[str, Any]:
    return {
        "status": "error",
        "run_id": None,
        "conversation_id": None,
        "answer": None,
        "artifacts": [],
        "errors": [message],
        "exit_code": exit_code,
    }


def json_projects_payload(projects: Sequence[ProjectResponseDTO]) -> dict[str, Any]:
    return {
        "status": "success",
        "projects": [
            {
                "id": str(project.id),
                "name": project.name,
                "local_path": project.local_path,
                "is_active": project.is_active,
            }
            for project in projects
        ],
        "errors": [],
    }


def json_project_payload(project: ProjectResponseDTO) -> dict[str, Any]:
    return {
        "status": "success",
        "project": {
            "id": str(project.id),
            "name": project.name,
            "user_id": str(project.user_id),
            "local_path": project.local_path,
            "is_active": project.is_active,
        },
        "errors": [],
    }


def json_health_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status", "unknown"),
        "checks": payload,
        "errors": [] if payload.get("status") == "healthy" else [str(payload)],
    }


def conversation_id_str(value: UUID | str) -> str:
    return str(value)
