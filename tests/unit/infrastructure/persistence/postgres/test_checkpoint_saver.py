import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.base import Checkpoint

from app.infrastructure.persistence.postgres.checkpoint_saver import (
    CheckpointModel,
    PostgresCheckpointSaver,
)


@pytest.mark.asyncio
async def test_checkpoint_saver_aput():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    saver = PostgresCheckpointSaver(mock_session)

    config = {"configurable": {"thread_id": "t-123", "checkpoint_id": "c-parent"}}
    checkpoint: Checkpoint = {
        "v": 1,
        "id": "c-456",
        "ts": "2026-09-10T12:00:00Z",
        "channel_values": {"msg": "hello"},
        "channel_versions": {"msg": 1},
        "versions_seen": {},
    }
    metadata = {"source": "input", "step": 1}
    new_versions = {"msg": 1}

    res_config = await saver.aput(config, checkpoint, metadata, new_versions)

    assert res_config["configurable"]["thread_id"] == "t-123"
    assert res_config["configurable"]["checkpoint_id"] == "c-456"
    assert mock_session.add.called
    added_model = mock_session.add.call_args[0][0]
    assert isinstance(added_model, CheckpointModel)
    assert added_model.thread_id == "t-123"
    assert added_model.checkpoint_id == "c-456"
    assert added_model.parent_checkpoint_id == "c-parent"
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_checkpoint_saver_aget_tuple():
    mock_session = AsyncMock()
    saver = PostgresCheckpointSaver(mock_session)

    type_c, bytes_c = saver.serde.dumps_typed(
        {
            "v": 1,
            "id": "c-456",
            "ts": "2026-09-10T12:00:00Z",
            "channel_values": {"msg": "hello"},
            "channel_versions": {"msg": 1},
            "versions_seen": {},
        }
    )
    type_m, bytes_m = saver.serde.dumps_typed({"step": 1})
    payload = {
        "checkpoint": {"type": type_c, "data": bytes_c.hex()},
        "metadata": {"type": type_m, "data": bytes_m.hex()},
    }

    mock_row = MagicMock(spec=CheckpointModel)
    mock_row.thread_id = "t-123"
    mock_row.checkpoint_id = "c-456"
    mock_row.parent_checkpoint_id = "c-parent"
    mock_row.checkpoint_data = json.dumps(payload)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_row
    mock_session.execute.return_value = mock_result

    config = {"configurable": {"thread_id": "t-123", "checkpoint_id": "c-456"}}
    tuple_res = await saver.aget_tuple(config)

    assert tuple_res is not None
    assert tuple_res.checkpoint["id"] == "c-456"
    assert tuple_res.checkpoint["channel_values"] == {"msg": "hello"}
    assert tuple_res.metadata == {"step": 1}
    assert tuple_res.parent_config == {"configurable": {"thread_id": "t-123", "checkpoint_id": "c-parent"}}
