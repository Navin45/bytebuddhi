import { BrowserWindow, app } from "electron"
import { join } from "node:path"

import { registerWindowCrashHandlers } from "./crash"

export function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: "ByteBuddhi",
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  })
  registerWindowCrashHandlers(window)
  window.webContents.on("preload-error", (_event, preloadPath, error) => {
    console.error(`Preload failed: ${preloadPath}: ${error.message}`)
  })
  window.once("ready-to-show", () => window.show())
  if (process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"))
  }
  return window
}

export function installWindowLifecycle(onClose: () => void): void {
  app.on("window-all-closed", () => {
    onClose()
    app.quit()
  })
}
