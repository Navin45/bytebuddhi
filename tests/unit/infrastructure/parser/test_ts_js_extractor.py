"""Unit tests for TypeScriptJavaScriptExtractor."""

import pytest

from app.domain.models.code_intelligence import CodeRelationType, SymbolKind
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


@pytest.fixture
def parser() -> TreeSitterCodeParser:
    return TreeSitterCodeParser()


def test_ts_extractor_interfaces_and_types(parser: TreeSitterCodeParser) -> None:
    code = """
interface Identifiable {
    id: string;
}

interface UserProfile extends Identifiable {
    username: string;
    email?: string;
}

type UserStatus = "active" | "inactive" | "suspended";
"""
    structure = parser.parse(code, language="typescript", file_path="types.ts")

    assert structure.file_path == "types.ts"
    assert structure.language == "typescript"

    sym_names = [s.name for s in structure.symbols]
    assert "Identifiable" in sym_names
    assert "UserProfile" in sym_names
    assert "UserStatus" in sym_names

    iface = next(s for s in structure.symbols if s.name == "UserProfile")
    assert iface.kind == SymbolKind.INTERFACE
    assert iface.signature == "interface UserProfile extends Identifiable"

    type_sym = next(s for s in structure.symbols if s.name == "UserStatus")
    assert type_sym.kind == SymbolKind.TYPE_ALIAS

    # Inheritance relation
    inherits = [r for r in structure.relationships if r.relation_type == CodeRelationType.INHERITS]
    assert len(inherits) == 1
    assert inherits[0].source_name == "UserProfile"
    assert inherits[0].target_name == "Identifiable"
    assert inherits[0].is_syntactic is True


def test_ts_extractor_classes_and_methods(parser: TreeSitterCodeParser) -> None:
    code = """
class UserService extends BaseService implements IUserService {
    private db: Database;

    constructor(db: Database) {
        this.db = db;
    }

    async findUser(id: string): Promise<User> {
        return this.db.get(id);
    }
}
"""
    structure = parser.parse(code, language="typescript", file_path="user_service.ts")

    syms = structure.symbols
    class_sym = next(s for s in syms if s.name == "UserService")
    assert class_sym.kind == SymbolKind.CLASS

    method_sym = next(s for s in syms if s.name == "findUser")
    assert method_sym.kind == SymbolKind.METHOD
    assert method_sym.parent_name == "UserService"
    assert method_sym.qualified_name == "UserService.findUser"

    # Inheritance
    inherits = [r for r in structure.relationships if r.relation_type == CodeRelationType.INHERITS]
    assert len(inherits) >= 1
    target_names = [r.target_name for r in inherits]
    assert "BaseService" in target_names


def test_ts_extractor_functions_and_arrow_functions(parser: TreeSitterCodeParser) -> None:
    code = """
export function add(a: number, b: number): number {
    return a + b;
}

export const multiply = (x: number, y: number): number => {
    return x * y;
};
"""
    structure = parser.parse(code, language="typescript", file_path="math.ts")

    sym_names = [s.name for s in structure.symbols]
    assert "add" in sym_names
    assert "multiply" in sym_names

    add_sym = next(s for s in structure.symbols if s.name == "add")
    assert add_sym.kind == SymbolKind.FUNCTION

    mul_sym = next(s for s in structure.symbols if s.name == "multiply")
    assert mul_sym.kind == SymbolKind.FUNCTION


def test_ts_extractor_imports_and_calls(parser: TreeSitterCodeParser) -> None:
    code = """
import { useState, useEffect } from 'react';
import axios from 'axios';

function App() {
    useEffect(() => {
        fetchData();
    }, []);
}
"""
    structure = parser.parse(code, language="tsx", file_path="App.tsx")

    imports = [r for r in structure.relationships if r.relation_type == CodeRelationType.IMPORTS]
    imported_targets = [r.target_name for r in imports]
    assert "react::useState" in imported_targets
    assert "react::useEffect" in imported_targets
    assert "axios" in imported_targets or "axios::axios" in imported_targets

    calls = [r for r in structure.relationships if r.relation_type == CodeRelationType.CALLS]
    call_targets = [r.target_name for r in calls]
    assert "useEffect" in call_targets
    assert all(c.is_syntactic for c in calls)
