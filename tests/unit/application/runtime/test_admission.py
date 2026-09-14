"""Per-user concurrent run admission."""

from uuid import uuid4

import pytest

from app.application.runtime.admission import ConcurrentRunLimitExceeded, RunAdmissionController


@pytest.mark.asyncio
async def test_admission_rejects_over_limit() -> None:
    controller = RunAdmissionController(max_per_user=1)
    user = uuid4()
    await controller.acquire(user)
    with pytest.raises(ConcurrentRunLimitExceeded):
        await controller.acquire(user)
    await controller.release(user)
    await controller.acquire(user)
    await controller.release(user)


@pytest.mark.asyncio
async def test_admission_isolates_users() -> None:
    controller = RunAdmissionController(max_per_user=1)
    a = uuid4()
    b = uuid4()
    await controller.acquire(a)
    await controller.acquire(b)
    assert controller.active_for(a) == 1
    assert controller.active_for(b) == 1
    await controller.release(a)
    await controller.release(b)
