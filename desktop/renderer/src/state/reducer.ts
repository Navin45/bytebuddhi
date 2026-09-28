import type { RunEvent } from "../generated/contracts"
import type { AppState, RunStatus, TranscriptItem } from "./app-state"

const TERMINAL: Record<string, RunStatus> = {
  run_completed: "completed",
  run_failed: "failed",
  run_cancelled: "cancelled",
  run_interrupted: "interrupted",
}

export function reduceRunEvent(state: AppState, event: RunEvent): AppState {
  if (event.sequence <= state.lastSequence) return state
  const next: AppState = { ...state, lastSequence: event.sequence, activeRunId: event.run_id || state.activeRunId }
  if (event.type === "run_queued") return { ...next, runStatus: "queued", submitting: false }
  if (event.type === "run_started") return { ...next, runStatus: "running", submitting: false }
  if (event.type === "assistant_delta") return appendDelta(next, event.run_id, text(event, "delta"))
  if (event.type === "tool_started") return openTool(next, event.run_id, event.sequence, text(event, "tool_name") || "tool")
  if (event.type === "tool_completed") return closeTool(next, event.run_id, event)
  if (event.type === "tool_approval_required") {
    const action = text(event, "action") || text(event, "tool_name") || "action"
    const riskLevel = text(event, "risk_level") || "high"
    const reason = text(event, "reason") || "Explicit user approval required"
    return {
      ...next,
      pendingApproval: { runId: event.run_id, action, riskLevel, reason },
      transcript: [
        ...next.transcript,
        {
          id: `approval-${event.run_id}-${event.sequence}`,
          kind: "notice",
          title: "Approval Required",
          body: `Action '${action}' requires approval (risk tier: ${riskLevel})`,
          detail: reason,
          runId: event.run_id,
          streaming: false,
          toolOpen: false,
        },
      ],
    }
  }
  if (event.type === "tool_approved" || event.type === "tool_rejected") {
    return { ...next, pendingApproval: null }
  }
  if (event.type === "run_cancel_requested") return { ...next, runStatus: "cancel_requested" }
  if (event.type === "message_created") return { ...next, transcript: finishStream(next.transcript, event.run_id) }
  const status = TERMINAL[event.type]
  if (status) return finish({ ...next, pendingApproval: null }, event.run_id, status, event)
  return next
}

export function withUserMessage(state: AppState, textBody: string, id: string): AppState {
  const item: TranscriptItem = {
    id,
    kind: "user",
    title: "You",
    body: textBody,
    detail: "",
    runId: null,
    streaming: false,
    toolOpen: false,
  }
  return { ...state, submitting: true, transcript: [...state.transcript, item] }
}

function appendDelta(state: AppState, runId: string, delta: string): AppState {
  const items = [...state.transcript]
  const last = items.at(-1)
  if (last && last.kind === "assistant" && last.streaming && last.runId === runId) {
    items[items.length - 1] = { ...last, body: last.body + delta }
    return { ...state, transcript: items }
  }
  items.push({
    id: `assistant-${runId}`,
    kind: "assistant",
    title: "ByteBuddhi",
    body: delta,
    detail: "",
    runId,
    streaming: true,
    toolOpen: false,
  })
  return { ...state, transcript: items }
}

function openTool(state: AppState, runId: string, sequence: number, name: string): AppState {
  return {
    ...state,
    transcript: [
      ...state.transcript,
      {
        id: `tool-${runId}-${sequence}`,
        kind: "tool",
        title: name,
        body: "running",
        detail: "",
        runId,
        streaming: false,
        toolOpen: true,
      },
    ],
  }
}

function closeTool(state: AppState, runId: string, event: RunEvent): AppState {
  const name = text(event, "tool_name")
  const artifact = text(event, "artifact_id")
  const failed = text(event, "status") === "failed" || Boolean(text(event, "error_message"))
  const items = [...state.transcript]
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]
    if (item && item.kind === "tool" && item.toolOpen && item.runId === runId) {
      items[index] = {
        ...item,
        title: name || item.title,
        body: failed ? "failed" : "completed",
        detail: artifact ? `artifact ${artifact}` : text(event, "error_message"),
        toolOpen: false,
      }
      break
    }
  }
  return { ...state, transcript: items }
}

function finish(state: AppState, runId: string, status: RunStatus, event: RunEvent): AppState {
  const transcript = finishStream(state.transcript, runId)
  const notice = noticeFor(runId, status, event)
  return {
    ...state,
    transcript: notice ? [...transcript, notice] : transcript,
    runStatus: status,
    submitting: false,
    cancelSent: false,
  }
}

function finishStream(items: TranscriptItem[], runId: string): TranscriptItem[] {
  return items.map((item) => (item.kind === "assistant" && item.runId === runId ? { ...item, streaming: false } : item))
}

function noticeFor(runId: string, status: RunStatus, event: RunEvent): TranscriptItem | null {
  if (status === "completed") return null
  const error = text(event, "error_message")
  const body =
    status === "interrupted"
      ? `${error ? `${error} ` : ""}The worker lease expired and the run was not replayed.`
      : status === "cancelled"
        ? "Run cancelled"
        : error || "Run failed"
  return {
    id: `notice-${runId}-${status}`,
    kind: "notice",
    title: status.toUpperCase(),
    body,
    detail: "",
    runId,
    streaming: false,
    toolOpen: false,
  }
}

function text(
  event: RunEvent,
  key: "delta" | "tool_name" | "artifact_id" | "error_message" | "status" | "action" | "risk_level" | "reason",
): string {
  const value = (event.data as Record<string, unknown>)[key]
  return typeof value === "string" ? value : ""
}
