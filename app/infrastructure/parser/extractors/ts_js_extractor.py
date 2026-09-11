"""JavaScript and TypeScript AST symbol and relationship extractor using Tree-sitter."""

from typing import Any

from app.domain.models.code_intelligence import (
    CodeRelation,
    CodeRelationType,
    Symbol,
    SymbolKind,
    SyntaxDiagnostic,
)
from app.infrastructure.parser.extractors.base import BaseLanguageExtractor


class TypeScriptJavaScriptExtractor(BaseLanguageExtractor):
    """Extracts symbols, inheritance, interfaces, imports, and calls from JS/TS/TSX AST."""

    def __init__(self, language_name: str = "typescript") -> None:
        super().__init__(language_name=language_name)

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

        def extract_calls(body_node: Any, caller_name: str) -> None:
            if not body_node:
                return
            stack = list(reversed(body_node.children))
            while stack:
                curr = stack.pop()
                if curr.type == "call_expression":
                    fn_node = curr.child_by_field_name("function")
                    if fn_node:
                        call_target = self.node_text(fn_node, source_bytes)
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
                if curr.type not in ("function_declaration", "class_declaration", "arrow_function"):
                    stack.extend(reversed(curr.children))

        def extract_function(
            fn_node: Any,
            parent_name: str | None = None,
            explicit_name: str | None = None,
        ) -> None:
            name_node = fn_node.child_by_field_name("name")
            name = explicit_name or (self.node_text(name_node, source_bytes) if name_node else "")
            if not name:
                return

            qualified_name = f"{parent_name}.{name}" if parent_name else name
            kind = SymbolKind.METHOD if parent_name else SymbolKind.FUNCTION
            loc = self.node_location(fn_node, file_path)

            params_node = fn_node.child_by_field_name("parameters")
            params_str = self.node_text(params_node, source_bytes) if params_node else "()"
            ret_node = fn_node.child_by_field_name("return_type")
            ret_str = f": {self.node_text(ret_node, source_bytes)}" if ret_node else ""
            signature = f"function {name}{params_str}{ret_str}"

            sym = Symbol(
                id=f"{file_path}::{qualified_name}",
                name=name,
                qualified_name=qualified_name,
                kind=kind,
                location=loc,
                language=self.language_name,
                signature=signature,
                parent_name=parent_name,
            )
            add_symbol(sym)
            body_node = fn_node.child_by_field_name("body")
            extract_calls(body_node, qualified_name)

        def extract_class(class_node: Any, parent_name: str | None = None) -> None:
            name_node = class_node.child_by_field_name("name")
            if not name_node:
                return
            name = self.node_text(name_node, source_bytes)
            qualified_name = f"{parent_name}.{name}" if parent_name else name
            loc = self.node_location(class_node, file_path)

            bases: list[str] = []
            heritage = next((c for c in class_node.children if c.type in ("class_heritage", "extends_clause")), None)
            if heritage:
                for child in heritage.children:
                    if child.type in ("extends_clause", "implements_clause"):
                        for sub in child.children:
                            if sub.is_named and sub.type not in ("extends", "implements"):
                                base_name = self.node_text(sub, source_bytes)
                                if base_name:
                                    bases.append(base_name)
                                    add_relation(
                                        CodeRelation(
                                            source_name=qualified_name,
                                            target_name=base_name,
                                            relation_type=CodeRelationType.INHERITS,
                                            location=self.node_location(sub, file_path),
                                            is_syntactic=True,
                                        )
                                    )

            sym = Symbol(
                id=f"{file_path}::{qualified_name}",
                name=name,
                qualified_name=qualified_name,
                kind=SymbolKind.CLASS,
                location=loc,
                language=self.language_name,
                signature=f"class {name}" + (f" extends {', '.join(bases)}" if bases else ""),
                parent_name=parent_name,
                metadata={"bases": bases},
            )
            add_symbol(sym)

            body_node = class_node.child_by_field_name("body")
            if body_node:
                for child in body_node.children:
                    if child.type == "method_definition":
                        m_name_node = child.child_by_field_name("name")
                        if m_name_node:
                            m_name = self.node_text(m_name_node, source_bytes)
                            m_qual = f"{qualified_name}.{m_name}"
                            m_loc = self.node_location(child, file_path)
                            m_params = child.child_by_field_name("parameters")
                            p_str = self.node_text(m_params, source_bytes) if m_params else "()"
                            m_ret = child.child_by_field_name("return_type")
                            r_str = f": {self.node_text(m_ret, source_bytes)}" if m_ret else ""
                            m_sig = f"{m_name}{p_str}{r_str}"
                            add_symbol(
                                Symbol(
                                    id=f"{file_path}::{m_qual}",
                                    name=m_name,
                                    qualified_name=m_qual,
                                    kind=SymbolKind.METHOD,
                                    location=m_loc,
                                    language=self.language_name,
                                    signature=m_sig,
                                    parent_name=qualified_name,
                                )
                            )
                            extract_calls(child.child_by_field_name("body"), m_qual)

        def extract_interface(iface_node: Any) -> None:
            name_node = iface_node.child_by_field_name("name")
            if not name_node:
                return
            name = self.node_text(name_node, source_bytes)
            loc = self.node_location(iface_node, file_path)

            bases: list[str] = []
            extends_node = next((c for c in iface_node.children if c.type == "extends_type_clause"), None)
            if extends_node:
                for sub in extends_node.children:
                    if sub.is_named and sub.type != "extends":
                        b_name = self.node_text(sub, source_bytes)
                        if b_name:
                            bases.append(b_name)
                            add_relation(
                                CodeRelation(
                                    source_name=name,
                                    target_name=b_name,
                                    relation_type=CodeRelationType.INHERITS,
                                    location=self.node_location(sub, file_path),
                                    is_syntactic=True,
                                )
                            )

            sym = Symbol(
                id=f"{file_path}::{name}",
                name=name,
                qualified_name=name,
                kind=SymbolKind.INTERFACE,
                location=loc,
                language=self.language_name,
                signature=f"interface {name}" + (f" extends {', '.join(bases)}" if bases else ""),
                metadata={"bases": bases},
            )
            add_symbol(sym)

        def extract_type_alias(type_node: Any) -> None:
            name_node = type_node.child_by_field_name("name")
            if not name_node:
                return
            name = self.node_text(name_node, source_bytes)
            loc = self.node_location(type_node, file_path)
            sym = Symbol(
                id=f"{file_path}::{name}",
                name=name,
                qualified_name=name,
                kind=SymbolKind.TYPE_ALIAS,
                location=loc,
                language=self.language_name,
                signature=f"type {name}",
            )
            add_symbol(sym)

        # Top-level AST scan
        for child in root_node.children:
            # Unwrap export statements
            target_node = child
            if child.type in ("export_statement", "export_default_declaration"):
                decl = child.child_by_field_name("declaration")
                if decl:
                    target_node = decl

            if target_node.type == "class_declaration":
                extract_class(target_node)

            elif target_node.type in ("function_declaration", "generator_function_declaration"):
                extract_function(target_node)

            elif target_node.type == "interface_declaration":
                extract_interface(target_node)

            elif target_node.type == "type_alias_declaration":
                extract_type_alias(target_node)

            elif target_node.type in ("lexical_declaration", "variable_declaration"):
                for decl in target_node.children:
                    if decl.type == "variable_declarator":
                        name_node = decl.child_by_field_name("name")
                        val_node = decl.child_by_field_name("value")
                        if name_node:
                            var_name = self.node_text(name_node, source_bytes)
                            if val_node and val_node.type in ("arrow_function", "function_expression"):
                                extract_function(val_node, explicit_name=var_name)
                            else:
                                is_const = target_node.type == "lexical_declaration" and self.node_text(
                                    target_node, source_bytes
                                ).startswith("const")
                                kind = SymbolKind.CONSTANT if (is_const or var_name.isupper()) else SymbolKind.VARIABLE
                                add_symbol(
                                    Symbol(
                                        id=f"{file_path}::{var_name}",
                                        name=var_name,
                                        qualified_name=var_name,
                                        kind=kind,
                                        location=self.node_location(decl, file_path),
                                        language=self.language_name,
                                    )
                                )

            elif target_node.type == "import_statement":
                source_node = target_node.child_by_field_name("source")
                module_spec = self.node_text(source_node, source_bytes).strip("'\"") if source_node else ""
                clause_node = next(
                    (c for c in target_node.children if c.type in ("import_clause", "named_imports")), None
                )
                imported_items: list[str] = []
                if clause_node:
                    for sub in clause_node.children:
                        if sub.type == "identifier":
                            imported_items.append(self.node_text(sub, source_bytes))
                        elif sub.type == "named_imports":
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    s_name = spec.child_by_field_name("name")
                                    if s_name:
                                        imported_items.append(self.node_text(s_name, source_bytes))

                if not imported_items and module_spec:
                    imported_items.append(module_spec)

                for item in imported_items:
                    target_name = f"{module_spec}::{item}" if module_spec else item
                    add_symbol(
                        Symbol(
                            id=f"{file_path}::{item}",
                            name=item,
                            qualified_name=target_name,
                            kind=SymbolKind.IMPORT,
                            location=self.node_location(target_node, file_path),
                            language=self.language_name,
                        )
                    )
                    add_relation(
                        CodeRelation(
                            source_name=file_path,
                            target_name=target_name,
                            relation_type=CodeRelationType.IMPORTS,
                            location=self.node_location(target_node, file_path),
                            is_syntactic=True,
                        )
                    )

        return symbols, relations, diagnostics
