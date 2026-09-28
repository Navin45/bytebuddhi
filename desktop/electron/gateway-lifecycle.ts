import { spawn, type ChildProcess } from "node:child_process"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

import { isLocalGateway } from "./security"

export async function probeGatewayLive(origin: string, timeoutMs = 1500): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const res = await fetch(`${origin}/api/v1/health/live`, { signal: controller.signal })
    clearTimeout(timer)
    return res.ok
  } catch {
    return false
  }
}

export async function waitForGatewayReadiness(origin: string, timeoutMs = 15000, intervalMs = 250): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${origin}/api/v1/health/ready`)
      if (res.ok) return true
    } catch {
      // Gateway is still starting up
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return false
}

export function findGatewayCommand(): { command: string; args: string[] } {
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA
    if (localAppData) {
      const cmdPath = join(localAppData, "ByteBuddhi", "bin", "bytebuddhi.cmd")
      if (existsSync(cmdPath)) {
        return { command: cmdPath, args: ["gateway", "start"] }
      }
      const exePath = join(localAppData, "ByteBuddhi", "bin", "bytebuddhi.exe")
      if (existsSync(exePath)) {
        return { command: exePath, args: ["gateway", "start"] }
      }
    }
  } else {
    const home = homedir()
    const localBin = join(home, ".local", "bin", "bytebuddhi")
    if (existsSync(localBin)) {
      return { command: localBin, args: ["gateway", "start"] }
    }
    const bbBin = join(home, ".bytebuddhi", "bin", "bytebuddhi")
    if (existsSync(bbBin)) {
      return { command: bbBin, args: ["gateway", "start"] }
    }
  }

  // Fallback for development repository or PATH execution
  return { command: "uv", args: ["run", "bytebuddhi", "gateway", "start"] }
}

export class ManagedGateway {
  private child: ChildProcess | null = null
  private spawnedByUs = false

  async ensureRunning(origin: string): Promise<boolean> {
    if (!isLocalGateway(origin)) {
      return true
    }

    const alreadyLive = await probeGatewayLive(origin)
    if (alreadyLive) {
      return true
    }

    if (this.child) {
      return waitForGatewayReadiness(origin)
    }

    const { command, args } = findGatewayCommand()
    try {
      this.child = spawn(command, args, {
        windowsHide: true,
        stdio: "ignore",
      })
      this.spawnedByUs = true

      this.child.on("exit", () => {
        this.child = null
        this.spawnedByUs = false
      })

      return await waitForGatewayReadiness(origin)
    } catch (err) {
      console.error("Failed to spawn ByteBuddhi gateway:", err)
      this.child = null
      this.spawnedByUs = false
      return false
    }
  }

  async stop(): Promise<void> {
    if (!this.spawnedByUs || !this.child) {
      return
    }

    const proc = this.child
    this.child = null
    this.spawnedByUs = false

    try {
      proc.kill("SIGTERM")
    } catch {
      // Process may already have terminated
    }
  }
}
