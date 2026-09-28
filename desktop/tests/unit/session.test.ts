import { describe, expect, it } from "vitest"

import { GatewayClient, type GatewayTransport } from "../../renderer/src/api/client"
import { messageForStatus } from "../../renderer/src/api/errors"
import { validateRunEvent } from "../../renderer/src/api/validate"
import { ChatSession, type DesktopBridge, type DesktopSettings } from "../../renderer/src/state/session"
import type { RunEvent } from "../../renderer/src/generated/contracts"

const settings: DesktopSettings = {
  gatewayUrl: "http://127.0.0.1:8765",
  theme: "system",
  fontSize: 16,
  autoStartLocalGateway: false,
  modelProvider: null,
  modelName: null,
}

function bridge(): DesktopBridge {
  return {
    auth: {
      status: async () => ({ signedIn: true }),
      start: async () => undefined,
      exchange: async () => undefined,
      signOut: async () => undefined,
    },
    settings: {
      load: async () => settings,
      save: async (patch) => ({ ...settings, ...patch }),
    },
  }
}

class FakeTransport implements GatewayTransport {
  readonly runs: { headers?: Record<string, string> }[] = []
  readonly cancels: string[] = []
  block = false
  private release: () => void = () => undefined

  request(call: { method: string; path: string; headers?: Record<string, string> }) {
    if (call.path === "/api/v1/health/ready") return Promise.resolve({ status: 200, body: { status: "ready" } })
    if (call.path === "/api/v1/projects") {
      return Promise.resolve({
        status: 200,
        body: [{ id: "p1", name: "bytebuddhi", user_id: "u", is_active: true, created_at: "t", updated_at: "t" }],
      })
    }
    if (call.path === "/api/v1/chat/conversations") {
      return Promise.resolve({
        status: 200,
        body: [{ id: "c1", title: "Audit", project_id: "p1", user_id: "u", is_archived: false, created_at: "t", updated_at: "t" }],
      })
    }
    if (call.path === "/api/v1/models") {
      return Promise.resolve({
        status: 200,
        body: { default_provider: "openai", default_model: "server-model", models: [] },
      })
    }
    if (call.path.includes("/messages")) return Promise.resolve({ status: 200, body: [] })
    if (call.method === "POST" && call.path === "/api/v1/runs") {
      this.runs.push({ headers: call.headers })
      return Promise.resolve({ status: 202, body: { run_id: "run_1", conversation_id: "c1", status: "queued" } })
    }
    if (call.path.endsWith("/cancel")) {
      this.cancels.push(call.path)
      return Promise.resolve({ status: 200, body: { run_id: "run_1", status: "running" } })
    }
    if (call.path.includes("/events")) return Promise.resolve({ status: 200, body: { events: [], next_sequence: 0, has_more: false } })
    return Promise.resolve({ status: 404, body: { detail: "missing" } })
  }

  readRunSocket(): AsyncIterable<unknown> {
    const blocked = this.block
    const wait = (): Promise<void> =>
      new Promise((resolve) => {
        this.release = resolve
      })
    return {
      async *[Symbol.asyncIterator]() {
        if (!blocked) {
          yield completed(1)
          return
        }
        await wait()
        yield completed(1)
      },
    }
  }

  unblock(): void {
    this.release()
  }
}

function completed(sequence: number): RunEvent {
  return {
    event_id: "evt",
    run_id: "run_1",
    sequence,
    type: "run_completed",
    schema_version: 1,
    created_at: "2026-09-25T00:00:00+00:00",
    data: {},
  }
}

describe("gateway client and session", () => {
  it("maps status codes to actionable errors", () => {
    expect(messageForStatus(401, {})).toContain("Sign in")
    expect(messageForStatus(403, {})).toContain("do not have access")
    expect(messageForStatus(429, {})).toContain("rate limited")
    expect(messageForStatus(500, { detail: "Bearer secret-token" })).not.toContain("secret-token")
  })

  it("rejects an event that is not in the protocol", () => {
    expect(validateRunEvent({ event_id: "e", run_id: "r", sequence: 1, type: "shell", schema_version: 1, created_at: "t" }).ok).toBe(false)
  })

  it("creates one run and a second send does not create another", async () => {
    const transport = new FakeTransport()
    transport.block = true
    const session = new ChatSession(new GatewayClient(transport), bridge())
    await session.bootstrap()
    const first = session.send("Say hello")
    await waitFor(() => transport.runs.length === 1)
    await session.send("Say hello again")
    expect(transport.runs).toHaveLength(1)
    expect(transport.runs[0]?.headers?.["Idempotency-Key"]).toBeTruthy()
    expect(session.getState().composer).toBe("")
    transport.unblock()
    await first
    expect(session.getState().runStatus).toBe("completed")
  })

  it("sends cancel once and waits for the terminal event", async () => {
    const transport = new FakeTransport()
    const session = new ChatSession(new GatewayClient(transport), bridge())
    session.state = { ...session.getState(), activeRunId: "run_1", runStatus: "running", submitting: false }
    await session.cancel()
    await session.cancel()
    expect(transport.cancels).toEqual(["/api/v1/runs/run_1/cancel"])
    expect(session.getState().runStatus).toBe("running")
  })

  it("does not cancel when the session stops", async () => {
    const transport = new FakeTransport()
    const session = new ChatSession(new GatewayClient(transport), bridge())
    session.state = { ...session.getState(), activeRunId: "run_1", runStatus: "running" }
    session.stop()
    expect(transport.cancels).toEqual([])
  })
})

async function waitFor(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error("timed out")
}
