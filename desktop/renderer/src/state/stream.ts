import type { RunEvent, RunEventPage } from "../generated/contracts"
import { GatewayConnectionError, GatewayRequestError } from "../api/errors"
import { validateRunEvent } from "../api/validate"

const TERMINAL = new Set(["run_completed", "run_failed", "run_cancelled", "run_interrupted"])

export type StreamStatus = "connected" | "reconnecting" | "disconnected"

export interface RunStreamSocket {
  readRunSocket(runId: string, afterSequence: number, signal: AbortSignal): AsyncIterable<unknown>
  getRunEvents(runId: string, afterSequence: number): Promise<RunEventPage>
}

export class RunStreamController {
  runId: string | null = null
  lastSequence = 0
  private stopped = false
  private terminal = false
  private readonly abort = new AbortController()

  constructor(
    private readonly socket: RunStreamSocket,
    private readonly maxReconnects = 3,
    private readonly sleep: (milliseconds: number) => Promise<void> = delay,
  ) {}

  stop(): void {
    this.stopped = true
    this.abort.abort()
  }

  async follow(
    runId: string,
    onEvent: (event: RunEvent) => void | Promise<void>,
    onStatus: (connection: StreamStatus, attempt: number) => void | Promise<void>,
    onDiagnostic: (message: string) => void = () => undefined,
  ): Promise<void> {
    this.runId = runId
    let failures = 0
    while (!this.stopped && !this.terminal) {
      try {
        await onStatus("connected", failures)
        for await (const raw of this.socket.readRunSocket(runId, this.lastSequence, this.abort.signal)) {
          if (this.stopped) return
          const parsed = validateRunEvent(raw)
          if (!parsed.ok) {
            onDiagnostic(parsed.reason)
            continue
          }
          if (await this.accept(parsed.event, onEvent)) return
        }
        throw new GatewayConnectionError("Run stream closed")
      } catch (error) {
        if (this.stopped || this.abort.signal.aborted) return
        if (!(error instanceof GatewayConnectionError || error instanceof GatewayRequestError || error instanceof SequenceGap)) {
          throw error
        }
        failures += 1
        if (failures > this.maxReconnects) {
          await onStatus("disconnected", failures)
          return
        }
        await onStatus("reconnecting", failures)
        await this.catchUp(onEvent)
        if (this.terminal || this.stopped) return
        await this.sleep(Math.min(1000 * 2 ** (failures - 1), 4000))
      }
    }
  }

  private async accept(event: RunEvent, onEvent: (event: RunEvent) => void | Promise<void>): Promise<boolean> {
    if (event.sequence <= this.lastSequence) return this.terminal
    if (event.sequence !== this.lastSequence + 1) {
      await this.catchUp(onEvent)
      if (this.terminal || event.sequence <= this.lastSequence) return this.terminal
      if (event.sequence !== this.lastSequence + 1) throw new SequenceGap()
    }
    this.lastSequence = event.sequence
    await onEvent(event)
    if (TERMINAL.has(event.type)) this.terminal = true
    return this.terminal
  }

  private async catchUp(onEvent: (event: RunEvent) => void | Promise<void>): Promise<void> {
    if (!this.runId) return
    while (!this.stopped) {
      const page = await this.socket.getRunEvents(this.runId, this.lastSequence)
      if (page.events.length === 0) return
      for (const event of page.events) {
        if (event.sequence <= this.lastSequence) continue
        if (event.sequence !== this.lastSequence + 1) return
        this.lastSequence = event.sequence
        await onEvent(event)
        if (TERMINAL.has(event.type)) {
          this.terminal = true
          return
        }
      }
      if (!page.has_more) return
    }
  }
}

class SequenceGap extends Error {
  constructor() {
    super("Missing run event")
    this.name = "SequenceGap"
  }
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}
