"""Unit tests for normalized code intelligence domain models."""

import pytest

from app.domain.models.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    CodeStructure,
    SourceLocation,
    Symbol,
    SymbolKind,
    SyntaxDiagnostic,
)


def test_source_location_valid_invariants():
    loc = SourceLocation(
        file_path="app/main.py",
        start_line=1,
        start_column=0,
        end_line=10,
        end_column=25,
    )
    assert loc.file_path == "app/main.py"
    assert loc.start_line == 1
    assert loc.start_column == 0
    assert loc.end_line == 10
    assert loc.end_column == 25

    d = loc.to_dict()
    assert d["start_line"] == 1
    assert d["start_column"] == 0


def test_source_location_zero_width_allowed():
    loc = SourceLocation(
        file_path="app/main.py",
        start_line=5,
        start_column=10,
        end_line=5,
        end_column=10,
    )
    assert loc.start_line == loc.end_line
    assert loc.start_column == loc.end_column


def test_source_location_invalid_invariants():
    # Line numbers must be 1-indexed (>= 1)
    with pytest.raises(ValueError, match="Line numbers must be 1-indexed"):
        SourceLocation(file_path="a.py", start_line=0, start_column=0, end_line=1, end_column=0)

    # Columns must be 0-indexed (>= 0)
    with pytest.raises(ValueError, match="Columns must be 0-indexed"):
        SourceLocation(file_path="a.py", start_line=1, start_column=-1, end_line=1, end_column=0)

    # Start line cannot exceed end line
    with pytest.raises(ValueError, match="cannot exceed end coordinate"):
        SourceLocation(file_path="a.py", start_line=5, start_column=0, end_line=4, end_column=10)

    # Same line with start_column > end_column
    with pytest.raises(ValueError, match="cannot exceed end coordinate"):
        SourceLocation(file_path="a.py", start_line=5, start_column=12, end_line=5, end_column=10)


def test_symbol_creation_and_serialization():
    loc = SourceLocation(file_path="test.py", start_line=1, start_column=0, end_line=3, end_column=12)
    sym = Symbol(
        id="test.py::User.login",
        name="login",
        qualified_name="User.login",
        kind=SymbolKind.METHOD,
        location=loc,
        language="python",
        signature="def login(self, username: str) -> bool",
        docstring="Authenticate user.",
        parent_name="User",
        metadata={"async": False},
    )

    assert sym.name == "login"
    assert sym.qualified_name == "User.login"
    assert sym.kind == SymbolKind.METHOD
    assert sym.parent_name == "User"

    d = sym.to_dict()
    assert d["id"] == "test.py::User.login"
    assert d["kind"] == "method"
    assert d["location"]["start_line"] == 1


def test_code_relation_syntactic_flag():
    loc = SourceLocation(file_path="test.py", start_line=2, start_column=4, end_line=2, end_column=15)
    rel = CodeRelation(
        source_name="User.login",
        target_name="verify_password",
        relation_type=CodeRelationType.CALLS,
        location=loc,
        is_syntactic=True,
    )
    assert rel.is_syntactic is True
    assert rel.relation_type == CodeRelationType.CALLS

    d = rel.to_dict()
    assert d["is_syntactic"] is True
    assert d["relation_type"] == "calls"


def test_code_structure_creation():
    loc = SourceLocation(file_path="foo.py", start_line=1, start_column=0, end_line=5, end_column=0)
    sym = Symbol(
        id="foo.py::Foo",
        name="Foo",
        qualified_name="Foo",
        kind=SymbolKind.CLASS,
        location=loc,
        language="python",
    )
    diag = SyntaxDiagnostic(message="Test warning", location=loc, severity="warning")
    struct = CodeStructure(
        file_path="foo.py",
        language="python",
        content_hash="abc123hash",
        symbols=[sym],
        relationships=[],
        diagnostics=[diag],
        total_lines=5,
    )

    assert struct.file_path == "foo.py"
    assert len(struct.symbols) == 1
    assert len(struct.diagnostics) == 1
    assert struct.total_lines == 5

    d = struct.to_dict()
    assert d["content_hash"] == "abc123hash"
    assert len(d["symbols"]) == 1
