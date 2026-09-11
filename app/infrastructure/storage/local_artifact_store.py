"""Local filesystem implementation of ArtifactStore using aiofiles."""

from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

from app.application.ports.output.observability.tracer import Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.domain.models.observability import SpanAttributes, SpanNames
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import NoOpTracer

logger = get_logger(__name__)


class LocalArtifactStore(ArtifactStore):
    """Stores execution logs, command outputs, and artifacts on the local filesystem."""

    def __init__(self, base_dir: str | Path = "./storage/artifacts", tracer: Tracer | None = None):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tracer = tracer or NoOpTracer()

    def _get_path(self, artifact_id: str) -> Path:
        # Sanitize artifact_id to avoid traversal within artifact storage
        safe_name = Path(artifact_id).name
        return self.base_dir / safe_name

    async def save_artifact(
        self,
        artifact_id: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save artifact content to the local filesystem."""
        with self.tracer.start_as_current_span(
            SpanNames.ARTIFACT_STORE,
            attributes={
                SpanAttributes.ARTIFACT_ID: artifact_id,
                SpanAttributes.ARTIFACT_SIZE_BYTES: len(content),
            },
        ):
            path = self._get_path(artifact_id)
            try:
                if isinstance(content, bytes):
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                else:
                    async with aiofiles.open(path, "w", encoding="utf-8") as f:
                        await f.write(content)

                logger.info("Artifact saved to local storage", artifact_id=artifact_id, path=str(path))
                return str(path)
            except Exception as e:
                logger.error("Failed to save artifact", artifact_id=artifact_id, error=str(e))
                raise

    async def get_artifact(self, artifact_id: str) -> str | bytes | None:
        """Retrieve artifact content from the local filesystem."""
        with self.tracer.start_as_current_span(
            SpanNames.ARTIFACT_GET,
            attributes={
                SpanAttributes.ARTIFACT_ID: artifact_id,
            },
        ):
            path = self._get_path(artifact_id)
            if not path.exists():
                return None

            try:
                # Attempt to read as text, fallback to binary if decoding fails
                async with aiofiles.open(path, "rb") as f:
                    data = await f.read()
                    raw_bytes = bytes(data) if not isinstance(data, bytes) else data

                try:
                    return raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return raw_bytes
            except Exception as e:
                logger.error("Failed to read artifact", artifact_id=artifact_id, error=str(e))
                raise

    async def delete_artifact(self, artifact_id: str) -> bool:
        """Delete artifact from the local filesystem."""
        path = self._get_path(artifact_id)
        if not path.exists():
            return False

        try:
            await aiofiles.os.remove(path)
            logger.info("Artifact deleted", artifact_id=artifact_id)
            return True
        except Exception as e:
            logger.error("Failed to delete artifact", artifact_id=artifact_id, error=str(e))
            raise

    async def artifact_exists(self, artifact_id: str) -> bool:
        """Check if artifact exists on the local filesystem."""
        path = self._get_path(artifact_id)
        return path.exists()
