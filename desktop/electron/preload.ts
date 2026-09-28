import { contextBridge, ipcRenderer } from "electron"

const desktop = {
  getVersion: (): Promise<string> => ipcRenderer.invoke("desktop:version"),
  getPlatform: (): Promise<string> => ipcRenderer.invoke("desktop:platform"),
  getAbout: () => ipcRenderer.invoke("desktop:about"),
  openExternal: (url: string): Promise<boolean> => ipcRenderer.invoke("desktop:open-external", url),
}

const gateway = {
  request: (call: { method: string; path: string; body?: unknown; headers?: Record<string, string> }) =>
    ipcRenderer.invoke("gateway:request", call),
  openStream: (runId: string, afterSequence: number): Promise<string> =>
    ipcRenderer.invoke("gateway:stream-open", { runId, afterSequence }),
  closeStream: (streamId: string): Promise<void> => ipcRenderer.invoke("gateway:stream-close", streamId),
  onStream: (callback: (event: { streamId: string; message?: string; closed?: boolean }) => void): (() => void) => {
    const listener = (_event: unknown, payload: { streamId: string; message?: string; closed?: boolean }): void => {
      callback(payload)
    }
    ipcRenderer.on("gateway:stream", listener)
    return () => ipcRenderer.removeListener("gateway:stream", listener)
  },
}

const auth = {
  status: (): Promise<{ signedIn: boolean }> => ipcRenderer.invoke("auth:status"),
  start: (provider: "google" | "github"): Promise<void> => ipcRenderer.invoke("auth:start", provider),
  exchange: (code: string): Promise<void> => ipcRenderer.invoke("auth:exchange", code),
  signOut: (): Promise<void> => ipcRenderer.invoke("auth:sign-out"),
}

const settings = {
  load: () => ipcRenderer.invoke("settings:load"),
  save: (patch: unknown) => ipcRenderer.invoke("settings:save", patch),
}

const update = {
  getState: () => ipcRenderer.invoke("update:state"),
  check: () => ipcRenderer.invoke("update:check"),
  download: () => ipcRenderer.invoke("update:download"),
  install: () => ipcRenderer.invoke("update:install"),
  setActiveRun: (active: boolean) => ipcRenderer.invoke("update:set-active-run", active),
  onState: (callback: (state: unknown) => void): (() => void) => {
    const listener = (_event: unknown, state: unknown): void => callback(state)
    ipcRenderer.on("update:state", listener)
    return () => ipcRenderer.removeListener("update:state", listener)
  },
}

contextBridge.exposeInMainWorld("bytebuddhi", { desktop, gateway, auth, settings, update })
