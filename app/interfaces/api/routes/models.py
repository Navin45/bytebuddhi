"""Safe model catalog API. Credentials and endpoints are never returned."""

from fastapi import APIRouter, Depends

from app.application.ports.output.llm.model_catalog import ModelCatalog
from app.domain.models.user import User
from app.interfaces.api.dependencies import get_model_catalog
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.model_schema import ModelCatalogResponse, ModelDescriptorResponse

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("", response_model=ModelCatalogResponse)
async def list_models(
    current_user: User = Depends(get_current_user),
    catalog: ModelCatalog = Depends(get_model_catalog),
) -> ModelCatalogResponse:
    default = catalog.default_ref()
    return ModelCatalogResponse(
        default_provider=default.provider,
        default_model=default.model,
        models=[
            ModelDescriptorResponse(
                provider=item.provider,
                model=item.model,
                display_name=item.display_name,
                capabilities=[cap.value for cap in item.capabilities],
                available=item.available,
            )
            for item in catalog.list_models()
        ],
    )
