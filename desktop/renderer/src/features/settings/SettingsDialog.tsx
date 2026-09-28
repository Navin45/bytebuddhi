import { useEffect, useState, type JSX } from "react"

import { isLocalGateway, parseGatewayOrigin } from "../../../../electron/security"
import type { AppState } from "../../state/app-state"
import type { ChatSession } from "../../state/session"

type UpdateState = {
  status: string
  version?: string
  percent?: number
  message?: string
}

export function SettingsDialog({
  session,
  state,
  onClose,
}: {
  session: ChatSession
  state: AppState
  onClose: () => void
}): JSX.Element {
  const [tab, setTab] = useState<"general" | "about">("general")
  const [gatewayUrl, setGatewayUrl] = useState(state.gatewayUrl)
  const [error, setError] = useState("")

  const [appVersion, setAppVersion] = useState("")
  const [platform, setPlatform] = useState("")
  const [gatewayVersion, setGatewayVersion] = useState<string | null>(null)
  const [protocolVersion, setProtocolVersion] = useState<number | null>(null)
  const [updateState, setUpdateState] = useState<UpdateState>({ status: "idle" })
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    if (typeof window !== "undefined" && window.bytebuddhi) {
      window.bytebuddhi.desktop?.getVersion?.().then(setAppVersion).catch(() => undefined)
      window.bytebuddhi.desktop?.getPlatform?.().then(setPlatform).catch(() => undefined)
      window.bytebuddhi.update?.getState?.().then((st) => setUpdateState(st as UpdateState)).catch(() => undefined)
      const unsub = window.bytebuddhi.update?.onState?.((st) => setUpdateState(st as UpdateState))

      window.bytebuddhi.gateway
        ?.request({ method: "GET", path: "/api/v1/health" })
        .then((res) => {
          if (res.status === 200 && res.body && typeof res.body === "object") {
            const b = res.body as Record<string, unknown>
            if (typeof b.version === "string") setGatewayVersion(b.version)
            if (typeof b.protocol_version === "number") setProtocolVersion(b.protocol_version)
          }
        })
        .catch(() => undefined)

      return () => {
        unsub?.()
      }
    }
    return undefined
  }, [])

  const handleCheckUpdate = async (): Promise<void> => {
    setChecking(true)
    try {
      const res = await window.bytebuddhi?.update?.check?.()
      if (res) setUpdateState(res)
    } catch (err) {
      setUpdateState({ status: "error", message: String(err) })
    } finally {
      setChecking(false)
    }
  }

  const handleDownloadUpdate = async (): Promise<void> => {
    try {
      const res = await window.bytebuddhi?.update?.download?.()
      if (res) setUpdateState(res)
    } catch (err) {
      setUpdateState({ status: "error", message: String(err) })
    }
  }

  const handleInstallUpdate = async (): Promise<void> => {
    try {
      await window.bytebuddhi?.update?.install?.()
    } catch (err) {
      setUpdateState({ status: "error", message: String(err) })
    }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog" style={{ minWidth: "320px", maxWidth: "480px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h2 style={{ margin: 0 }}>Settings</h2>
          <div style={{ display: "flex", gap: "0.25rem" }}>
            <button
              type="button"
              className={tab === "general" ? "active" : ""}
              onClick={() => setTab("general")}
              style={{ fontWeight: tab === "general" ? "bold" : "normal" }}
            >
              General
            </button>
            <button
              type="button"
              className={tab === "about" ? "active" : ""}
              onClick={() => setTab("about")}
              style={{ fontWeight: tab === "about" ? "bold" : "normal" }}
            >
              About
            </button>
          </div>
        </div>

        {tab === "general" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const origin = parseGatewayOrigin(gatewayUrl)
              if (!origin) {
                setError("Enter a gateway origin such as http://127.0.0.1:8765.")
                return
              }
              void session.saveSettings({ gatewayUrl: origin })
              onClose()
            }}
          >
            <label>
              Gateway URL
              <input aria-label="Gateway URL" value={gatewayUrl} onChange={(event) => setGatewayUrl(event.target.value)} />
            </label>
            <label>
              Theme
              <select
                aria-label="Theme"
                value={state.theme}
                onChange={(event) => void session.saveSettings({ theme: event.target.value as AppState["theme"] })}
              >
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </label>
            <label>
              Font size
              <input
                aria-label="Font size"
                type="number"
                min={12}
                max={22}
                value={state.fontSize}
                onChange={(event) => void session.saveSettings({ fontSize: Number(event.target.value) })}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={state.autoStartLocalGateway}
                onChange={(event) => void session.saveSettings({ autoStartLocalGateway: event.target.checked })}
              />
              Start the local gateway when this app opens
            </label>
            {state.autoStartLocalGateway && !isLocalGateway(state.gatewayUrl) ? (
              <p>A remote gateway is never started on this computer.</p>
            ) : null}
            {error ? <p className="error">{error}</p> : null}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
              <button type="submit">Save gateway</button>
              <button type="button" onClick={() => void session.signOut()}>Sign out</button>
              <button type="button" onClick={onClose}>Close</button>
            </div>
          </form>
        ) : (
          <div>
            <div style={{ marginBottom: "1rem", lineHeight: "1.6" }}>
              <p><strong>ByteBuddhi Desktop:</strong> {appVersion} {platform ? `(${platform})` : ""}</p>
              <p><strong>Gateway:</strong> {gatewayVersion ? `${gatewayVersion} (connected)` : "Not connected"}</p>
              <p><strong>Protocol Version:</strong> {protocolVersion ?? 1}</p>
              <p style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <strong>Channel:</strong>
                <select
                  value={state.releaseChannel ?? "stable"}
                  onChange={(event) => void session.saveSettings({ releaseChannel: event.target.value as "stable" | "beta" })}
                >
                  <option value="stable">stable</option>
                  <option value="beta">beta / rc</option>
                </select>
              </p>
            </div>

            <div style={{ borderTop: "1px solid var(--line)", paddingTop: "0.75rem", marginBottom: "1rem" }}>
              <h3 style={{ margin: "0 0 0.5rem" }}>Updates</h3>
              {updateState.status === "checking" || checking ? (
                <p>Checking for updates…</p>
              ) : updateState.status === "available" ? (
                <div>
                  <p style={{ color: "var(--accent, #3b82f6)" }}>
                    Update available: <strong>{updateState.version}</strong>
                  </p>
                  <button type="button" onClick={() => void handleDownloadUpdate()}>
                    Download update
                  </button>
                </div>
              ) : updateState.status === "downloading" ? (
                <p>Downloading update: {updateState.percent ?? 0}%</p>
              ) : updateState.status === "ready" ? (
                <div>
                  <p style={{ color: "var(--success, #22c55e)" }}>
                    Update {updateState.version} is downloaded and ready to install.
                  </p>
                  <button type="button" onClick={() => void handleInstallUpdate()}>
                    Restart & install
                  </button>
                </div>
              ) : updateState.status === "error" ? (
                <div>
                  <p className="error">Update check error: {updateState.message}</p>
                  <button type="button" onClick={() => void handleCheckUpdate()}>
                    Retry
                  </button>
                </div>
              ) : (
                <div>
                  <p>ByteBuddhi is up to date.</p>
                  <button type="button" onClick={() => void handleCheckUpdate()}>
                    Check for updates
                  </button>
                </div>
              )}
            </div>

            <button type="button" onClick={onClose}>Close</button>
          </div>
        )}
      </div>
    </div>
  )
}
