import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Composer } from "../../renderer/src/components/Composer"
import { ConversationView } from "../../renderer/src/components/ConversationView"
import { initialState } from "../../renderer/src/state/app-state"
import { reduceRunEvent } from "../../renderer/src/state/reducer"
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

describe("conversation rendering", () => {
  it("renders one assistant message for streamed deltas", () => {
    let state = initialState()
    state = reduceRunEvent(state, event(1, "assistant_delta", { delta: "Hello" }))
    state = reduceRunEvent(state, event(2, "assistant_delta", { delta: " world" }))
    render(<ConversationView state={state} onStickToBottom={() => undefined} />)
    expect(screen.getByText("Hello world")).toBeTruthy()
    expect(screen.getAllByText("ByteBuddhi")).toHaveLength(1)
  })

  it("shows an interrupted run without calling it complete", () => {
    const state = reduceRunEvent(initialState(), event(1, "run_interrupted"))
    render(<ConversationView state={state} onStickToBottom={() => undefined} />)
    expect(screen.getByText(/was not replayed/)).toBeTruthy()
    expect(screen.getByText("INTERRUPTED")).toBeTruthy()
  })

  it("disables send while a run is active and offers stop", () => {
    render(<Composer value="hello" disabled running onChange={() => undefined} onSend={() => undefined} onStop={() => undefined} />)
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy()
    expect(screen.getByLabelText("Message")).toHaveProperty("disabled", true)
  })

  it("shows the empty conversation", () => {
    render(<ConversationView state={initialState()} onStickToBottom={() => undefined} />)
    expect(screen.getByText(/No messages yet/)).toBeTruthy()
  })
})
