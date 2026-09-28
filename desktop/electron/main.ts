import { app, BrowserWindow, ipcMain, shell } from "electron"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import electronUpdater, { type UpdateInfo } from "electron-updater"

const { autoUpdater } = electronUpdater

import { CredentialVault, type StoredCredentials } from "./credentials"
import { initCrashHandling } from "./crash"
import { GatewayBridge } from "./gateway"
import { ManagedGateway } from "./gateway-lifecycle"
import { isLocalGateway, isSafeExternalUrl, parseGatewayOrigin } from "./security"
import { createMainWindow, installWindowLifecycle } from "./windows"

initCrashHandling()

// ── Auto-update state ──────────────────────────────────────────────
type UpdateState =
  | { status: "idle" }
  | { status: "checking" }
  | { status: "available"; version: string }
  | { status: "downloading"; percent: number }
  | { status: "ready"; version: string }
  | { status: "error"; message: string }

let updateState: UpdateState = { status: "idle" }
let hasActiveRun = false

type DesktopSettings = {
  gatewayUrl: string
  theme: "light" | "dark" | "system"
  fontSize: number
  autoStartLocalGateway: boolean
  modelProvider: string | null
  modelName: string | null
  releaseChannel: "stable" | "beta"
}

const DEFAULT_SETTINGS: DesktopSettings = {
  gatewayUrl: "http://127.0.0.1:8765",
  theme: "system",
  fontSize: 16,
  autoStartLocalGateway: true,
  modelProvider: null,
  modelName: null,
  releaseChannel: "stable",
}

let settings = { ...DEFAULT_SETTINGS }
let credentials: StoredCredentials | null = null
const managedGateway = new ManagedGateway()
let bridge!: GatewayBridge

function applyUpdateChannel(channel: "stable" | "beta"): void {
  if (channel === "beta") {
    autoUpdater.allowPrerelease = true
    autoUpdater.channel = "rc"
  } else {
    autoUpdater.allowPrerelease = false
    autoUpdater.channel = "latest"
  }
}

if (process.env.BYTEBUDDHI_E2E_GATEWAY) {
  app.setPath("userData", join(tmpdir(), "bytebuddhi-desktop-e2e"))
}

function settingsPath(): string {
  return join(app.getPath("userData"), "settings.json")
}

function loadSettings(): DesktopSettings {
  try {
    const parsed: unknown = JSON.parse(readFileSync(settingsPath(), "utf8"))
    settings = sanitizeSettings(parsed)
  } catch {
    settings = { ...DEFAULT_SETTINGS }
  }
  applyUpdateChannel(settings.releaseChannel)
  const e2eOrigin = process.env.BYTEBUDDHI_E2E_GATEWAY
  if (e2eOrigin) {
    const origin = parseGatewayOrigin(e2eOrigin)
    if (origin) settings = { ...settings, gatewayUrl: origin, autoStartLocalGateway: false }
  }
  return settings
}

function saveSettings(patch: Partial<DesktopSettings>): DesktopSettings {
  settings = sanitizeSettings({ ...settings, ...patch })
  applyUpdateChannel(settings.releaseChannel)
  mkdirSync(app.getPath("userData"), { recursive: true })
  writeFileSync(settingsPath(), JSON.stringify(settings, null, 2))
  return settings
}

function sanitizeSettings(value: unknown): DesktopSettings {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : {}
  const origin = typeof record.gatewayUrl === "string" ? parseGatewayOrigin(record.gatewayUrl) : null
  const theme = record.theme === "light" || record.theme === "dark" || record.theme === "system" ? record.theme : "system"
  const fontSize = typeof record.fontSize === "number" ? Math.min(22, Math.max(12, Math.round(record.fontSize))) : 16
  const releaseChannel = record.releaseChannel === "beta" ? "beta" : "stable"
  return {
    gatewayUrl: origin ?? DEFAULT_SETTINGS.gatewayUrl,
    theme,
    fontSize,
    autoStartLocalGateway: record.autoStartLocalGateway === true,
    modelProvider: typeof record.modelProvider === "string" ? record.modelProvider : null,
    modelName: typeof record.modelName === "string" ? record.modelName : null,
    releaseChannel,
  }
}

function currentTokens(): StoredCredentials | null {
  const e2eToken = process.env.BYTEBUDDHI_E2E_TOKEN
  if (e2eToken) return { accessToken: e2eToken, refreshToken: "" }
  return credentials
}

async function maybeStartGateway(): Promise<void> {
  if (process.env.BYTEBUDDHI_E2E_GATEWAY) return
  if (!settings.autoStartLocalGateway || !isLocalGateway(settings.gatewayUrl)) return
  await managedGateway.ensureRunning(settings.gatewayUrl)
}

function broadcast(channel: string, payload: unknown): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send(channel, payload)
  }
}

async function exchangeCode(code: string): Promise<void> {
  const trimmed = code.trim()
  if (!trimmed || trimmed.length > 512) throw new Error("A one-time code is required.")
  const exchanged = await bridge.request({
    method: "POST",
    path: "/api/v1/auth/oauth/exchange",
    body: { code: trimmed },
  })
  if (exchanged.status >= 400 || !exchanged.body || typeof exchanged.body !== "object") {
    throw new Error("Sign-in failed or the code expired.")
  }
  const record = exchanged.body as Record<string, unknown>
  if (typeof record.access_token !== "string" || typeof record.refresh_token !== "string") {
    throw new Error("Sign-in failed.")
  }
  credentials = { accessToken: record.access_token, refreshToken: record.refresh_token }
  new CredentialVault(join(app.getPath("userData"), "credentials.bin")).save(credentials)
}

app.whenReady().then(() => {
  loadSettings()
  if (!process.env.BYTEBUDDHI_E2E_TOKEN) {
    credentials = new CredentialVault(join(app.getPath("userData"), "credentials.bin")).load()
  }
  bridge = new GatewayBridge(
    () => settings.gatewayUrl,
    currentTokens,
    (next) => {
      credentials = next
      const vault = new CredentialVault(join(app.getPath("userData"), "credentials.bin"))
      if (next) vault.save(next)
      else vault.clear()
    },
    (notice) => broadcast("gateway:stream", notice),
  )
  void maybeStartGateway()
  createMainWindow()
  installWindowLifecycle(() => {
    bridge.closeAll()
    void managedGateway.stop()
  })
})

app.on("before-quit", () => {
  void managedGateway.stop()
})

ipcMain.handle("desktop:version", () => app.getVersion())
ipcMain.handle("desktop:platform", () => process.platform)
ipcMain.handle("desktop:about", () => ({
  version: app.getVersion(),
  protocol: 1,
  commit: process.env.BYTEBUDDHI_GIT_COMMIT || "release",
  buildTime: process.env.BYTEBUDDHI_BUILD_TIME || new Date().toISOString().slice(0, 10),
  channel: settings.releaseChannel || autoUpdater.channel || "stable",
}))
ipcMain.handle("desktop:open-external", async (_event, url: unknown) => {
  if (typeof url !== "string" || !isSafeExternalUrl(url)) return false
  await shell.openExternal(url)
  return true
})
ipcMain.handle("gateway:request", (_event, call: unknown) => {
  if (!call || typeof call !== "object") return { status: 400, body: { detail: "Request is invalid." } }
  const record = call as Record<string, unknown>
  if (typeof record.method !== "string" || typeof record.path !== "string") {
    return { status: 400, body: { detail: "Request is invalid." } }
  }
  const headers = record.headers && typeof record.headers === "object" ? (record.headers as Record<string, string>) : undefined
  return bridge.request({ method: record.method, path: record.path, body: record.body, headers })
})
ipcMain.handle("gateway:stream-open", (_event, input: unknown) => {
  const record = input && typeof input === "object" ? (input as Record<string, unknown>) : {}
  return bridge.openStream(String(record.runId ?? ""), Number(record.afterSequence ?? 0))
})
ipcMain.handle("gateway:stream-close", (_event, streamId: unknown) => {
  if (typeof streamId === "string") bridge.closeStream(streamId)
})
ipcMain.handle("auth:status", () => ({ signedIn: Boolean(currentTokens()?.accessToken) }))
ipcMain.handle("auth:start", async (_event, provider: unknown) => {
  if (provider !== "google" && provider !== "github") throw new Error("Provider must be google or github.")
  const url = `${settings.gatewayUrl}/api/v1/auth/${provider}/login?client=cli`
  if (!isSafeExternalUrl(url)) throw new Error("The sign-in URL was rejected.")
  await shell.openExternal(url)
})
ipcMain.handle("auth:exchange", (_event, code: unknown) => exchangeCode(typeof code === "string" ? code : ""))
ipcMain.handle("auth:sign-out", () => {
  credentials = null
  if (!process.env.BYTEBUDDHI_E2E_TOKEN) {
    new CredentialVault(join(app.getPath("userData"), "credentials.bin")).clear()
  }
})
ipcMain.handle("settings:load", () => settings)
ipcMain.handle("settings:save", (_event, patch: unknown) => {
  const next = saveSettings(patch && typeof patch === "object" ? (patch as Partial<DesktopSettings>) : {})
  if (next.autoStartLocalGateway) maybeStartGateway()
  return next
})

// ── Auto-update IPC ────────────────────────────────────────────────
ipcMain.handle("update:state", () => updateState)
ipcMain.handle("update:check", async () => {
  try {
    await autoUpdater.checkForUpdates()
  } catch (err) {
    updateState = { status: "error", message: String(err) }
  }
  return updateState
})
ipcMain.handle("update:download", async () => {
  if (hasActiveRun) {
    updateState = { status: "error", message: "Cannot update while a run is active." }
    return updateState
  }
  try {
    await autoUpdater.downloadUpdate()
  } catch (err) {
    updateState = { status: "error", message: String(err) }
  }
  return updateState
})
ipcMain.handle("update:install", () => {
  if (hasActiveRun) {
    updateState = { status: "error", message: "Cannot update while a run is active." }
    return updateState
  }
  autoUpdater.quitAndInstall(false, true)
})
ipcMain.handle("update:set-active-run", (_event, active: unknown) => {
  hasActiveRun = active === true
})

// ── Auto-update events ─────────────────────────────────────────────
autoUpdater.autoDownload = false
autoUpdater.autoInstallOnAppQuit = false
autoUpdater.allowPrerelease = false

autoUpdater.on("checking-for-update", () => {
  updateState = { status: "checking" }
  broadcast("update:state", updateState)
})
autoUpdater.on("update-available", (info: UpdateInfo) => {
  updateState = { status: "available", version: info.version }
  broadcast("update:state", updateState)
})
autoUpdater.on("update-not-available", () => {
  updateState = { status: "idle" }
  broadcast("update:state", updateState)
})
autoUpdater.on("download-progress", (progress: { percent: number }) => {
  updateState = { status: "downloading", percent: Math.round(progress.percent) }
  broadcast("update:state", updateState)
})
autoUpdater.on("update-downloaded", (info: UpdateInfo) => {
  updateState = { status: "ready", version: info.version }
  broadcast("update:state", updateState)
})
autoUpdater.on("error", (err: Error) => {
  updateState = { status: "error", message: err?.message ?? String(err) }
  broadcast("update:state", updateState)
})
