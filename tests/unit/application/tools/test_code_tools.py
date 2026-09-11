"""Unit tests for builtin code intelligence tools."""

import json
from pathlib import Path

import pytest

from app.application.code.in_memory_index import InMemoryCodeIndex
from app.application.code.intelligence_service import CodeIntelligenceService
from app.application.tools.builtin.code_tools import create_code_tools
from app.application.tools.context import ToolExecutionContext
from app.application.tools.definition import ToolCall
from app.application.tools.executor import ToolExecutor
from app.application.tools.registry import ToolRegistry
from app.domain.models.workspace import Workspace
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.create(root_path=str(tmp_path), workspace_id="ws_code")


@pytest.fixture
def code_service() -> CodeIntelligenceService:
    parser = TreeSitterCodeParser()
    index = InMemoryCodeIndex()
    return CodeIntelligenceService(parser=parser, index=index)


@pytest.fixture
def registry_and_executor(code_service: CodeIntelligenceService, workspace: Workspace):
    registry = ToolRegistry()
    for defn, handler in create_code_tools(code_service, default_workspace=workspace):
        registry.register(defn, handler)
    executor = ToolExecutor(registry)
    return registry, executor


@pytest.mark.asyncio
async def test_code_tools_registration(registry_and_executor):
    registry, _ = registry_and_executor
    tool_names = [t.name for t in registry.list_definitions()]

    expected_tools = [
        "list_code_files",
        "get_code_structure",
        "get_symbol_definition",
        "find_symbols",
        "find_references",
        "search_code_structure",
    ]
    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_list_code_files_tool(registry_and_executor, workspace: Workspace, tmp_path: Path):
    _, executor = registry_and_executor
    (tmp_path / "app.py").write_text("print('app')", encoding="utf-8")
    (tmp_path / "service.ts").write_text("export const s = 1;", encoding="utf-8")

    context = ToolExecutionContext(run_id="r1", tool_call_id="c1", workspace=workspace)
    call = ToolCall(id="c1", name="list_code_files", arguments={"subpath": ".", "max_files": 10})

    result = await executor.execute(call, context=context)
    assert not result.is_error
    data = json.loads(result.content)
    assert data["count"] == 2
    assert "app.py" in data["files"]
    assert "service.ts" in data["files"]


@pytest.mark.asyncio
async def test_get_code_structure_tool(registry_and_executor, workspace: Workspace, tmp_path: Path):
    _, executor = registry_and_executor
    (tmp_path / "calc.py").write_text(
        "class Calculator:\n    def add(self, a, b):\n        return a + b\n",
        encoding="utf-8",
    )

    context = ToolExecutionContext(run_id="r1", tool_call_id="c2", workspace=workspace)
    call = ToolCall(id="c2", name="get_code_structure", arguments={"path": "calc.py", "max_depth": 3})

    result = await executor.execute(call, context=context)
    assert not result.is_error
    data = json.loads(result.content)
    assert data["file_path"] == "calc.py"
    assert len(data["symbols"]) == 1
    assert data["symbols"][0]["name"] == "Calculator"
    assert len(data["symbols"][0]["children"]) == 1
    assert data["symbols"][0]["children"][0]["name"] == "add"


@pytest.mark.asyncio
async def test_get_symbol_definition_tool(registry_and_executor, workspace: Workspace, tmp_path: Path):
    _, executor = registry_and_executor
    (tmp_path / "models.py").write_text(
        'class Account:\n    """Account representation."""\n    def balance(self) -> float:\n        return 0.0\n',
        encoding="utf-8",
    )

    context = ToolExecutionContext(run_id="r1", tool_call_id="c3", workspace=workspace)

    # Find Account
    call = ToolCall(id="c3", name="get_symbol_definition", arguments={"name": "Account", "file_path": "models.py"})
    result = await executor.execute(call, context=context)
    assert not result.is_error
    data = json.loads(result.content)
    assert data["found"] is True
    assert data["symbol"]["name"] == "Account"
    assert data["symbol"]["kind"] == "class"

    # Find nonexistent
    call_missing = ToolCall(id="c4", name="get_symbol_definition", arguments={"name": "Ghost"})
    res_missing = await executor.execute(call_missing, context=context)
    assert not res_missing.is_error
    assert json.loads(res_missing.content)["found"] is False


@pytest.mark.asyncio
async def test_find_symbols_and_references_tools(registry_and_executor, workspace: Workspace, tmp_path: Path):
    _, executor = registry_and_executor
    (tmp_path / "service.py").write_text(
        "def compute():\n    return 42\ndef run():\n    return compute()\n",
        encoding="utf-8",
    )

    context = ToolExecutionContext(run_id="r1", tool_call_id="c5", workspace=workspace)

    # find_symbols
    call_syms = ToolCall(id="c5", name="find_symbols", arguments={"query": "compute", "file_path": "service.py"})
    res_syms = await executor.execute(call_syms, context=context)
    assert not res_syms.is_error
    data_syms = json.loads(res_syms.content)
    assert data_syms["count"] >= 1
    assert data_syms["symbols"][0]["name"] == "compute"

    # find_references
    call_refs = ToolCall(id="c6", name="find_references", arguments={"symbol_name": "compute"})
    res_refs = await executor.execute(call_refs, context=context)
    assert not res_refs.is_error
    data_refs = json.loads(res_refs.content)
    assert data_refs["count"] >= 1
    assert data_refs["references"][0]["target_name"] == "compute"
    assert data_refs["references"][0]["is_syntactic"] is True


@pytest.mark.asyncio
async def test_search_code_structure_tool(registry_and_executor, workspace: Workspace, tmp_path: Path):
    _, executor = registry_and_executor
    (tmp_path / "api.py").write_text(
        'def handle_payment():\n    """Process credit card payments."""\n    pass\n',
        encoding="utf-8",
    )

    context = ToolExecutionContext(run_id="r1", tool_call_id="c7", workspace=workspace)

    # First analyze so search can find it
    analyze_call = ToolCall(id="c7a", name="get_code_structure", arguments={"path": "api.py"})
    await executor.execute(analyze_call, context=context)

    # Search by docstring keyword
    search_call = ToolCall(id="c7b", name="search_code_structure", arguments={"query": "credit card"})
    search_res = await executor.execute(search_call, context=context)
    assert not search_res.is_error
    data = json.loads(search_res.content)
    assert data["count"] == 1
    assert data["results"][0]["symbol"] == "handle_payment"
