import { app, type BrowserWindow } from "electron"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const BEARER_RE = /bearer\s+[A-Za-z0-9._+/=-]+/gi
const JWT_RE = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
const KEY_RE = /(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35})/g

export function sanitizeText(text: string): string {
  return text
    .replace(BEARER_RE, "Bearer [REDACTED]")
    .replace(JWT_RE, "[REDACTED_JWT]")
    .replace(KEY_RE, "[REDACTED_KEY]")
}

export function writeCrashReport(type: string, detail: unknown): void {
  try {
    const crashDir = join(app.getPath("userData"), "crashes")
    mkdirSync(crashDir, { recursive: true })

    let errorObj: { message?: string; stack?: string; details?: unknown } = {}
    if (detail instanceof Error) {
      errorObj = {
        message: sanitizeText(detail.message),
        stack: detail.stack ? sanitizeText(detail.stack) : undefined,
      }
    } else if (typeof detail === "object" && detail !== null) {
      errorObj = { details: detail }
    } else {
      errorObj = { message: sanitizeText(String(detail)) }
    }

    const report = {
      timestamp: new Date().toISOString(),
      type,
      appVersion: app.getVersion(),
      electronVersion: process.versions.electron,
      nodeVersion: process.versions.node,
      platform: process.platform,
      arch: process.arch,
      error: errorObj,
    }

    const filename = `${Date.now()}-${type.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`
    writeFileSync(join(crashDir, filename), JSON.stringify(report, null, 2), "utf8")
  } catch (err) {
    console.error("Failed to write sanitized crash report:", err)
  }
}

export function initCrashHandling(): void {
  process.on("uncaughtException", (error) => {
    writeCrashReport("main-uncaught-exception", error)
  })

  process.on("unhandledRejection", (reason) => {
    writeCrashReport("main-unhandled-rejection", reason)
  })
}

export function registerWindowCrashHandlers(window: BrowserWindow): void {
  window.webContents.on("render-process-gone", (_event, details) => {
    writeCrashReport("render-process-gone", details)
  })

  window.webContents.on("unresponsive", () => {
    writeCrashReport("renderer-unresponsive", { message: "Window became unresponsive" })
  })
}
