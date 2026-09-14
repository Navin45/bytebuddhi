"""Model catalog and provider registry ports."""

from typing import Protocol, runtime_checkable

from app.application.ports.output.llm.model_gateway import ModelDescriptor, ModelGateway, ModelRef


@runtime_checkable
class ModelCatalog(Protocol):
    """Authoritative list of selectable models. Does not hold credentials."""

    def default_ref(self) -> ModelRef:
        """Configured default model. Not a silent failover target."""
        ...

    def list_models(self) -> list[ModelDescriptor]:
        """Registered models for enabled providers, including unavailable entries."""
        ...

    def resolve(self, provider: str | None, model: str | None) -> ModelDescriptor:
        """Resolve a selection. None/None uses the default. No silent substitution."""
        ...


@runtime_checkable
class ProviderRegistry(Protocol):
    """Maps provider ids to adapters. Adding a provider is a localized registration."""

    def get(self, provider_id: str) -> ModelGateway: ...

    def registered_ids(self) -> list[str]: ...
