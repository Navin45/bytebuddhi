"""Tool registry for registering and discovering agent capabilities."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.ports.output.logger import get_logger
from app.application.tools.definition import CapabilityType, RiskLevel, ToolDefinition

logger = get_logger(__name__)

ToolHandler = Callable[..., Awaitable[Any]] | Callable[..., Any]


class ToolRegistry:
    """Central registry of tools and capabilities available to agents."""

    def __init__(self) -> None:
        # Maps LLM-facing tool name -> (ToolDefinition, ToolHandler)
        self._tools_by_name: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        # Maps namespaced capability ID -> tool name
        self._id_to_name: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._tools_by_name)

    def __contains__(self, name_or_id: str) -> bool:
        return self.has(name_or_id)

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        allow_override: bool = False,
    ) -> None:
        """Register a capability with collision detection.

        Args:
            definition: The tool/capability definition including schema.
            handler: Callable function or coroutine implementing the tool.
            allow_override: If True, overwrite existing tool with same name without raising.

        Raises:
            ValueError: If a capability is already registered with the same name and allow_override is False.
        """
        cap_id = definition.id or f"{definition.capability_type.value}.{definition.name}"

        if cap_id in self._id_to_name and self._id_to_name[cap_id] != definition.name:
            existing_name = self._id_to_name[cap_id]
            raise ValueError(
                f"Capability id '{cap_id}' is already registered under name '{existing_name}', "
                "cannot register a second tool with the same id"
            )

        # Check for name collision
        if definition.name in self._tools_by_name:
            if not allow_override:
                existing_def, _ = self._tools_by_name[definition.name]
                raise ValueError(
                    f"Capability '{definition.name}' is already registered "
                    f"under id '{existing_def.id}', cannot register without allow_override"
                )
            # If overriding, clean up old id mapping if changed
            old_def, _ = self._tools_by_name[definition.name]
            if old_def.id and old_def.id in self._id_to_name:
                self._id_to_name.pop(old_def.id, None)

        self._tools_by_name[definition.name] = (definition, handler)
        self._id_to_name[cap_id] = definition.name

    def unregister(self, name_or_id: str) -> bool:
        """Unregister a tool by its name or namespaced ID.

        Returns:
            bool: True if removed, False if not found.
        """
        target_name = name_or_id
        if name_or_id in self._id_to_name:
            target_name = self._id_to_name.pop(name_or_id)

        entry = self._tools_by_name.pop(target_name, None)
        if entry:
            defn, _ = entry
            if defn.id in self._id_to_name:
                self._id_to_name.pop(defn.id, None)
            return True
        return False

    def get(self, name_or_id: str) -> tuple[ToolDefinition, ToolHandler] | None:
        """Look up a capability by name or namespaced ID."""
        target_name = self._id_to_name.get(name_or_id, name_or_id)
        return self._tools_by_name.get(target_name)

    def get_by_id(self, cap_id: str) -> tuple[ToolDefinition, ToolHandler] | None:
        """Look up a capability explicitly by its namespaced ID."""
        return self.get(cap_id)

    def has(self, name_or_id: str) -> bool:
        """Check if a capability is registered by name or namespaced ID."""
        return name_or_id in self._tools_by_name or name_or_id in self._id_to_name

    def list_definitions(
        self,
        capability_type: CapabilityType | None = None,
        risk_level: RiskLevel | None = None,
    ) -> list[ToolDefinition]:
        """List registered capability definitions with optional filtering."""
        results = []
        for defn, _ in self._tools_by_name.values():
            if capability_type is not None and defn.capability_type != capability_type:
                continue
            if risk_level is not None and defn.risk_level != risk_level:
                continue
            results.append(defn)
        return results

    def list_capabilities(
        self,
        capability_type: CapabilityType | None = None,
        risk_level: RiskLevel | None = None,
    ) -> list[ToolDefinition]:
        """Alias for list_definitions matching capability nomenclature."""
        return self.list_definitions(capability_type=capability_type, risk_level=risk_level)

    def search(
        self,
        query: str = "",
        capability_type: CapabilityType | None = None,
        risk_level: RiskLevel | None = None,
    ) -> list[ToolDefinition]:
        """Search registered capabilities matching query and/or capability type and risk level."""
        q_lower = query.strip().lower()
        results: list[ToolDefinition] = []

        for defn, _ in self._tools_by_name.values():
            if capability_type is not None and defn.capability_type != capability_type:
                continue
            if risk_level is not None and defn.risk_level != risk_level:
                continue
            if q_lower:
                match_name = q_lower in defn.name.lower()
                match_id = q_lower in (defn.id or "").lower()
                match_desc = q_lower in defn.description.lower()
                if not (match_name or match_id or match_desc):
                    continue
            results.append(defn)

        return results

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Canonical tool schemas consumed by ModelGateway adapters."""
        return [defn.to_openai_schema() for defn, _ in self._tools_by_name.values()]

    def get_schemas_for_openai(self) -> list[dict[str, Any]]:
        """Compatibility alias for get_tool_schemas()."""
        return self.get_tool_schemas()

    def get_schemas_for_anthropic(self) -> list[dict[str, Any]]:
        """Get tool schemas formatted for Anthropic tool use."""
        return [defn.to_anthropic_schema() for defn, _ in self._tools_by_name.values()]


# Canonical alias
CapabilityRegistry = ToolRegistry
