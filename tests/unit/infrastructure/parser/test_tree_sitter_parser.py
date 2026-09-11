"""Unit tests for TreeSitterCodeParser adapter."""

from app.domain.models.code_intelligence import SymbolKind
from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser


def test_parser_supported_languages():
    parser = TreeSitterCodeParser()
    langs = parser.supported_languages()
    assert "python" in langs
    assert "javascript" in langs
    assert "typescript" in langs
    assert "tsx" in langs
    assert parser.can_parse("python")
    assert parser.can_parse("TypeScript")
    assert not parser.can_parse("haskell")


def test_parse_valid_python():
    parser = TreeSitterCodeParser()
    code = "class Calculator:\n    def add(self, a: int, b: int) -> int:\n        return a + b\n"
    struct = parser.parse(code, language="python", file_path="calc.py")

    assert struct.file_path == "calc.py"
    assert struct.language == "python"
    assert len(struct.diagnostics) == 0
    assert len(struct.symbols) == 2

    cls_sym = next(s for s in struct.symbols if s.kind == SymbolKind.CLASS)
    assert cls_sym.name == "Calculator"
    assert cls_sym.location.start_line == 1
    assert cls_sym.location.start_column == 0

    method_sym = next(s for s in struct.symbols if s.kind == SymbolKind.METHOD)
    assert method_sym.name == "add"
    assert method_sym.qualified_name == "Calculator.add"
    assert method_sym.parent_name == "Calculator"
    assert method_sym.location.start_line == 2


def test_parse_valid_typescript():
    parser = TreeSitterCodeParser()
    code = (
        "interface User {\n"
        "    id: string;\n"
        "    name: string;\n"
        "}\n\n"
        "class UserService {\n"
        "    getUser(id: string): User {\n"
        "        return { id, name: 'Alice' };\n"
        "    }\n"
        "}\n"
    )
    struct = parser.parse(code, language="typescript", file_path="user.ts")

    assert struct.file_path == "user.ts"
    assert struct.language == "typescript"
    assert len(struct.diagnostics) == 0

    iface = next(s for s in struct.symbols if s.kind == SymbolKind.INTERFACE)
    assert iface.name == "User"

    cls = next(s for s in struct.symbols if s.kind == SymbolKind.CLASS)
    assert cls.name == "UserService"

    method = next(s for s in struct.symbols if s.kind == SymbolKind.METHOD)
    assert method.name == "getUser"
    assert method.qualified_name == "UserService.getUser"


def test_parse_valid_tsx():
    parser = TreeSitterCodeParser()
    code = (
        "import React from 'react';\n"
        "export const Greeting = (props: { name: string }) => {\n"
        "    return <h1>Hello, {props.name}</h1>;\n"
        "};\n"
    )
    struct = parser.parse(code, language="tsx", file_path="Greeting.tsx")

    assert struct.file_path == "Greeting.tsx"
    assert struct.language == "tsx"
    assert len(struct.diagnostics) == 0

    fn = next(s for s in struct.symbols if s.kind == SymbolKind.FUNCTION)
    assert fn.name == "Greeting"


def test_parser_error_recovery_malformed_source():
    parser = TreeSitterCodeParser()
    # Malformed Python: statement with syntax error followed by valid class
    malformed_code = (
        "x = %%% invalid python syntax %%%\n\nclass RecoveredClass:\n    def valid_method(self):\n        pass\n"
    )
    struct = parser.parse(malformed_code, language="python", file_path="malformed.py")

    # Does not crash; emits syntax diagnostics for the error
    assert len(struct.diagnostics) > 0
    assert any(d.severity == "error" for d in struct.diagnostics)

    # Recovers surrounding valid AST symbols
    recovered_cls = next((s for s in struct.symbols if s.name == "RecoveredClass"), None)
    assert recovered_cls is not None
    assert recovered_cls.kind == SymbolKind.CLASS

    recovered_method = next((s for s in struct.symbols if s.name == "valid_method"), None)
    assert recovered_method is not None


def test_parser_unsupported_language_handling():
    parser = TreeSitterCodeParser()
    struct = parser.parse("int main() { return 0; }", language="c_unknown", file_path="main.c")

    assert struct.file_path == "main.c"
    assert len(struct.diagnostics) == 1
    assert struct.diagnostics[0].severity == "warning"
    assert "Unsupported language" in struct.diagnostics[0].message
    assert len(struct.symbols) == 0


def test_parser_crlf_vs_lf_coordinate_consistency():
    parser = TreeSitterCodeParser()
    code_lf = "class Foo:\n    def bar(self):\n        pass\n"
    code_crlf = "class Foo:\r\n    def bar(self):\r\n        pass\r\n"

    struct_lf = parser.parse(code_lf, language="python", file_path="test.py")
    struct_crlf = parser.parse(code_crlf, language="python", file_path="test.py")

    sym_lf = next(s for s in struct_lf.symbols if s.name == "bar")
    sym_crlf = next(s for s in struct_crlf.symbols if s.name == "bar")

    assert sym_lf.location.start_line == 2
    assert sym_crlf.location.start_line == 2
    assert sym_lf.location.start_column == sym_crlf.location.start_column


def test_parser_unicode_identifiers():
    parser = TreeSitterCodeParser()
    code = "class Donnée:\n    def café(self):\n        pass\n"
    struct = parser.parse(code, language="python", file_path="unicode.py")

    cls = next(s for s in struct.symbols if s.kind == SymbolKind.CLASS)
    assert cls.name == "Donnée"
    method = next(s for s in struct.symbols if s.kind == SymbolKind.METHOD)
    assert method.name == "café"


def test_source_location_invariants_comprehensive():
    """Verify coordinate invariants: line 1-indexed, column 0-indexed across declarations."""
    parser = TreeSitterCodeParser()
    # 1. Single-line declaration
    # 2. Multi-line declaration
    # 3. Nested symbol
    # 4. UTF-8 content and Unicode comments
    # 5. CRLF and LF consistency
    python_code = (
        "# 🐍 UTF-8 Comment with emojis and accents: é, à, ü\r\n"
        "class Alpha:\r\n"
        '    """Multi-line\r\n'
        "    docstring.\r\n"
        '    """\r\n'
        "    x = 1\r\n"
        "\r\n"
        "    def beta(self) -> None:\r\n"
        "        def gamma(): pass\r\n"
        "        gamma()\r\n"
    )

    struct = parser.parse(python_code, language="python", file_path="alpha.py")

    # Invariants verification across all symbols
    for s in struct.symbols:
        assert s.location.start_line >= 1, f"start_line must be 1-indexed (got {s.location.start_line})"
        assert s.location.end_line >= s.location.start_line, "end_line must be >= start_line"
        assert s.location.start_column >= 0, f"start_column must be 0-indexed (got {s.location.start_column})"
        assert s.location.end_column >= 0, f"end_column must be 0-indexed (got {s.location.end_column})"
        if s.location.start_line == s.location.end_line:
            assert s.location.start_column <= s.location.end_column

    # Check Alpha class (starts at line 2)
    alpha = next(s for s in struct.symbols if s.name == "Alpha")
    assert alpha.location.start_line == 2
    assert alpha.location.start_column == 0
    assert alpha.location.end_line >= 10

    # Check beta method (nested under Alpha, line 8)
    beta = next(s for s in struct.symbols if s.name == "beta")
    assert beta.location.start_line == 8
    assert beta.parent_name == "Alpha"

    # Check gamma (nested under beta, single-line at line 9)
    gamma = next(s for s in struct.symbols if s.name == "gamma")
    assert gamma.location.start_line == 9
    assert gamma.location.end_line == 9
    assert gamma.location.start_column < gamma.location.end_column
    assert gamma.parent_name == "Alpha.beta"

    # Check single-line variable x
    x_sym = next(s for s in struct.symbols if s.name == "x")
    assert x_sym.location.start_line == 6
    assert x_sym.location.end_line == 6
