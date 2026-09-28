import { GatewayClient, type GatewayTransport } from "./client"

type StreamNotice = { streamId: string; message?: string; closed?: boolean }

type ByteBuddhiWindow = {
  gateway: {
    request(call: { method: string; path: string; body?: unknown; headers?: Record<string, string> }): Promise<{
      status: number
      body: unknown
    }>
    openStream(runId: string, afterSequence: number): Promise<string>
    closeStream(streamId: string): Promise<void>
    onStream(callback: (event: StreamNotice) => void): () => void
  }
}

export function createDesktopClient(): GatewayClient {
  return new GatewayClient(new IpcTransport(desktopWindow()))
}

class IpcTransport implements GatewayTransport {
  constructor(private readonly desktop: ByteBuddhiWindow) {}

  request(call: { method: string; path: string; body?: unknown; headers?: Record<string, string> }) {
    return this.desktop.gateway.request(call)
  }

  readRunSocket(runId: string, afterSequence: number, signal: AbortSignal): AsyncIterable<unknown> {
    const desktop = this.desktop
    return {
      async *[Symbol.asyncIterator]() {
        const streamId = await desktop.gateway.openStream(runId, afterSequence)
        const queue: Array<unknown | null> = []
        let notify: (() => void) | null = null
        const unsubscribe = desktop.gateway.onStream((event) => {
          if (event.streamId !== streamId) return
          if (event.closed) queue.push(null)
          else if (typeof event.message === "string") {
            try {
              queue.push(JSON.parse(event.message) as unknown)
            } catch {
              queue.push({ invalid: true })
            }
          }
          notify?.()
        })
        const abort = (): void => {
          queue.push(null)
          notify?.()
        }
        signal.addEventListener("abort", abort)
        try {
          while (!signal.aborted) {
            const next = queue.shift()
            if (next === null) return
            if (next !== undefined) {
              yield next
              continue
            }
            await new Promise<void>((resolve) => {
              notify = resolve
            })
          }
        } finally {
          signal.removeEventListener("abort", abort)
          unsubscribe()
          await desktop.gateway.closeStream(streamId)
        }
      },
    }
  }
}

function desktopWindow(): ByteBuddhiWindow {
  const candidate = (window as unknown as { bytebuddhi?: ByteBuddhiWindow }).bytebuddhi
  if (!candidate) throw new Error("The desktop bridge is unavailable.")
  return candidate
}
