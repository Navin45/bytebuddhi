"""Python AST symbol and relationship extractor using Tree-sitter."""

from typing import Any

from app.domain.models.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    Symbol,
    SymbolKind,
    SyntaxDiagnostic,
)
from app.infrastructure.parser.extractors.base import BaseLanguageExtractor


class PythonLanguageExtractor(BaseLanguageExtractor):
    """Extracts symbols, inheritance, imports, and calls from Python AST."""

    def __init__(self) -> None:
        super().__init__(language_name="python")

    def extract(
        self,
        root_node: Any,
        source_bytes: bytes,
        file_path: str,
        max_symbols: int = 500,
        max_relations: int = 1000,
    ) -> tuple[list[Symbol], list[CodeRelation], list[SyntaxDiagnostic]]:
        symbols: list[Symbol] = []
        relations: list[CodeRelation] = []
        diagnostics = self.find_syntax_diagnostics(root_node, file_path)

        def add_symbol(sym: Symbol) -> bool:
            if len(symbols) < max_symbols:
                symbols.append(sym)
                return True
            return False

        def add_relation(rel: CodeRelation) -> bool:
            if len(relations) < max_relations:
                relations.append(rel)
                return True
            return False

        def extract_docstring(body_node: Any) -> str | None:
            if not body_node:
                return None
            for child in body_node.children:
                if child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "string":
                            text = self.node_text(sub, source_bytes)
                            # Strip quotes
                            for q in ('"""', "'''", '"', "'"):
                                if text.startswith(q) and text.endswith(q) and len(text) >= 2 * len(q):
                                    return text[len(q) : -len(q)].strip()
                            return text.strip()
                elif child.is_named:
                    break
            return None

        def extract_calls(body_node: Any, caller_name: str) -> None:
            if not body_node:
                return
            stack = list(reversed(body_node.children))
            while stack:
                curr = stack.pop()
                if curr.type == "call":
                    func_node = curr.child_by_field_name("function")
                    if func_node:
                        call_target = self.node_text(func_node, source_bytes)
                        if call_target:
                            add_relation(
                                CodeRelation(
                                    source_name=caller_name,
                                    target_name=call_target,
                                    relation_type=CodeRelationType.CALLS,
                                    location=self.node_location(curr, file_path),
                                    is_syntactic=True,
                                )
                            )
                # Don't descend into nested function or class definitions
                if curr.type not in ("function_definition", "class_definition"):
                    stack.extend(reversed(curr.children))

        def extract_function(
            fn_node: Any,
            parent_name: str | None = None,
            decorators: list[str] | None = None,
        ) -> None:
            name_node = fn_node.child_by_field_name("name")
            if not name_node:
                return
            name = self.node_text(name_node, source_bytes)
            qualified_name = f"{parent_name}.{name}" if parent_name else name
            kind = SymbolKind.METHOD if parent_name else SymbolKind.FUNCTION
            loc = self.node_location(fn_node, file_path)

            params_node = fn_node.child_by_field_name("parameters")
            params_str = self.node_text(params_node, source_bytes) if params_node else "()"
            ret_node = fn_node.child_by_field_name("return_type")
            ret_str = f" -> {self.node_text(ret_node, source_bytes)}" if ret_node else ""
            signature = f"def {name}{params_str}{ret_str}"

            body_node = fn_node.child_by_field_name("body")
            doc = extract_docstring(body_node)

            metadata: dict[str, Any] = {}
            if decorators:
                metadata["decorators"] = decorators

            sym = Symbol(
                id=f"{file_path}::{qualified_name}",
                name=name,
                qualified_name=qualified_name,
                kind=kind,
                location=loc,
                language=self.language_name,
                signature=signature,
                docstring=doc,
                parent_name=parent_name,
                metadata=metadata,
            )
            add_symbol(sym)
            extract_calls(body_node, qualified_name)

            # Check nested definitions
            if body_node:
                for child in body_node.children:
                    if child.type == "function_definition":
                        extract_function(child, parent_name=qualified_name)
                    elif child.type == "class_definition":
                        extract_class(child, parent_name=qualified_name)

        def extract_class(
            class_node: Any,
            parent_name: str | None = None,
            decorators: list[str] | None = None,
        ) -> None:
            name_node = class_node.child_by_field_name("name")
            if not name_node:
                return
            name = self.node_text(name_node, source_bytes)
            qualified_name = f"{parent_name}.{name}" if parent_name else name
            loc = self.node_location(class_node, file_path)

            body_node = class_node.child_by_field_name("body")
            doc = extract_docstring(body_node)

            # Superclasses / Inheritance
            bases: list[str] = []
            super_node = class_node.child_by_field_name("superclasses")
            if super_node:
                for arg in super_node.children:
                    if arg.is_named:
                        base_name = self.node_text(arg, source_bytes)
                        if base_name:
                            bases.append(base_name)
                            add_relation(
                                CodeRelation(
                                    source_name=qualified_name,
                                    target_name=base_name,
                                    relation_type=CodeRelationType.INHERITS,
                                    location=self.node_location(arg, file_path),
                                    is_syntactic=True,
                                )
                            )

            metadata: dict[str, Any] = {"bases": bases}
            if decorators:
                metadata["decorators"] = decorators

            sym = Symbol(
                id=f"{file_path}::{qualified_name}",
                name=name,
                qualified_name=qualified_name,
                kind=SymbolKind.CLASS,
                location=loc,
                language=self.language_name,
                signature=f"class {name}" + (f"({', '.join(bases)})" if bases else ""),
                docstring=doc,
                parent_name=parent_name,
                metadata=metadata,
            )
            add_symbol(sym)

            # Process class body items
            if body_node:
                pending_decorators: list[str] = []
                for child in body_node.children:
                    if child.type == "decorator":
                        pending_decorators.append(self.node_text(child, source_bytes))
                    elif child.type == "decorated_definition":
                        decs = [self.node_text(c, source_bytes) for c in child.children if c.type == "decorator"]
                        def_node = next(
                            (c for c in child.children if c.type in ("function_definition", "class_definition")), None
                        )
                        if def_node:
                            if def_node.type == "function_definition":
                                extract_function(def_node, parent_name=qualified_name, decorators=decs)
                            elif def_node.type == "class_definition":
                                extract_class(def_node, parent_name=qualified_name, decorators=decs)
                    elif child.type == "function_definition":
                        extract_function(child, parent_name=qualified_name, decorators=pending_decorators or None)
                        pending_decorators = []
                    elif child.type == "class_definition":
                        extract_class(child, parent_name=qualified_name, decorators=pending_decorators or None)
                        pending_decorators = []
                    elif child.type == "expression_statement":
                        # Detect assignments like attr = val
                        assign_node = next(
                            (c for c in child.children if c.type in ("assignment", "augmented_assignment")), None
                        )
                        if assign_node:
                            left = assign_node.child_by_field_name("left")
                            if left and left.type == "identifier":
                                attr_name = self.node_text(left, source_bytes)
                                kind = SymbolKind.CONSTANT if attr_name.isupper() else SymbolKind.VARIABLE
                                add_symbol(
                                    Symbol(
                                        id=f"{file_path}::{qualified_name}.{attr_name}",
                                        name=attr_name,
                                        qualified_name=f"{qualified_name}.{attr_name}",
                                        kind=kind,
                                        location=self.node_location(assign_node, file_path),
                                        language=self.language_name,
                                        parent_name=qualified_name,
                                    )
                                )

        def process_node(child: Any) -> None:
            if child.type == "ERROR":
                for sub in child.children:
                    process_node(sub)
                return

            if child.type == "decorated_definition":
                decs = [self.node_text(c, source_bytes) for c in child.children if c.type == "decorator"]
                target = next(
                    (c for c in child.children if c.type in ("function_definition", "class_definition")), None
                )
                if target:
                    if target.type == "function_definition":
                        extract_function(target, decorators=decs)
                    elif target.type == "class_definition":
                        extract_class(target, decorators=decs)

            elif child.type == "class_definition":
                extract_class(child)

            elif child.type == "function_definition":
                extract_function(child)

            elif child.type == "import_statement":
                for name_node in child.children:
                    if name_node.type in ("dotted_name", "aliased_import"):
                        imp_name = self.node_text(name_node, source_bytes)
                        add_symbol(
                            Symbol(
                                id=f"{file_path}::{imp_name}",
                                name=imp_name,
                                qualified_name=imp_name,
                                kind=SymbolKind.IMPORT,
                                location=self.node_location(name_node, file_path),
                                language=self.language_name,
                            )
                        )
                        add_relation(
                            CodeRelation(
                                source_name=file_path,
                                target_name=imp_name,
                                relation_type=CodeRelationType.IMPORTS,
                                location=self.node_location(name_node, file_path),
                                is_syntactic=True,
                            )
                        )

            elif child.type == "import_from_statement":
                module_node = child.child_by_field_name("module_name")
                module_str = self.node_text(module_node, source_bytes) if module_node else ""
                for imp_child in child.children:
                    if imp_child.type in ("dotted_name", "aliased_import"):
                        imp_name = self.node_text(imp_child, source_bytes)
                        full_target = f"{module_str}.{imp_name}" if module_str else imp_name
                        add_symbol(
                            Symbol(
                                id=f"{file_path}::{imp_name}",
                                name=imp_name,
                                qualified_name=full_target,
                                kind=SymbolKind.IMPORT,
                                location=self.node_location(imp_child, file_path),
                                language=self.language_name,
                            )
                        )
                        add_relation(
                            CodeRelation(
                                source_name=file_path,
                                target_name=full_target,
                                relation_type=CodeRelationType.IMPORTS,
                                location=self.node_location(imp_child, file_path),
                                is_syntactic=True,
                            )
                        )

            elif child.type == "expression_statement":
                assign_node = next(
                    (c for c in child.children if c.type in ("assignment", "augmented_assignment")), None
                )
                if assign_node:
                    left = assign_node.child_by_field_name("left")
                    if left and left.type == "identifier":
                        var_name = self.node_text(left, source_bytes)
                        kind = SymbolKind.CONSTANT if var_name.isupper() else SymbolKind.VARIABLE
                        add_symbol(
                            Symbol(
                                id=f"{file_path}::{var_name}",
                                name=var_name,
                                qualified_name=var_name,
                                kind=kind,
                                location=self.node_location(assign_node, file_path),
                                language=self.language_name,
                            )
                        )

        # Top-level traversal
        for child in root_node.children:
            process_node(child)

        return symbols, relations, diagnostics
