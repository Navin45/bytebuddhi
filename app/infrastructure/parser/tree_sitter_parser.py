"""Tree-sitter implementation of CodeParser port."""

import hashlib

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from app.application.ports.output.code.code_parser import CodeParser
from app.domain.models.code_intelligence import (
    CodeStructure,
    SourceLocation,
    SyntaxDiagnostic,
)
from app.infrastructure.config.logger import get_logger
from app.infrastructure.parser.extractors.base import BaseLanguageExtractor
from app.infrastructure.parser.extractors.python_extractor import PythonLanguageExtractor
from app.infrastructure.parser.extractors.ts_js_extractor import (
    TypeScriptJavaScriptExtractor,
)

logger = get_logger(__name__)


class TreeSitterCodeParser(CodeParser):
    """Parses source files using Tree-sitter into normalized CodeStructure."""

    def __init__(self, max_symbols: int = 500, max_relations: int = 1000) -> None:
        self.max_symbols = max_symbols
        self.max_relations = max_relations
        self._parsers: dict[str, Parser] = {}
        self._extractors: dict[str, BaseLanguageExtractor] = {}
        self._initialize_languages()

    def _initialize_languages(self) -> None:
        """Initialize language grammars and parser instances."""
        try:
            # Python
            py_lang = Language(tspy.language())
            self._parsers["python"] = Parser(py_lang)
            self._extractors["python"] = PythonLanguageExtractor()

            # JavaScript
            js_lang = Language(tsjs.language())
            self._parsers["javascript"] = Parser(js_lang)
            self._extractors["javascript"] = TypeScriptJavaScriptExtractor("javascript")

            # TypeScript
            ts_lang = Language(tsts.language_typescript())
            self._parsers["typescript"] = Parser(ts_lang)
            self._extractors["typescript"] = TypeScriptJavaScriptExtractor("typescript")

            # TSX
            tsx_lang = Language(tsts.language_tsx())
            self._parsers["tsx"] = Parser(tsx_lang)
            self._extractors["tsx"] = TypeScriptJavaScriptExtractor("tsx")

        except Exception as e:
            logger.error("Failed to initialize Tree-sitter languages", error=str(e))
            raise

    def supported_languages(self) -> list[str]:
        """Return list of supported languages."""
        return list(self._parsers.keys())

    def can_parse(self, language: str) -> bool:
        """Return True if the language is supported."""
        return language.lower().strip() in self._parsers

    def parse(
        self,
        content: str | bytes,
        language: str,
        file_path: str = "",
    ) -> CodeStructure:
        """Parse source code into normalized CodeStructure."""
        lang_key = language.lower().strip()
        source_bytes = content.encode("utf-8") if isinstance(content, str) else content
        content_hash = hashlib.sha256(source_bytes).hexdigest()
        total_lines = len(source_bytes.split(b"\n")) if source_bytes else 0

        if not self.can_parse(lang_key):
            diag = SyntaxDiagnostic(
                message=f"Unsupported language '{language}' for Tree-sitter parsing",
                location=SourceLocation(
                    file_path=file_path,
                    start_line=1,
                    start_column=0,
                    end_line=max(1, total_lines),
                    end_column=0,
                ),
                severity="warning",
            )
            return CodeStructure(
                file_path=file_path,
                language=language,
                content_hash=content_hash,
                diagnostics=[diag],
                total_lines=total_lines,
            )

        parser = self._parsers[lang_key]
        extractor = self._extractors[lang_key]

        try:
            tree = parser.parse(source_bytes)
            symbols, relations, diagnostics = extractor.extract(
                root_node=tree.root_node,
                source_bytes=source_bytes,
                file_path=file_path,
                max_symbols=self.max_symbols,
                max_relations=self.max_relations,
            )
            return CodeStructure(
                file_path=file_path,
                language=lang_key,
                content_hash=content_hash,
                symbols=symbols,
                relationships=relations,
                diagnostics=diagnostics,
                total_lines=total_lines,
            )
        except Exception as e:
            logger.warning("Tree-sitter parser exception on source file", file=file_path, error=str(e))
            diag = SyntaxDiagnostic(
                message=f"Parser exception: {e!s}",
                location=SourceLocation(
                    file_path=file_path,
                    start_line=1,
                    start_column=0,
                    end_line=max(1, total_lines),
                    end_column=0,
                ),
                severity="error",
            )
            return CodeStructure(
                file_path=file_path,
                language=lang_key,
                content_hash=content_hash,
                diagnostics=[diag],
                total_lines=total_lines,
            )
