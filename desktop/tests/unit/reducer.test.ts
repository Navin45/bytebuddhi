import { describe, expect, it } from "vitest"

import { initialState, runActive } from "../../renderer/src/state/app-state"
import { reduceRunEvent, withUserMessage } from "../../renderer/src/state/reducer"
import type { RunEvent } from "../../renderer/src/generated/contracts"

function event(sequence: number, type: RunEvent["type"], data: RunEvent["data"] = {}): RunEvent {
  return {
    event_id: `evt-${sequence}`,
    run_id: "run_1",
    sequence,
    type,
    schema_version: 1,
    created_at: "2026-09-25T00:00:00+00:00",
    data,
  }
}

describe("reduceRunEvent", () => {
  it("merges assistant deltas into one message", () => {
    let state = initialState()
    state = reduceRunEvent(state, event(1, "run_queued"))
    state = reduceRunEvent(state, event(2, "run_started"))
    state = reduceRunEvent(state, event(3, "assistant_delta", { delta: "Hello" }))
    state = reduceRunEvent(state, event(4, "assistant_delta", { delta: " world" }))
    state = reduceRunEvent(state, event(5, "run_completed"))
    const assistants = state.transcript.filter((item) => item.kind === "assistant")
    expect(assistants).toHaveLength(1)
    expect(assistants[0]?.body).toBe("Hello world")
    expect(state.runStatus).toBe("completed")
    expect(runActive(state)).toBe(false)
  })

  it("ignores a duplicate sequence", () => {
    const state = reduceRunEvent(initialState(), event(1, "assistant_delta", { delta: "Hello" }))
    const again = reduceRunEvent(state, event(1, "assistant_delta", { delta: " again" }))
    expect(again.transcript[0]?.body).toBe("Hello")
  })

  it("updates the same tool activity", () => {
    let state = initialState()
    state = reduceRunEvent(state, event(1, "tool_started", { tool_name: "filesystem.search" }))
    state = reduceRunEvent(state, event(2, "tool_completed", { tool_name: "filesystem.search", artifact_id: "art_1" }))
    const tools = state.transcript.filter((item) => item.kind === "tool")
    expect(tools).toHaveLength(1)
    expect(tools[0]?.body).toBe("completed")
    expect(tools[0]?.detail).toContain("art_1")
  })

  it("unlocks terminal states and explains interruption", () => {
    for (const status of ["run_completed", "run_failed", "run_cancelled", "run_interrupted"] as const) {
      const state = reduceRunEvent({ ...initialState(), submitting: true, runStatus: "running" }, event(1, status))
      expect(runActive(state)).toBe(false)
    }
    const interrupted = reduceRunEvent(initialState(), event(1, "run_interrupted"))
    expect(interrupted.transcript[0]?.body).toContain("was not replayed")
  })

  it("keeps the composer locked after cancel is requested", () => {
    const state = reduceRunEvent({ ...initialState(), runStatus: "running" }, event(1, "run_cancel_requested"))
    expect(state.runStatus).toBe("cancel_requested")
    expect(runActive(state)).toBe(true)
  })

  it("does not call the network", () => {
    const state = withUserMessage(initialState(), "hello", "user-1")
    expect(state.submitting).toBe(true)
    expect(state.transcript[0]?.body).toBe("hello")
  })
})
