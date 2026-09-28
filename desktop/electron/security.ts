/** URL and path guards. No Electron or Node APIs, so tests can import this module. */

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost"])

export function parseGatewayOrigin(raw: string): string | null {
  let url: URL
  try {
    url = new URL(raw.trim())
  } catch {
    return null
  }
  if (url.username || url.password || url.search || url.hash) return null
  if (url.pathname !== "/" && url.pathname !== "") return null
  if (url.protocol !== "http:" && url.protocol !== "https:") return null
  return url.origin
}

export function isLocalGateway(origin: string): boolean {
  try {
    return LOCAL_HOSTS.has(new URL(origin).hostname)
  } catch {
    return false
  }
}

export function isSafeExternalUrl(raw: string): boolean {
  let url: URL
  try {
    url = new URL(raw.trim())
  } catch {
    return false
  }
  if (url.username || url.password) return false
  if (url.protocol === "https:") return true
  return url.protocol === "http:" && LOCAL_HOSTS.has(url.hostname)
}

export function isAllowedApiPath(path: string): boolean {
  if (!path.startsWith("/api/v1/") || path.includes("..") || path.includes("\\") || path.includes("://")) {
    return false
  }
  return !path.includes("\n") && !path.includes("\r")
}

export function websocketUrl(origin: string, path: string): string {
  const url = new URL(path, origin)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  return url.toString()
}

export function isValidRunId(runId: string): boolean {
  return /^[A-Za-z0-9_-]{1,80}$/.test(runId)
}
