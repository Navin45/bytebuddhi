"""Unit tests for PythonLanguageExtractor."""

import pytest

from app.domain.models.code_intelligence import CodeRelationType, SymbolKind
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


@pytest.fixture
def parser() -> TreeSitterCodeParser:
    return TreeSitterCodeParser()


def test_python_extractor_classes_and_methods(parser: TreeSitterCodeParser) -> None:
    code = """
class BaseService:
    \"\"\"Base service docstring.\"\"\"
    version: str = "1.0"

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self) -> bool:
        \"\"\"Execute doc.\"\"\"
        return True

class ChildService(BaseService):
    def execute(self) -> bool:
        super().execute()
        return False
"""
    structure = parser.parse(code, language="python", file_path="service.py")

    assert structure.file_path == "service.py"
    assert structure.language == "python"
    assert len(structure.diagnostics) == 0

    sym_names = [s.name for s in structure.symbols]
    assert "BaseService" in sym_names
    assert "ChildService" in sym_names
    assert "__init__" in sym_names
    assert "execute" in sym_names

    # Check qualified names & parent names
    base_cls = next(s for s in structure.symbols if s.name == "BaseService")
    assert base_cls.kind == SymbolKind.CLASS
    assert base_cls.docstring == "Base service docstring."
    assert base_cls.signature == "class BaseService"
    assert base_cls.parent_name is None

    child_cls = next(s for s in structure.symbols if s.name == "ChildService")
    assert child_cls.signature == "class ChildService(BaseService)"

    init_m = next(s for s in structure.symbols if s.qualified_name == "BaseService.__init__")
    assert init_m.kind == SymbolKind.METHOD
    assert init_m.parent_name == "BaseService"

    # Inheritance relation
    inherits_rels = [r for r in structure.relationships if r.relation_type == CodeRelationType.INHERITS]
    assert len(inherits_rels) == 1
    assert inherits_rels[0].source_name == "ChildService"
    assert inherits_rels[0].target_name == "BaseService"
    assert inherits_rels[0].is_syntactic is True


def test_python_extractor_functions_and_calls(parser: TreeSitterCodeParser) -> None:
    code = """
def helper(x: int) -> int:
    return x * 2

def main() -> None:
    val = helper(10)
    print(val)
"""
    structure = parser.parse(code, language="python", file_path="main.py")

    assert len(structure.symbols) >= 2
    helper_sym = next(s for s in structure.symbols if s.name == "helper")
    assert helper_sym.kind == SymbolKind.FUNCTION
    assert helper_sym.signature == "def helper(x: int) -> int"

    # Syntactic calls
    call_rels = [r for r in structure.relationships if r.relation_type == CodeRelationType.CALLS]
    assert len(call_rels) >= 2
    for r in call_rels:
        assert r.is_syntactic is True
        assert r.source_name == "main"
    call_targets = [r.target_name for r in call_rels]
    assert "helper" in call_targets
    assert "print" in call_targets


def test_python_extractor_imports(parser: TreeSitterCodeParser) -> None:
    code = """
import os
import sys
from pathlib import Path
from app.models import User, Item
"""
    structure = parser.parse(code, language="python", file_path="app.py")

    import_rels = [r for r in structure.relationships if r.relation_type == CodeRelationType.IMPORTS]
    target_names = [r.target_name for r in import_rels]

    assert "os" in target_names
    assert "sys" in target_names
    assert "pathlib.Path" in target_names
    assert "app.models.User" in target_names
    assert "app.models.Item" in target_names

    for r in import_rels:
        assert r.is_syntactic is True


def test_python_extractor_decorators(parser: TreeSitterCodeParser) -> None:
    code = """
@dataclass
class Config:
    timeout: int = 30

    @classmethod
    @validator
    def build(cls):
        pass
"""
    structure = parser.parse(code, language="python", file_path="config.py")

    cfg = next(s for s in structure.symbols if s.name == "Config")
    assert "@dataclass" in cfg.metadata.get("decorators", [])

    build_fn = next(s for s in structure.symbols if s.name == "build")
    decs = build_fn.metadata.get("decorators", [])
    assert "@classmethod" in decs
    assert "@validator" in decs


def test_python_extractor_nested_definitions(parser: TreeSitterCodeParser) -> None:
    code = """
def outer():
    def inner():
        pass
    return inner
"""
    structure = parser.parse(code, language="python", file_path="nested.py")

    outer_sym = next(s for s in structure.symbols if s.name == "outer")
    inner_sym = next(s for s in structure.symbols if s.name == "inner")

    assert outer_sym.parent_name is None
    assert inner_sym.parent_name == "outer"
    assert inner_sym.qualified_name == "outer.inner"
