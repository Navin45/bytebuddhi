import WebSocket from "ws"

import { isAllowedApiPath, isValidRunId, websocketUrl } from "./security"

export type GatewayCall = {
  method: string
  path: string
  body?: unknown
  headers?: Record<string, string>
}

export type StreamNotice =
  | { streamId: string; message: string }
  | { streamId: string; closed: true }

type TokenPair = { accessToken: string; refreshToken: string }

export class GatewayBridge {
  private readonly sockets = new Map<string, WebSocket>()
  private sequence = 0

  constructor(
    private readonly origin: () => string,
    private readonly tokens: () => TokenPair | null,
    private readonly replaceTokens: (tokens: TokenPair | null) => void,
    private readonly emit: (notice: StreamNotice) => void,
  ) {}

  async request(call: GatewayCall): Promise<{ status: number; body: unknown }> {
    if (!isAllowedApiPath(call.path)) {
      return { status: 400, body: { detail: "Request path is not allowed." } }
    }
    const first = await this.send(call)
    if (first.status !== 401 || call.path === "/api/v1/auth/refresh") return first
    const refreshed = await this.refresh()
    if (!refreshed) return first
    return this.send(call)
  }

  openStream(runId: string, afterSequence: number): string {
    if (!isValidRunId(runId) || !Number.isInteger(afterSequence) || afterSequence < 0) {
      throw new Error("Run stream request is invalid")
    }
    const accessToken = this.tokens()?.accessToken
    if (!accessToken) throw new Error("Authentication required")
    const streamId = `stream-${++this.sequence}`
    const socket = new WebSocket(websocketUrl(this.origin(), `/api/v1/runs/${runId}/stream?after_sequence=${afterSequence}`), {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    this.sockets.set(streamId, socket)
    socket.on("message", (data: WebSocket.RawData) => {
      this.emit({ streamId, message: data.toString() })
    })
    const finish = (): void => {
      if (!this.sockets.has(streamId)) return
      this.sockets.delete(streamId)
      this.emit({ streamId, closed: true })
    }
    socket.on("close", finish)
    socket.on("error", finish)
    return streamId
  }

  closeStream(streamId: string): void {
    const socket = this.sockets.get(streamId)
    this.sockets.delete(streamId)
    socket?.close()
  }

  closeAll(): void {
    for (const socket of this.sockets.values()) socket.close()
    this.sockets.clear()
  }

  private async refresh(): Promise<boolean> {
    const refreshToken = this.tokens()?.refreshToken
    if (!refreshToken) return false
    const response = await this.send({
      method: "POST",
      path: "/api/v1/auth/refresh",
      body: { refresh_token: refreshToken },
    })
    if (response.status >= 400 || !response.body || typeof response.body !== "object") {
      this.replaceTokens(null)
      return false
    }
    const record = response.body as Record<string, unknown>
    if (typeof record.access_token !== "string" || typeof record.refresh_token !== "string") {
      this.replaceTokens(null)
      return false
    }
    this.replaceTokens({ accessToken: record.access_token, refreshToken: record.refresh_token })
    return true
  }

  private async send(call: GatewayCall): Promise<{ status: number; body: unknown }> {
    const headers: Record<string, string> = { accept: "application/json" }
    const accessToken = this.tokens()?.accessToken
    if (accessToken && call.path !== "/api/v1/auth/oauth/exchange" && call.path !== "/api/v1/auth/refresh") {
      headers.authorization = `Bearer ${accessToken}`
    }
    for (const [key, value] of Object.entries(call.headers ?? {})) {
      if (key.toLowerCase() === "authorization") continue
      headers[key] = value
    }
    if (call.body !== undefined) headers["content-type"] = "application/json"
    let response: Response
    try {
      response = await fetch(`${this.origin()}${call.path}`, {
        method: call.method,
        headers,
        body: call.body === undefined ? undefined : JSON.stringify(call.body),
      })
    } catch {
      return { status: 0, body: { detail: "Cannot connect to the ByteBuddhi gateway." } }
    }
    const text = await response.text()
    if (!text) return { status: response.status, body: null }
    try {
      return { status: response.status, body: JSON.parse(text) as unknown }
    } catch {
      return { status: response.status, body: { detail: "The gateway returned an unreadable response." } }
    }
  }
}
