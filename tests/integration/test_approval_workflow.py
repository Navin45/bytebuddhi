"""Comprehensive end-to-end integration tests for authoritative tool approvals.

Tests approval lifecycle, user authorization boundary, rejection semantics,
timeouts, and edge cases (duplicate approval, post-completion resolution).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.application.runtime.approval import RunApprovalRegistry
from app.application.runtime.events import ExecutionEvent, ExecutionEventType


class MockEventSink:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def emit(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_approval_granted_flow() -> None:
    registry = RunApprovalRegistry()
    sink = MockEventSink()
    user_id = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    async def run_task() -> bool:
        return await registry.request_approval(
            sink=sink,
            run_id=run_id,
            user_id=user_id,
            action="delete_database",
            risk_level="high",
            reason="Destructive operation",
            timeout_seconds=5.0,
        )

    task = asyncio.create_task(run_task())
    await asyncio.sleep(0.05)

    # 1. Verify tool_approval_required event was emitted
    assert len(sink.events) == 1
    assert sink.events[0].type == ExecutionEventType.TOOL_APPROVAL_REQUIRED
    assert sink.events[0].payload["action"] == "delete_database"
    assert sink.events[0].payload["risk_level"] == "high"

    # 2. User approves
    resolved = await registry.resolve(
        run_id=run_id,
        user_id=user_id,
        action="delete_database",
        approved=True,
    )
    assert resolved is True

    # 3. Verify task resumes and returns True (approved)
    result = await task
    assert result is True

    # 4. Verify tool_approved event was emitted
    assert len(sink.events) == 2
    assert sink.events[1].type == ExecutionEventType.TOOL_APPROVED


@pytest.mark.asyncio
async def test_approval_rejected_flow() -> None:
    registry = RunApprovalRegistry()
    sink = MockEventSink()
    user_id = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    async def run_task() -> bool:
        return await registry.request_approval(
            sink=sink,
            run_id=run_id,
            user_id=user_id,
            action="drop_table",
            risk_level="critical",
            reason="Permanent loss of data",
            timeout_seconds=5.0,
        )

    task = asyncio.create_task(run_task())
    await asyncio.sleep(0.05)

    # User rejects
    resolved = await registry.resolve(
        run_id=run_id,
        user_id=user_id,
        action="drop_table",
        approved=False,
    )
    assert resolved is True

    # Verify task receives False (denied)
    result = await task
    assert result is False

    # Verify tool_rejected event was emitted
    assert sink.events[-1].type == ExecutionEventType.TOOL_REJECTED


@pytest.mark.asyncio
async def test_approval_timeout_flow() -> None:
    registry = RunApprovalRegistry()
    sink = MockEventSink()
    user_id = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    # Request approval with very short timeout
    result = await registry.request_approval(
        sink=sink,
        run_id=run_id,
        user_id=user_id,
        action="execute_shell_script",
        risk_level="high",
        reason="Needs quick response",
        timeout_seconds=0.1,
    )

    # Should time out and return False (fails closed)
    assert result is False
    assert await registry.is_action_approved(run_id, "execute_shell_script") is False
    assert sink.events[-1].type == ExecutionEventType.TOOL_REJECTED


@pytest.mark.asyncio
async def test_user_b_cannot_approve_user_a_run() -> None:
    registry = RunApprovalRegistry()
    sink = MockEventSink()
    user_a = uuid4()
    user_b = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    task = asyncio.create_task(
        registry.request_approval(
            sink=sink,
            run_id=run_id,
            user_id=user_a,
            action="rm_rf",
            risk_level="critical",
            reason="Danger",
            timeout_seconds=5.0,
        )
    )
    await asyncio.sleep(0.05)

    # User B tries to approve User A's run
    resolved_by_b = await registry.resolve(
        run_id=run_id,
        user_id=user_b,
        action="rm_rf",
        approved=True,
    )
    assert resolved_by_b is False  # Unauthorized: User mismatch

    # User A now legitimately approves
    resolved_by_a = await registry.resolve(
        run_id=run_id,
        user_id=user_a,
        action="rm_rf",
        approved=True,
    )
    assert resolved_by_a is True

    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_duplicate_approval_is_rejected() -> None:
    registry = RunApprovalRegistry()
    sink = MockEventSink()
    user_id = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    task = asyncio.create_task(
        registry.request_approval(
            sink=sink,
            run_id=run_id,
            user_id=user_id,
            action="write_system_file",
            risk_level="high",
            reason="Privileged write",
            timeout_seconds=5.0,
        )
    )
    await asyncio.sleep(0.05)

    first_attempt = await registry.resolve(
        run_id=run_id,
        user_id=user_id,
        action="write_system_file",
        approved=True,
    )
    assert first_attempt is True

    # Second attempt on already resolved pending approval
    # Pending map was cleared upon task finish
    await task
    second_attempt = await registry.resolve(
        run_id=run_id,
        user_id=user_id,
        action="write_system_file",
        approved=False,
    )
    assert second_attempt is False


@pytest.mark.asyncio
async def test_approval_after_run_completion_rejected() -> None:
    registry = RunApprovalRegistry()
    user_id = uuid4()
    run_id = f"run-{uuid4().hex[:12]}"

    # No approval pending (e.g. run already completed)
    attempt = await registry.resolve(
        run_id=run_id,
        user_id=user_id,
        action="some_action",
        approved=False,
    )
    assert attempt is False
