import type { DesktopSettings } from "./state/session"

export type ByteBuddhiApi = {
  desktop: {
    getVersion(): Promise<string>
    getPlatform(): Promise<string>
    openExternal(url: string): Promise<boolean>
  }
  gateway: {
    request(call: {
      method: string
      path: string
      body?: unknown
      headers?: Record<string, string>
    }): Promise<{ status: number; body: unknown }>
    openStream(runId: string, afterSequence: number): Promise<string>
    closeStream(streamId: string): Promise<void>
    onStream(callback: (event: { streamId: string; message?: string; closed?: boolean }) => void): () => void
  }
  auth: {
    status(): Promise<{ signedIn: boolean }>
    start(provider: "google" | "github"): Promise<void>
    exchange(code: string): Promise<void>
    signOut(): Promise<void>
  }
  settings: {
    load(): Promise<DesktopSettings>
    save(patch: Partial<DesktopSettings>): Promise<DesktopSettings>
  }
  update: {
    getState(): Promise<{ status: string; version?: string; percent?: number; message?: string }>
    check(): Promise<{ status: string; version?: string; percent?: number; message?: string }>
    download(): Promise<{ status: string; version?: string; percent?: number; message?: string }>
    install(): Promise<void>
    setActiveRun(active: boolean): Promise<void>
    onState(callback: (state: { status: string; version?: string; percent?: number; message?: string }) => void): () => void
  }
}

declare global {
  interface Window {
    bytebuddhi: ByteBuddhiApi
  }
}
