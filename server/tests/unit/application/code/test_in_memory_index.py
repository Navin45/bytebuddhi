"""Unit tests for InMemoryCodeIndex."""

import pytest

from app.application.code.in_memory_index import InMemoryCodeIndex
from app.domain.models.code_intelligence import (
    CodeStructure,
    SourceLocation,
    Symbol,
    SymbolKind,
)


@pytest.fixture
def index() -> InMemoryCodeIndex:
    return InMemoryCodeIndex()


def _create_sample_structure(file_path: str, content_hash: str, symbol_names: list[str]) -> CodeStructure:
    symbols = []
    for name in symbol_names:
        loc = SourceLocation(file_path=file_path, start_line=1, start_column=0, end_line=5, end_column=0)
        kind = SymbolKind.CLASS if name[0].isupper() else SymbolKind.FUNCTION
        symbols.append(
            Symbol(
                id=f"{file_path}::{name}",
                name=name,
                qualified_name=name,
                kind=kind,
                location=loc,
                language="python",
            )
        )
    return CodeStructure(
        file_path=file_path,
        language="python",
        content_hash=content_hash,
        symbols=symbols,
        relationships=[],
        diagnostics=[],
        total_lines=10,
    )


def test_index_set_get_and_content_hash(index: InMemoryCodeIndex) -> None:
    struct = _create_sample_structure("app/main.py", "hash123", ["MainApp", "run"])
    index.set("app/main.py", struct)

    retrieved = index.get("app/main.py")
    assert retrieved is not None
    assert retrieved.file_path == "app/main.py"
    assert retrieved.content_hash == "hash123"
    assert len(retrieved.symbols) == 2

    assert index.get_content_hash("app/main.py") == "hash123"
    assert index.get_content_hash("nonexistent.py") is None


def test_index_remove_and_clear(index: InMemoryCodeIndex) -> None:
    struct1 = _create_sample_structure("a.py", "h1", ["Foo"])
    struct2 = _create_sample_structure("b.py", "h2", ["Bar"])
    index.set("a.py", struct1)
    index.set("b.py", struct2)

    assert index.remove("a.py") is True
    assert index.get("a.py") is None
    assert index.remove("a.py") is False

    assert index.get("b.py") is not None
    index.clear()
    assert index.get("b.py") is None
    assert len(index.get_all_structures()) == 0


def test_index_find_symbols_query_filtering(index: InMemoryCodeIndex) -> None:
    struct1 = _create_sample_structure("a.py", "h1", ["UserService", "authenticate"])
    struct2 = _create_sample_structure("b.py", "h2", ["UserRepo", "find_by_id"])
    index.set("a.py", struct1)
    index.set("b.py", struct2)

    # Search for "user"
    results = index.find_symbols(query="user")
    names = [s.name for s in results]
    assert "UserService" in names
    assert "UserRepo" in names
    assert "authenticate" not in names


def test_index_find_symbols_kind_filtering(index: InMemoryCodeIndex) -> None:
    struct = _create_sample_structure("a.py", "h1", ["UserService", "login_user"])
    index.set("a.py", struct)

    classes = index.find_symbols(query="", kind=SymbolKind.CLASS)
    assert len(classes) == 1
    assert classes[0].name == "UserService"

    functions = index.find_symbols(query="", kind=SymbolKind.FUNCTION)
    assert len(functions) == 1
    assert functions[0].name == "login_user"


def test_index_find_symbols_file_path_narrowing(index: InMemoryCodeIndex) -> None:
    struct1 = _create_sample_structure("service.py", "h1", ["execute"])
    struct2 = _create_sample_structure("client.py", "h2", ["execute"])
    index.set("service.py", struct1)
    index.set("client.py", struct2)

    all_exec = index.find_symbols(query="execute")
    assert len(all_exec) == 2

    narrowed = index.find_symbols(query="execute", file_path="service.py")
    assert len(narrowed) == 1
    assert narrowed[0].location.file_path == "service.py"
