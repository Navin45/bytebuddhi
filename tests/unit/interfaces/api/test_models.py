"""Model catalog API returns safe metadata only."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.llm.catalog import StaticModelCatalog
from app.application.ports.output.llm.model_gateway import ModelCapability, ModelDescriptor, ModelRef
from app.domain.models.user import User
from app.interfaces.api.dependencies import get_model_catalog
from app.interfaces.api.main import app
from app.interfaces.api.middleware import get_current_user


@pytest.mark.asyncio
async def test_models_catalog_hides_credentials_and_endpoints() -> None:
    catalog = StaticModelCatalog(
        [
            ModelDescriptor(
                provider="openai",
                model="gpt-test",
                display_name="OpenAI gpt-test",
                capabilities=(ModelCapability.CHAT, ModelCapability.TOOL_CALLING),
                available=True,
            )
        ],
        ModelRef("openai", "gpt-test"),
    )
    user = User(
        id=uuid4(),
        email="models@example.com",
        username="models",
        password_hash="hash",
        created_at=None,
        updated_at=None,
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_model_catalog] = lambda: catalog
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/models")
        assert response.status_code == 200
        payload = response.json()
        assert payload["default_provider"] == "openai"
        assert payload["default_model"] == "gpt-test"
        assert payload["models"][0]["available"] is True
        blob = response.text.lower()
        assert "api_key" not in blob
        assert "sk-" not in blob
        assert "base_url" not in blob
        assert "authorization" not in blob
    finally:
        app.dependency_overrides.clear()
