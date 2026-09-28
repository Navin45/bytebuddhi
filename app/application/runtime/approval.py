"""Authoritative approval coordination for high-risk and gated actions.

Decisions are validated and recorded on the server. Clients cannot bypass
backend policy by claiming approval locally.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.application.ports.output.logger import get_logger
from app.application.runtime.events import (
    ExecutionEvent,
    ExecutionEventSink,
    ExecutionEventType,
    publish_execution_event,
)

logger = get_logger(__name__)

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300.0


@dataclass
class PendingApproval:
    run_id: str
    user_id: UUID
    action: str
    risk_level: str
    reason: str
    future: asyncio.Future[bool]


class RunApprovalRegistry:
    """Coordinates server-authoritative approval requests between runs and clients."""

    def __init__(self, default_timeout_seconds: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS) -> None:
        self._pending: dict[tuple[str, str], PendingApproval] = {}
        self._approved_actions: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._default_timeout = default_timeout_seconds

    async def is_action_approved(self, run_id: str, action: str) -> bool:
        async with self._lock:
            return action in self._approved_actions.get(run_id, set())

    async def grant_approval(self, run_id: str, action: str) -> None:
        async with self._lock:
            if run_id not in self._approved_actions:
                self._approved_actions[run_id] = set()
            self._approved_actions[run_id].add(action)

    async def request_approval(
        self,
        *,
        run_id: str,
        user_id: UUID,
        action: str,
        risk_level: str,
        reason: str,
        sink: ExecutionEventSink | None = None,
        timeout_seconds: float | None = None,
    ) -> bool:
        """Register an approval request, emit durable event, and await user decision."""
        if await self.is_action_approved(run_id, action):
            return True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        key = (run_id, action)

        async with self._lock:
            self._pending[key] = PendingApproval(
                run_id=run_id,
                user_id=user_id,
                action=action,
                risk_level=risk_level,
                reason=reason,
                future=future,
            )

        # Emit durable TOOL_APPROVAL_REQUIRED event
        await publish_execution_event(
            sink,
            ExecutionEvent(
                type=ExecutionEventType.TOOL_APPROVAL_REQUIRED,
                run_id=run_id,
                payload={
                    "action": action,
                    "tool_name": action,
                    "risk_level": risk_level,
                    "reason": reason,
                },
            ),
        )

        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        try:
            approved = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            logger.warning("run_approval_timed_out", run_id=run_id, action=action)
            approved = False
            await publish_execution_event(
                sink,
                ExecutionEvent(
                    type=ExecutionEventType.TOOL_REJECTED,
                    run_id=run_id,
                    payload={"action": action, "tool_name": action, "reason": "Approval request timed out"},
                ),
            )
        except asyncio.CancelledError:
            approved = False
            raise
        finally:
            async with self._lock:
                self._pending.pop(key, None)

        if approved:
            await self.grant_approval(run_id, action)
            await publish_execution_event(
                sink,
                ExecutionEvent(
                    type=ExecutionEventType.TOOL_APPROVED,
                    run_id=run_id,
                    payload={"action": action, "tool_name": action},
                ),
            )
        else:
            await publish_execution_event(
                sink,
                ExecutionEvent(
                    type=ExecutionEventType.TOOL_REJECTED,
                    run_id=run_id,
                    payload={"action": action, "tool_name": action, "reason": "Approval rejected by user"},
                ),
            )
        return approved

    async def resolve(
        self,
        *,
        run_id: str,
        user_id: UUID,
        action: str,
        approved: bool,
    ) -> bool:
        """Process an explicit approval or rejection decision from an authorized user."""
        key = (run_id, action)
        pending: PendingApproval | None = None
        async with self._lock:
            pending = self._pending.get(key)

        if pending is None:
            # Check if matching any pending for this run if action matches or wildcard
            async with self._lock:
                for (r_id, act), item in self._pending.items():
                    if r_id == run_id and (act == action or action == "*"):
                        pending = item
                        key = (r_id, act)
                        break

        if pending is None:
            logger.info("run_approval_not_found", run_id=run_id, action=action)
            # If approved without a pending future, still record pre-approval
            if approved:
                await self.grant_approval(run_id, action)
                return True
            return False

        if pending.user_id != user_id:
            logger.warning(
                "run_approval_user_mismatch", run_id=run_id, expected=str(pending.user_id), actual=str(user_id)
            )
            return False

        if not pending.future.done():
            pending.future.set_result(approved)
            return True
        return False

    async def cancel_run(self, run_id: str) -> None:
        """Cancel and reject any pending approvals when a run is cancelled or terminated."""
        to_cancel: list[PendingApproval] = []
        async with self._lock:
            for (r_id, _), item in list(self._pending.items()):
                if r_id == run_id:
                    to_cancel.append(item)
                    self._pending.pop((r_id, item.action), None)

        for item in to_cancel:
            if not item.future.done():
                item.future.set_result(False)

    async def clear_run(self, run_id: str) -> None:
        """Clean up all approval state for a completed or failed run."""
        await self.cancel_run(run_id)
        async with self._lock:
            self._approved_actions.pop(run_id, None)
