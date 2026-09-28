import { useEffect, useMemo, useState, useSyncExternalStore, type JSX } from "react"

import { createDesktopClient } from "./api/ipc"
import { Composer } from "./components/Composer"
import { ConnectionIndicator } from "./components/ConnectionIndicator"
import { ConversationView } from "./components/ConversationView"
import { Sidebar } from "./components/Sidebar"
import { StatusBar } from "./components/StatusBar"
import { AuthScreen } from "./features/auth/AuthScreen"
import { SettingsDialog } from "./features/settings/SettingsDialog"
import { runActive } from "./state/app-state"
import { ChatSession } from "./state/session"
import "./styles/app.css"

export function App(): JSX.Element {
  const session = useMemo(() => new ChatSession(createDesktopClient(), window.bytebuddhi), [])
  const state = useSyncExternalStore(session.subscribe.bind(session), session.getState.bind(session))
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    void session.bootstrap()
    return () => session.stop()
  }, [session])

  useEffect(() => {
    const theme = state.theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : state.theme
    document.documentElement.dataset.theme = theme === "system" ? "light" : theme
    document.documentElement.style.setProperty("--font-size", `${state.fontSize}px`)
  }, [state.theme, state.fontSize])

  if (!state.signedIn) return <AuthScreen session={session} />

  return (
    <div className="shell">
      <header className="topbar">
        <strong>ByteBuddhi</strong>
        <ConnectionIndicator state={state} />
        <label>
          Model
          <select
            aria-label="Model"
            value={state.selectedModel ? `${state.selectedProvider}::${state.selectedModel}` : ""}
            onChange={(event) => {
              const [provider, model] = event.target.value.split("::")
              if (provider && model) void session.selectModel(provider, model)
            }}
          >
            <option value="">Server default</option>
            {state.models.map((model) => (
              <option key={`${model.provider}::${model.model}`} value={`${model.provider}::${model.model}`}>
                {model.displayName} ({model.provider})
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => setSidebarOpen((open) => !open)}>
          {sidebarOpen ? "Hide sidebar" : "Show sidebar"}
        </button>
        <button type="button" onClick={() => setSettingsOpen(true)}>Settings</button>
      </header>
      <div className="workspace">
        <Sidebar session={session} state={state} open={sidebarOpen} />
        <ConversationView state={state} onStickToBottom={(stick) => session.setStickToBottom(stick)} />
      </div>
      {state.pendingApproval ? (
        <div className="approval-banner" role="alert" style={{ margin: "8px 16px", padding: "12px", background: "var(--surface-raised, #24292e)", borderRadius: "6px", border: "1px solid var(--accent, #e36209)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong>Approval Required:</strong> Action <code>{state.pendingApproval.action}</code> (risk: {state.pendingApproval.riskLevel})
            <p style={{ margin: "4px 0 0", fontSize: "0.9em", opacity: 0.85 }}>{state.pendingApproval.reason}</p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button type="button" style={{ background: "#28a745", color: "#fff", border: "none", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" }} onClick={() => void session.approveTool(state.pendingApproval!.action)}>
              Approve
            </button>
            <button type="button" style={{ background: "#cb2431", color: "#fff", border: "none", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" }} onClick={() => void session.rejectTool(state.pendingApproval!.action)}>
              Reject
            </button>
          </div>
        </div>
      ) : null}
      {state.error ? <p className="error" role="alert">{state.error}</p> : null}
      <Composer
        value={state.composer}
        disabled={runActive(state)}
        running={runActive(state)}
        onChange={(value) => session.setComposer(value)}
        onSend={() => void session.send(state.composer)}
        onStop={() => void session.cancel()}
      />
      <StatusBar state={state} />
      {settingsOpen ? <SettingsDialog session={session} state={state} onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  )
}
