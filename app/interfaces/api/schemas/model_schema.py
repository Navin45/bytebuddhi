"""Model catalog response schemas. No credentials or endpoints."""

from pydantic import BaseModel, Field


class ModelDescriptorResponse(BaseModel):
    provider: str
    model: str
    display_name: str
    capabilities: list[str] = Field(default_factory=list)
    available: bool = False


class ModelCatalogResponse(BaseModel):
    default_provider: str
    default_model: str
    models: list[ModelDescriptorResponse]
