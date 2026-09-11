"""GitHub reference connector implementing BaseConnector."""

from collections.abc import Callable
from typing import Any

from app.application.ports.output.connectors.connector import BaseConnector
from app.application.ports.output.connectors.credential_provider import CredentialProvider
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import CapabilityType, RiskLevel, ToolDefinition
from app.application.tools.registry import ToolRegistry
from app.domain.exceptions.connector_exceptions import (
    ConnectorAuthenticationError,
    ConnectorError,
)
from app.infrastructure.config.logger import get_logger
from app.infrastructure.http.external_client import ExternalHttpClient

logger = get_logger(__name__)


class GitHubConnector(BaseConnector):
    """Reference external connector providing safe, bounded GitHub capabilities."""

    connector_id: str = "github"
    name: str = "GitHub"

    def __init__(
        self,
        credential_provider: CredentialProvider,
        http_client: ExternalHttpClient | None = None,
        base_url: str = "https://api.github.com",
        client: ExternalHttpClient | None = None,
    ) -> None:
        self.credential_provider = credential_provider
        self.http_client = client or http_client or ExternalHttpClient()
        self.base_url = base_url.rstrip("/")

    async def connect(self) -> None:
        """Verify connector health."""
        pass

    async def disconnect(self) -> None:
        """Clean up resources."""
        pass

    def get_capabilities(self) -> list[ToolDefinition]:
        """Return the 7 standard GitHub tool definitions."""
        return [
            ToolDefinition(
                name="github_search_repositories",
                description="Search GitHub repositories by keyword query.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword or query string"},
                        "limit": {"type": "integer", "description": "Max repositories to return (default 10, max 30)"},
                    },
                    "required": ["query"],
                },
                id="github.search_repositories",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            ToolDefinition(
                name="github_get_repository",
                description="Get metadata for a GitHub repository.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner or organization"},
                        "repo": {"type": "string", "description": "Repository name"},
                    },
                    "required": ["owner", "repo"],
                },
                id="github.get_repository",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            ToolDefinition(
                name="github_list_issues",
                description="List issues for a repository.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "Issue state (default 'open')",
                        },
                        "limit": {"type": "integer", "description": "Max issues to return (default 10, max 30)"},
                    },
                    "required": ["owner", "repo"],
                },
                id="github.list_issues",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            ToolDefinition(
                name="github_get_issue",
                description="Get details of a specific issue by number.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "issue_number": {"type": "integer", "description": "Issue number"},
                    },
                    "required": ["owner", "repo", "issue_number"],
                },
                id="github.get_issue",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            ToolDefinition(
                name="github_create_issue",
                description="Create a new issue on GitHub. Mutating operation requiring explicit approval.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "title": {"type": "string", "description": "Issue title"},
                        "body": {"type": "string", "description": "Issue description body"},
                    },
                    "required": ["owner", "repo", "title"],
                },
                id="github.create_issue",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            ),
            ToolDefinition(
                name="github_list_pull_requests",
                description="List pull requests for a repository.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "PR state (default 'open')",
                        },
                        "limit": {"type": "integer", "description": "Max PRs to return (default 10, max 30)"},
                    },
                    "required": ["owner", "repo"],
                },
                id="github.list_pull_requests",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            ToolDefinition(
                name="github_get_pull_request",
                description="Get details for a specific GitHub pull request.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "pull_number": {"type": "integer", "description": "Pull request number"},
                    },
                    "required": ["owner", "repo", "pull_number"],
                },
                id="github.get_pull_request",
                capability_type=CapabilityType.CONNECTOR,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
        ]

    def _create_handler(self, cap_name: str) -> Callable[..., Any]:
        async def handler(context: ToolExecutionContext | None = None, **kwargs: Any) -> Any:
            return await self.invoke(cap_name, kwargs, context)

        return handler

    def get_tool_tuples(self) -> list[tuple[ToolDefinition, Callable[..., Any]]]:
        """Return list of (ToolDefinition, handler) tuples for registry inclusion."""
        return [(defn, self._create_handler(defn.name)) for defn in self.get_capabilities()]

    def register_capabilities(self, registry: ToolRegistry) -> None:
        """Register all 7 capabilities with bound execution handlers into the registry."""
        for defn, handler in self.get_tool_tuples():
            registry.register(defn, handler)

    async def _get_auth_headers(self, context: ToolExecutionContext | None = None) -> dict[str, str]:
        """Resolve GitHub bearer token securely from caller context without exposing secrets."""
        project_id = context.metadata.get("project_id") if context and context.metadata else None
        user_id = context.user_id if context else None

        credential = await self.credential_provider.get_credential(
            provider="github",
            user_id=user_id,
            project_id=project_id,
        )

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if not credential or not credential.secret:
            raise ConnectorAuthenticationError("No GitHub token found for caller scope")

        headers["Authorization"] = f"Bearer {credential.secret}"
        return headers

    async def search_repositories(
        self,
        query: str,
        limit: int = 10,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Search GitHub repositories."""
        headers = await self._get_auth_headers(context)
        clamped_limit = max(1, min(limit, 30))
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/search/repositories",
            provider="github",
            headers=headers,
            params={"q": query, "per_page": clamped_limit},
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        return {
            "total_count": data.get("total_count", len(items)) if isinstance(data, dict) else len(items),
            "repositories": [
                {
                    "name": repo.get("name"),
                    "full_name": repo.get("full_name"),
                    "description": (repo.get("description") or "")[:200],
                    "html_url": repo.get("html_url"),
                    "stargazers_count": repo.get("stargazers_count", 0),
                    "forks_count": repo.get("forks_count", 0),
                    "open_issues_count": repo.get("open_issues_count", 0),
                    "language": repo.get("language"),
                }
                for repo in items[:clamped_limit]
            ],
        }

    async def get_repository(
        self,
        owner: str,
        repo: str,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Get GitHub repository metadata."""
        headers = await self._get_auth_headers(context)
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/repos/{owner}/{repo}",
            provider="github",
            headers=headers,
        )
        if isinstance(data, dict):
            return {
                "name": data.get("name"),
                "full_name": data.get("full_name"),
                "html_url": data.get("html_url"),
                "description": data.get("description"),
                "stargazers_count": data.get("stargazers_count", 0),
                "forks_count": data.get("forks_count", 0),
                "open_issues_count": data.get("open_issues_count", 0),
                "default_branch": data.get("default_branch", "main"),
                "private": data.get("private", False),
            }
        return {}

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        limit: int = 10,
        context: ToolExecutionContext | None = None,
    ) -> list[dict[str, Any]]:
        """List GitHub repository issues."""
        headers = await self._get_auth_headers(context)
        clamped_limit = max(1, min(limit, 30))
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/repos/{owner}/{repo}/issues",
            provider="github",
            headers=headers,
            params={"state": state, "per_page": clamped_limit},
        )
        items = data if isinstance(data, list) else []
        return [
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "author": issue.get("user", {}).get("login"),
                "created_at": issue.get("created_at"),
                "comments": issue.get("comments", 0),
                "labels": [label.get("name") for label in issue.get("labels", []) if isinstance(label, dict)],
                "html_url": issue.get("html_url"),
            }
            for issue in items[:clamped_limit]
            if not issue.get("pull_request")
        ]

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Get single GitHub issue details."""
        headers = await self._get_auth_headers(context)
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/repos/{owner}/{repo}/issues/{issue_number}",
            provider="github",
            headers=headers,
        )
        if isinstance(data, dict):
            return {
                "number": data.get("number"),
                "title": data.get("title"),
                "state": data.get("state"),
                "author": data.get("user", {}).get("login"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "comments": data.get("comments", 0),
                "labels": [lbl.get("name") for lbl in data.get("labels", []) if isinstance(lbl, dict)],
                "body": (data.get("body") or "")[:2000],
                "html_url": data.get("html_url"),
            }
        return {}

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Create a new GitHub issue (mutating operation)."""
        headers = await self._get_auth_headers(context)
        payload = {"title": title, "body": body}
        data = await self.http_client.request(
            method="POST",
            url=f"{self.base_url}/repos/{owner}/{repo}/issues",
            provider="github",
            headers=headers,
            json=payload,
            allow_mutation_retry=False,
        )
        if isinstance(data, dict):
            return {
                "success": True,
                "number": data.get("number"),
                "title": data.get("title"),
                "html_url": data.get("html_url"),
            }
        return {}

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        limit: int = 10,
        context: ToolExecutionContext | None = None,
    ) -> list[dict[str, Any]]:
        """List GitHub repository pull requests."""
        headers = await self._get_auth_headers(context)
        clamped_limit = max(1, min(limit, 30))
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/repos/{owner}/{repo}/pulls",
            provider="github",
            headers=headers,
            params={"state": state, "per_page": clamped_limit},
        )
        items = data if isinstance(data, list) else []
        return [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "author": pr.get("user", {}).get("login"),
                "created_at": pr.get("created_at"),
                "html_url": pr.get("html_url"),
            }
            for pr in items[:clamped_limit]
        ]

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Get single GitHub pull request details."""
        headers = await self._get_auth_headers(context)
        data = await self.http_client.request(
            method="GET",
            url=f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}",
            provider="github",
            headers=headers,
        )
        if isinstance(data, dict):
            head_branch = data.get("head", {}).get("ref") if isinstance(data.get("head"), dict) else None
            return {
                "number": data.get("number"),
                "title": data.get("title"),
                "state": data.get("state"),
                "author": data.get("user", {}).get("login"),
                "head_branch": head_branch,
                "mergeable": data.get("mergeable"),
                "body": (data.get("body") or "")[:1500],
                "html_url": data.get("html_url"),
            }
        return {}

    async def invoke(
        self,
        capability_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> Any:
        """Route capability invocation to the corresponding helper method."""
        if capability_name == "github_search_repositories":
            return await self.search_repositories(
                query=arguments.get("query", ""),
                limit=arguments.get("limit", 10),
                context=context,
            )

        if capability_name == "github_get_repository":
            return await self.get_repository(
                owner=arguments["owner"],
                repo=arguments["repo"],
                context=context,
            )

        if capability_name == "github_list_issues":
            return await self.list_issues(
                owner=arguments["owner"],
                repo=arguments["repo"],
                state=arguments.get("state", "open"),
                limit=arguments.get("limit", 10),
                context=context,
            )

        if capability_name == "github_get_issue":
            return await self.get_issue(
                owner=arguments["owner"],
                repo=arguments["repo"],
                issue_number=arguments["issue_number"],
                context=context,
            )

        if capability_name == "github_create_issue":
            return await self.create_issue(
                owner=arguments["owner"],
                repo=arguments["repo"],
                title=arguments["title"],
                body=arguments.get("body", ""),
                context=context,
            )

        if capability_name == "github_list_pull_requests":
            return await self.list_pull_requests(
                owner=arguments["owner"],
                repo=arguments["repo"],
                state=arguments.get("state", "open"),
                limit=arguments.get("limit", 10),
                context=context,
            )

        if capability_name == "github_get_pull_request":
            return await self.get_pull_request(
                owner=arguments["owner"],
                repo=arguments["repo"],
                pull_number=arguments["pull_number"],
                context=context,
            )

        raise ConnectorError(f"Unknown GitHub capability: {capability_name}")
