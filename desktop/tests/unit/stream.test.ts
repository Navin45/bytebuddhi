import { describe, expect, it } from "vitest"

import type { RunEvent, RunEventPage } from "../../renderer/src/generated/contracts"
import { RunStreamController, type RunStreamSocket } from "../../renderer/src/state/stream"
import { GatewayConnectionError } from "../../renderer/src/api/errors"

function event(sequence: number, type: RunEvent["type"] = "assistant_delta"): RunEvent {
  return {
    event_id: `evt-${sequence}`,
    run_id: "run_1",
    sequence,
    type,
    schema_version: 1,
    created_at: "2026-09-25T00:00:00+00:00",
    data: { delta: String(sequence) },
  }
}

class FakeSocket implements RunStreamSocket {
  readonly reads: number[] = []
  readonly replays: number[] = []
  createdRuns = 0

  constructor(
    private batches: unknown[],
    private readonly pages: Record<number, RunEvent[]> = {},
  ) {}

  readRunSocket(_runId: string, afterSequence: number): AsyncIterable<unknown> {
    this.reads.push(afterSequence)
    const batch = this.batches.shift()
    return {
      async *[Symbol.asyncIterator]() {
        if (batch instanceof Error) throw batch
        if (!Array.isArray(batch)) return
        for (const item of batch) {
          if ((item as RunEvent).sequence > afterSequence) yield item
        }
      },
    }
  }

  async getRunEvents(_runId: string, afterSequence: number): Promise<RunEventPage> {
    this.replays.push(afterSequence)
    const events = this.pages[afterSequence] ?? []
    return { events, next_sequence: events.at(-1)?.sequence ?? afterSequence, has_more: false }
  }
}

async function follow(socket: FakeSocket): Promise<{ applied: number[]; statuses: string[] }> {
  const applied: number[] = []
  const statuses: string[] = []
  const controller = new RunStreamController(socket, 3, async () => undefined)
  await controller.follow(
    "run_1",
    (item) => {
      applied.push(item.sequence)
    },
    (connection) => {
      statuses.push(connection)
    },
  )
  expect(socket.createdRuns).toBe(0)
  return { applied, statuses }
}

describe("RunStreamController", () => {
  it("reconnects the same run and replays after the last sequence", async () => {
    const socket = new FakeSocket([[event(1), event(2)], new GatewayConnectionError("closed"), [event(3), event(4, "run_completed")]])
    const { applied, statuses } = await follow(socket)
    expect(applied).toEqual([1, 2, 3, 4])
    expect(socket.replays).toContain(2)
    expect(socket.reads[1]).toBe(2)
    expect(statuses).toContain("reconnecting")
  })

  it("requests the missing event before applying a later one", async () => {
    const socket = new FakeSocket([[event(1), event(2), event(4, "run_completed")]], { 2: [event(3)] })
    const { applied } = await follow(socket)
    expect(socket.replays).toEqual([2])
    expect(applied).toEqual([1, 2, 3, 4])
  })

  it("stops after the reconnect limit", async () => {
    const socket = new FakeSocket([
      new GatewayConnectionError("down"),
      new GatewayConnectionError("down"),
      new GatewayConnectionError("down"),
      new GatewayConnectionError("down"),
    ])
    const { statuses } = await follow(socket)
    expect(statuses.filter((item) => item === "reconnecting")).toHaveLength(3)
    expect(statuses.at(-1)).toBe("disconnected")
  })

  it("does not cancel the run when stopped", async () => {
    let release: () => void = () => undefined
    let started: () => void = () => undefined
    const ready = new Promise<void>((resolve) => {
      started = resolve
    })
    const socket: RunStreamSocket = {
      readRunSocket: () => ({
        async *[Symbol.asyncIterator]() {
          started()
          await new Promise<void>((resolve) => {
            release = resolve
          })
          yield undefined
        },
      }),
      getRunEvents: async () => ({ events: [], next_sequence: 0, has_more: false }),
    }
    const controller = new RunStreamController(socket, 3, async () => undefined)
    const pending = controller.follow("run_1", () => undefined, () => undefined)
    await ready
    controller.stop()
    release()
    await pending
  })
})
