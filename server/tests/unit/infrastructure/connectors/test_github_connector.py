"""Unit tests for GitHubConnector reference implementation."""

import httpx
import pytest

from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import CapabilityType, RiskLevel
from app.domain.exceptions.connector_exceptions import ConnectorAuthenticationError
from app.domain.models.credential import Credential, CredentialType
from app.domain.models.workspace import Workspace
from app.infrastructure.connectors.credentials.env_credential_provider import (
    EnvAndDictCredentialProvider,
)
from app.infrastructure.connectors.github.github_connector import GitHubConnector
from app.infrastructure.http.external_client import ExternalHttpClient


@pytest.fixture
def credential_provider() -> EnvAndDictCredentialProvider:
    return EnvAndDictCredentialProvider()


@pytest.fixture
def mock_github_client() -> ExternalHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        auth = request.headers.get("authorization", "")
        if "Bearer valid_token" not in auth and "Bearer test_token" not in auth:
            return httpx.Response(401, json={"message": "Bad credentials"})

        if "/search/repositories" in url:
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "items": [
                        {
                            "name": "bytebuddhi",
                            "full_name": "Navin45/bytebuddhi",
                            "html_url": "https://github.com/Navin45/bytebuddhi",
                            "description": "AI agent platform",
                            "stargazers_count": 42,
                            "forks_count": 5,
                            "open_issues_count": 2,
                        }
                    ],
                },
            )
        if "/repos/test/repo/issues/42" in url:
            return httpx.Response(
                200,
                json={
                    "number": 42,
                    "title": "Bug in parser",
                    "state": "open",
                    "body": "Parser crashed on EOF",
                    "user": {"login": "alice"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "comments": 3,
                    "labels": [{"name": "bug"}],
                    "html_url": "https://github.com/test/repo/issues/42",
                },
            )
        if "/repos/test/repo/issues" in url and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "number": 43,
                    "title": "New issue",
                    "state": "open",
                    "body": "Created by agent",
                    "user": {"login": "bot"},
                    "created_at": "2026-01-03T00:00:00Z",
                    "updated_at": "2026-01-03T00:00:00Z",
                    "comments": 0,
                    "labels": [],
                    "html_url": "https://github.com/test/repo/issues/43",
                },
            )
        if "/repos/test/repo/issues" in url and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "Issue 1",
                        "state": "open",
                        "body": "Desc 1",
                        "user": {"login": "alice"},
                        "created_at": "2026-01-01T00:00:00Z",
                        "comments": 0,
                        "labels": [],
                        "html_url": "https://github.com/test/repo/issues/1",
                    }
                ],
            )
        if "/repos/test/repo/pulls/10" in url:
            return httpx.Response(
                200,
                json={
                    "number": 10,
                    "title": "Feature PR",
                    "state": "open",
                    "body": "Adds feature",
                    "user": {"login": "bob"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "html_url": "https://github.com/test/repo/pulls/10",
                    "head": {"ref": "feature"},
                    "base": {"ref": "main"},
                    "mergeable": True,
                },
            )
        if "/repos/test/repo/pulls" in url:
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 10,
                        "title": "Feature PR",
                        "state": "open",
                        "body": "Adds feature",
                        "user": {"login": "bob"},
                        "created_at": "2026-01-01T00:00:00Z",
                        "html_url": "https://github.com/test/repo/pulls/10",
                        "head": {"ref": "feature"},
                        "base": {"ref": "main"},
                    }
                ],
            )
        if "/repos/test/repo" in url:
            return httpx.Response(
                200,
                json={
                    "name": "repo",
                    "full_name": "test/repo",
                    "html_url": "https://github.com/test/repo",
                    "description": "Test repository",
                    "stargazers_count": 10,
                    "forks_count": 2,
                    "open_issues_count": 1,
                    "default_branch": "main",
                    "private": False,
                },
            )
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport)
    return ExternalHttpClient(client=raw_client, max_retries=1)


@pytest.mark.asyncio
async def test_github_connector_capabilities_metadata(
    credential_provider: EnvAndDictCredentialProvider,
    mock_github_client: ExternalHttpClient,
):
    """Verify GitHubConnector exposes all 7 capabilities with correct metadata."""
    connector = GitHubConnector(
        credential_provider=credential_provider,
        client=mock_github_client,
    )
    caps = connector.get_capabilities()
    assert len(caps) == 7

    names = {defn.name for defn in caps}
    expected = {
        "github_search_repositories",
        "github_get_repository",
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_list_pull_requests",
        "github_get_pull_request",
    }
    assert names == expected

    for defn in caps:
        assert defn.capability_type == CapabilityType.CONNECTOR
        if defn.name == "github_create_issue":
            assert defn.risk_level == RiskLevel.HIGH
            assert defn.requires_approval is True
        else:
            assert defn.risk_level == RiskLevel.LOW
            assert defn.requires_approval is False


@pytest.mark.asyncio
async def test_github_connector_auth_failure_when_no_token(
    credential_provider: EnvAndDictCredentialProvider,
    mock_github_client: ExternalHttpClient,
):
    """Verify calling a GitHub tool without credentials raises ConnectorAuthenticationError."""
    connector = GitHubConnector(
        credential_provider=credential_provider,
        client=mock_github_client,
    )
    ws = Workspace.create(root_path=".")
    ctx = ToolExecutionContext(run_id="r1", tool_call_id="c1", workspace=ws, user_id="unregistered_user")

    with pytest.raises(ConnectorAuthenticationError, match="No GitHub token found"):
        await connector.search_repositories(query="test", context=ctx)


@pytest.mark.asyncio
async def test_github_connector_all_capabilities_execution(
    credential_provider: EnvAndDictCredentialProvider,
    mock_github_client: ExternalHttpClient,
):
    """Verify execution of all 7 GitHub capabilities with valid credential."""
    await credential_provider.set_credential(
        "github",
        Credential(
            name="token",
            provider="github",
            credential_type=CredentialType.BEARER_TOKEN,
            secret_value="valid_token",
        ),
        user_id="user1",
    )

    connector = GitHubConnector(
        credential_provider=credential_provider,
        client=mock_github_client,
    )
    ws = Workspace.create(root_path=".")
    ctx = ToolExecutionContext(run_id="r1", tool_call_id="c1", workspace=ws, user_id="user1")

    # 1. Search repos
    res_search = await connector.search_repositories(query="bytebuddhi", context=ctx)
    assert res_search["total_count"] == 1
    assert res_search["repositories"][0]["full_name"] == "Navin45/bytebuddhi"

    # 2. Get repo
    res_repo = await connector.get_repository(owner="test", repo="repo", context=ctx)
    assert res_repo["full_name"] == "test/repo"

    # 3. List issues
    res_issues = await connector.list_issues(owner="test", repo="repo", context=ctx)
    assert len(res_issues) == 1
    assert res_issues[0]["number"] == 1

    # 4. Get issue
    res_issue = await connector.get_issue(owner="test", repo="repo", issue_number=42, context=ctx)
    assert res_issue["number"] == 42
    assert res_issue["title"] == "Bug in parser"

    # 5. Create issue
    res_create = await connector.create_issue(
        owner="test", repo="repo", title="New issue", body="Created by agent", context=ctx
    )
    assert res_create["number"] == 43
    assert res_create["title"] == "New issue"

    # 6. List pull requests
    res_prs = await connector.list_pull_requests(owner="test", repo="repo", context=ctx)
    assert len(res_prs) == 1
    assert res_prs[0]["number"] == 10

    # 7. Get pull request
    res_pr = await connector.get_pull_request(owner="test", repo="repo", pull_number=10, context=ctx)
    assert res_pr["number"] == 10
    assert res_pr["head_branch"] == "feature"
