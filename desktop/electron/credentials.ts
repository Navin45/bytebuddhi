import { safeStorage } from "electron"
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { dirname } from "node:path"

export type StoredCredentials = {
  accessToken: string
  refreshToken: string
}

export class CredentialVault {
  constructor(private readonly filePath: string) {}

  save(credentials: StoredCredentials): void {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("Secure credential storage is unavailable on this desktop.")
    }
    mkdirSync(dirname(this.filePath), { recursive: true })
    writeFileSync(this.filePath, safeStorage.encryptString(JSON.stringify(credentials)))
  }

  load(): StoredCredentials | null {
    let encrypted: Buffer
    try {
      encrypted = readFileSync(this.filePath)
    } catch {
      return null
    }
    if (!safeStorage.isEncryptionAvailable()) return null
    try {
      const parsed: unknown = JSON.parse(safeStorage.decryptString(encrypted))
      if (!isCredentials(parsed)) return null
      return parsed
    } catch {
      return null
    }
  }

  clear(): void {
    rmSync(this.filePath, { force: true })
  }
}

function isCredentials(value: unknown): value is StoredCredentials {
  if (!value || typeof value !== "object") return false
  const record = value as Record<string, unknown>
  return typeof record.accessToken === "string" && typeof record.refreshToken === "string" && record.accessToken.length > 0
}
