import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { isAllowedApiPath, isLocalGateway, isSafeExternalUrl, parseGatewayOrigin } from "../../electron/security"

describe("desktop security guards", () => {
  it("accepts gateway origins and rejects embedded credentials", () => {
    expect(parseGatewayOrigin("http://127.0.0.1:8765")).toBe("http://127.0.0.1:8765")
    expect(parseGatewayOrigin("https://gateway.example")).toBe("https://gateway.example")
    expect(parseGatewayOrigin("https://user:secret@gateway.example")).toBeNull()
    expect(parseGatewayOrigin("javascript:alert(1)")).toBeNull()
    expect(isLocalGateway("http://127.0.0.1:8765")).toBe(true)
    expect(isLocalGateway("https://gateway.example")).toBe(false)
  })

  it("rejects unsafe external URLs", () => {
    expect(isSafeExternalUrl("https://example.com/docs")).toBe(true)
    expect(isSafeExternalUrl("http://127.0.0.1:8765/api/v1/auth/google/login?client=cli")).toBe(true)
    expect(isSafeExternalUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeExternalUrl("file:///tmp/secret")).toBe(false)
    expect(isSafeExternalUrl("http://gateway.example")).toBe(false)
  })

  it("limits gateway calls to the versioned API", () => {
    expect(isAllowedApiPath("/api/v1/runs")).toBe(true)
    expect(isAllowedApiPath("/api/v1/../secret")).toBe(false)
    expect(isAllowedApiPath("https://evil.example")).toBe(false)
  })

  it("keeps the renderer free of Node integration and token storage", () => {
    const renderer = readTree(join(import.meta.dirname, "../../renderer/src"))
    const preload = readFileSync(join(import.meta.dirname, "../../electron/preload.ts"), "utf8")
    const windows = readFileSync(join(import.meta.dirname, "../../electron/windows.ts"), "utf8")
    expect(renderer).not.toContain("localStorage")
    expect(renderer).not.toContain("require(")
    expect(renderer).not.toContain("child_process")
    expect(preload).not.toContain("require(")
    expect(preload).not.toContain("child_process")
    expect(windows).toContain("nodeIntegration: false")
    expect(windows).toContain("contextIsolation: true")
    expect(windows).toContain("sandbox: true")
    expect(windows).toContain("webSecurity: true")
  })
})

function readTree(directory: string): string {
  return readdirSync(directory)
    .map((name) => {
      const path = join(directory, name)
      return statSync(path).isDirectory() ? readTree(path) : readFileSync(path, "utf8")
    })
    .join("\n")
}
