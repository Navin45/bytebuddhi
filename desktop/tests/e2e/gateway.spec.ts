import { createServer, type ServerResponse } from "node:http"
import type { AddressInfo } from "node:net"
import { _electron as electron, expect, test } from "@playwright/test"
import { WebSocketServer, type WebSocket } from "ws"

const TOKEN = "e2e-token"

type RunEvent = {
  event_id: string
  run_id: string
  sequence: number
  type: string
  schema_version: number
  created_at: string
  data: Record<string, string>
}

type RunRecord = {
  id: string
  events: RunEvent[]
  visibleUntil: number
  sockets: WebSocket[]
}

test("streams a run, replays a gap, and cancels once", async () => {
  const runs: RunRecord[] = []
  let cancelCount = 0
  const gateway = createServer(async (request, response) => {
    if (request.headers.authorization !== `Bearer ${TOKEN}`) {
      json(response, 401, { detail: "unauthorized" })
      return
    }
    const url = new URL(request.url ?? "/", "http://127.0.0.1")
    if (request.method === "GET" && url.pathname === "/api/v1/health/ready") {
      json(response, 200, { status: "ready", checks: {} })
      return
    }
    if (request.method === "GET" && url.pathname === "/api/v1/projects") {
      json(response, 200, [{ id: "p1", name: "bytebuddhi", user_id: "u", is_active: true, created_at: "t", updated_at: "t" }])
      return
    }
    if (request.method === "GET" && url.pathname === "/api/v1/chat/conversations") {
      json(response, 200, [])
      return
    }
    if (request.method === "POST" && url.pathname === "/api/v1/chat/conversations") {
      json(response, 201, {
        id: "c1",
        title: "Say hello",
        project_id: "p1",
        user_id: "u",
        is_archived: false,
        created_at: "t",
        updated_at: "t",
      })
      return
    }
    if (request.method === "GET" && url.pathname === "/api/v1/models") {
      json(response, 200, {
        default_provider: "openai",
        default_model: "server-model",
        models: [{ provider: "openai", model: "server-model", display_name: "Server model", capabilities: ["chat"], available: true }],
      })
      return
    }
    if (request.method === "GET" && url.pathname.endsWith("/messages")) {
      json(response, 200, [])
      return
    }
    if (request.method === "POST" && url.pathname === "/api/v1/runs") {
      const run = createRun(runs)
      json(response, 202, { run_id: run.id, conversation_id: "c1", status: "queued" })
      return
    }
    const eventsMatch = url.pathname.match(/^\/api\/v1\/runs\/([^/]+)\/events$/)
    if (request.method === "GET" && eventsMatch) {
      const run = runs.find((item) => item.id === eventsMatch[1])
      const after = Number(url.searchParams.get("after_sequence") ?? "0")
      const events = run?.events.filter((item) => item.sequence > after && item.sequence <= (run?.visibleUntil ?? 0)) ?? []
      json(response, 200, { events, next_sequence: events.at(-1)?.sequence ?? after, has_more: false })
      return
    }
    const cancelMatch = url.pathname.match(/^\/api\/v1\/runs\/([^/]+)\/cancel$/)
    if (request.method === "POST" && cancelMatch) {
      cancelCount += 1
      const run = runs.find((item) => item.id === cancelMatch[1])
      if (run) publish(run, ["run_cancel_requested", "run_cancelled"])
      json(response, 200, { run_id: cancelMatch[1], status: "running" })
      return
    }
    json(response, 404, { detail: "missing" })
  })
  const sockets = new WebSocketServer({ noServer: true })
  gateway.on("upgrade", (request, socket, head) => {
    if (request.headers.authorization !== `Bearer ${TOKEN}`) {
      socket.destroy()
      return
    }
    sockets.handleUpgrade(request, socket, head, (ws) => {
      const url = new URL(request.url ?? "/", "http://127.0.0.1")
      const match = url.pathname.match(/^\/api\/v1\/runs\/([^/]+)\/stream$/)
      const run = runs.find((item) => item.id === match?.[1])
      if (!run) {
        ws.close()
        return
      }
      const after = Number(url.searchParams.get("after_sequence") ?? "0")
      run.sockets.push(ws)
      if (runs[0]?.id === run.id && after === 0) {
        sendVisible(run, after, 2)
        run.visibleUntil = 3
        ws.close()
        return
      }
      if (runs[0]?.id === run.id) {
        run.visibleUntil = 4
        sendVisible(run, after, 4)
        ws.close()
        return
      }
      sendVisible(run, after, run.visibleUntil)
    })
  })
  await new Promise<void>((resolve) => gateway.listen(0, "127.0.0.1", resolve))
  const port = (gateway.address() as AddressInfo).port
  const app = await electron.launch({
    args: ["out/main/index.js"],
    env: {
      ...process.env,
      BYTEBUDDHI_E2E_GATEWAY: `http://127.0.0.1:${port}`,
      BYTEBUDDHI_E2E_TOKEN: TOKEN,
    },
  })
  try {
    const page = await app.firstWindow()
    const isolation = await app.evaluate(async ({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0]
      return window?.webContents.executeJavaScript(`({
        require: typeof require,
        process: typeof process,
        fs: typeof window.fs,
        desktop: typeof window.bytebuddhi?.desktop?.openExternal
      })`)
    })
    expect(isolation.require).toBe("undefined")
    expect(isolation.process).toBe("undefined")
    expect(isolation.fs).toBe("undefined")
    expect(isolation.desktop).toBe("function")
    expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([])
    await expect(page.getByRole("button", { name: /bytebuddhi/ })).toBeVisible()
    await page.getByLabel("Message").fill("Say hello")
    await page.getByRole("button", { name: "Send" }).click()
    await expect(page.getByText("Hello world")).toBeVisible()
    expect(runs).toHaveLength(1)

    await page.getByLabel("Message").fill("Stop this")
    await page.getByRole("button", { name: "Send" }).click()
    await page.getByRole("button", { name: "Stop" }).click()
    await expect(page.getByText("Run cancelled")).toBeVisible()
    expect(runs).toHaveLength(2)
    expect(cancelCount).toBe(1)
    await app.close()
    expect(cancelCount).toBe(1)
  } finally {
    await app.close().catch(() => undefined)
    sockets.close()
    await new Promise<void>((resolve, reject) => gateway.close((error) => (error ? reject(error) : resolve())))
  }
})

function createRun(runs: RunRecord[]): RunRecord {
  const id = `run_${runs.length + 1}`
  const run: RunRecord = { id, events: [], visibleUntil: 0, sockets: [] }
  if (runs.length === 0) {
    run.events = [event(id, 1, "run_started"), event(id, 2, "assistant_delta", "Hello"), event(id, 3, "assistant_delta", " world"), event(id, 4, "run_completed")]
    run.visibleUntil = 2
  } else {
    run.events = [event(id, 1, "run_queued"), event(id, 2, "run_started")]
    run.visibleUntil = 2
  }
  runs.push(run)
  return run
}

function publish(run: RunRecord, types: string[]): void {
  const start = run.events.length
  types.forEach((type, index) => {
    run.events.push(event(run.id, start + index + 1, type))
  })
  run.visibleUntil = run.events.length
  for (const socket of run.sockets) {
    if (socket.readyState === socket.OPEN) sendVisible(run, 0, run.visibleUntil)
  }
}

function sendVisible(run: RunRecord, after: number, until: number): void {
  for (const socket of run.sockets) {
    for (const item of run.events) {
      if (item.sequence > after && item.sequence <= until && socket.readyState === socket.OPEN) {
        socket.send(JSON.stringify(item))
      }
    }
  }
}

function event(runId: string, sequence: number, type: string, delta = ""): RunEvent {
  return {
    event_id: `${runId}-${sequence}`,
    run_id: runId,
    sequence,
    type,
    schema_version: 1,
    created_at: "2026-09-25T00:00:00+00:00",
    data: delta ? { delta } : {},
  }
}

function json(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json" })
  response.end(JSON.stringify(body))
}
