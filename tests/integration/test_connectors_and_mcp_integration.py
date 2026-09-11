"""End-to-end integration test for AgentRuntime with native tools, GitHub connector, and MCP capabilities."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.application.agent.runtime import AgentRuntime
from app.application.agent.types import AgentStatus
from app.application.policy.tool_policy import ToolPolicyEngine
from app.application.ports.output.llm.model_gateway import ModelGateway, ModelResponse
from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
from app.application.tools.definition import ToolCall, ToolDefinition
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.credential import Credential, CredentialType
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.mcp import MCPServerConfig
from app.domain.models.workspace import Workspace
from app.infrastructure.connectors.credentials.env_credential_provider import (
    EnvAndDictCredentialProvider,
)
from app.infrastructure.connectors.github.github_connector import GitHubConnector
from app.infrastructure.http.external_client import ExternalHttpClient
from app.infrastructure.mcp.client_manager import MCPCapabilityManager
from app.infrastructure.mcp.mock_mcp_client import MockMCPClient
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.mark.asyncio
async def test_agent_runtime_with_connectors_and_mcp(tmp_path):
    """Verify AgentRuntime can execute native tools, external connector tools, and MCP tools in a unified loop."""
    workspace = Workspace.create(root_path=tmp_path, workspace_id="ws_connector_e2e")
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")
    registry = ToolRegistry()

    # 1. Register Native Tools
    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)

    # 2. Setup & Register GitHub Connector
    cred_provider = EnvAndDictCredentialProvider()
    await cred_provider.set_credential(
        "github",
        Credential(
            name="github_token",
            provider="github",
            credential_type=CredentialType.BEARER_TOKEN,
            secret_value="ghp_test_e2e_secret",
        ),
        user_id="alice",
    )

    def mock_github_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/repos/test-org/test-repo" in url:
            return httpx.Response(
                200,
                json={
                    "name": "test-repo",
                    "full_name": "test-org/test-repo",
                    "description": "Integration test repository",
                    "html_url": "https://github.com/test-org/test-repo",
                    "stargazers_count": 99,
                    "forks_count": 12,
                    "open_issues_count": 3,
                    "default_branch": "main",
                    "private": False,
                },
            )
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(mock_github_handler)
    raw_http = httpx.AsyncClient(transport=transport)
    http_client = ExternalHttpClient(client=raw_http, max_retries=1)
    github_connector = GitHubConnector(credential_provider=cred_provider, client=http_client)

    github_connector.register_capabilities(registry)

    # 3. Setup & Register MCP Capabilities
    mcp_manager = MCPCapabilityManager(registry=registry)
    mcp_config = MCPServerConfig(
        name="docs_server",
        transport="stdio",
        command="docs_cli",
        capability_allowlist=["fetch_doc"],
    )
    mock_mcp_client = MockMCPClient(
        server_config=mcp_config,
        available_tools=[
            {
                "name": "fetch_doc",
                "description": "Fetch documentation content",
                "inputSchema": {
                    "type": "object",
                    "properties": {"doc_id": {"type": "string"}},
                    "required": ["doc_id"],
                },
            }
        ],
    )
    mcp_manager.register_server(mcp_config, client=mock_mcp_client)
    await mcp_manager.discover_capabilities("docs_server")

    # 4. Register a tool that returns large content to verify output bounding & archiving
    def generate_large_payload() -> str:
        return "A" * 8000  # > 6000 max_output_chars

    registry.register(
        ToolDefinition(name="get_big_data", description="Returns large payload"),
        generate_large_payload,
    )

    # 5. Build Executor and Policy
    policy = ToolPolicyEngine(registry=registry)
    executor = ToolExecutor(
        registry=registry,
        policy_engine=policy,
        artifact_store=artifact_store,
        max_output_chars=6000,
    )

    # 6. Mock ModelGateway: Turn 1 calls GitHub, Turn 2 calls MCP, Turn 3 calls Large Data, Turn 4 finishes
    mock_gateway = AsyncMock(spec=ModelGateway)
    mock_gateway.generate.side_effect = [
        # Turn 1: Call GitHub
        ModelResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_gh",
                    name="github_get_repository",
                    arguments={"owner": "test-org", "repo": "test-repo"},
                )
            ],
            model="test-model",
        ),
        # Turn 2: Call MCP
        ModelResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_mcp",
                    name="mcp_docs_server_fetch_doc",
                    arguments={"doc_id": "architecture_overview"},
                )
            ],
            model="test-model",
        ),
        # Turn 3: Call Large Data tool
        ModelResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_big",
                    name="get_big_data",
                    arguments={},
                )
            ],
            model="test-model",
        ),
        # Turn 4: Final response
        ModelResponse(
            content="Retrieved GitHub repo details, fetched MCP documentation, and processed the large dataset.",
            tool_calls=[],
            model="test-model",
        ),
    ]

    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=registry,
        tool_executor=executor,
        workspace=workspace,
    )

    # Execute agent run with user_id metadata
    messages = [{"role": "user", "content": "Fetch repo, docs, and big dataset"}]
    run_state = await runtime.run(
        messages=messages,
        workspace=workspace,
        execution_context=ExecutionContext(
            user_id="alice",
            project_id="proj_e2e",
            conversation_id=None,
            run_id="run_connectors",
            workspace_id=workspace.workspace_id,
        ),
    )

    assert run_state.status == AgentStatus.COMPLETED
    assert run_state.iteration == 4
    assert len(run_state.tool_calls) == 3
    assert len(run_state.tool_results) == 3

    # Check result 1: GitHub connector
    gh_result = run_state.tool_results[0]
    assert gh_result.name == "github_get_repository"
    assert not gh_result.is_error
    assert "test-org/test-repo" in gh_result.content

    # Check result 2: MCP capability
    mcp_result = run_state.tool_results[1]
    assert mcp_result.name == "mcp_docs_server_fetch_doc"
    assert not mcp_result.is_error
    assert "architecture_overview" in mcp_result.content

    # Check result 3: Large output bounded and archived
    big_result = run_state.tool_results[2]
    assert big_result.name == "get_big_data"
    assert not big_result.is_error
    assert "Large output archived to artifact" in big_result.content
    assert len(big_result.content) < 6000  # Truncated preview in context

    # Check final response
    assert run_state.final_response == (
        "Retrieved GitHub repo details, fetched MCP documentation, and processed the large dataset."
    )
