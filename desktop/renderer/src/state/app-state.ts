export type ConnectionState =
  | "gateway_starting"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "authentication_required"

export type RunStatus =
  | "idle"
  | "queued"
  | "running"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"

export type TranscriptItem = {
  id: string
  kind: "user" | "assistant" | "tool" | "notice"
  title: string
  body: string
  detail: string
  runId: string | null
  streaming: boolean
  toolOpen: boolean
}

export type PendingApproval = {
  runId: string
  action: string
  riskLevel: string
  reason: string
}

export type AppState = {
  connection: ConnectionState
  reconnectAttempt: number
  reconnectLimit: number
  signedIn: boolean
  projects: { id: string; name: string }[]
  conversations: { id: string; title: string; projectId: string | null; updatedAt: string }[]
  activeProjectId: string | null
  activeConversationId: string | null
  activeRunId: string | null
  runStatus: RunStatus
  submitting: boolean
  cancelSent: boolean
  lastSequence: number
  selectedProvider: string | null
  selectedModel: string | null
  models: { provider: string; model: string; displayName: string; capabilities: string[]; available: boolean }[]
  transcript: TranscriptItem[]
  composer: string
  error: string | null
  theme: "light" | "dark" | "system"
  fontSize: number
  gatewayUrl: string
  autoStartLocalGateway: boolean
  releaseChannel: "stable" | "beta"
  stickToBottom: boolean
  diagnostics: string | null
  pendingApproval: PendingApproval | null
}

export const RECONNECT_LIMIT = 3

export function initialState(): AppState {
  return {
    connection: "connecting",
    reconnectAttempt: 0,
    reconnectLimit: RECONNECT_LIMIT,
    signedIn: false,
    projects: [],
    conversations: [],
    activeProjectId: null,
    activeConversationId: null,
    activeRunId: null,
    runStatus: "idle",
    submitting: false,
    cancelSent: false,
    lastSequence: 0,
    selectedProvider: null,
    selectedModel: null,
    models: [],
    transcript: [],
    composer: "",
    error: null,
    theme: "system",
    fontSize: 16,
    gatewayUrl: "http://127.0.0.1:8765",
    autoStartLocalGateway: false,
    releaseChannel: "stable",
    stickToBottom: true,
    diagnostics: null,
    pendingApproval: null,
  }
}

export function runActive(state: AppState): boolean {
  return state.submitting || state.runStatus === "queued" || state.runStatus === "running" || state.runStatus === "cancel_requested"
}

export function visibleConversations(state: AppState): AppState["conversations"] {
  if (!state.activeProjectId) return state.conversations.filter((item) => item.projectId === null)
  return state.conversations.filter((item) => item.projectId === state.activeProjectId)
}

export function connectionLabel(state: AppState): string {
  if (state.connection === "reconnecting") return `RECONNECTING ${state.reconnectAttempt}/${state.reconnectLimit}`
  const labels: Record<ConnectionState, string> = {
    gateway_starting: "GATEWAY STARTING",
    connecting: "CONNECTING",
    connected: "CONNECTED",
    reconnecting: "RECONNECTING",
    disconnected: "DISCONNECTED",
    authentication_required: "SIGN IN REQUIRED",
  }
  return labels[state.connection]
}

export function runLabel(status: RunStatus): string {
  const labels: Record<RunStatus, string> = {
    idle: "IDLE",
    queued: "QUEUED",
    running: "RUNNING",
    cancel_requested: "CANCEL REQUESTED",
    completed: "COMPLETED",
    failed: "FAILED",
    cancelled: "CANCELLED",
    interrupted: "INTERRUPTED",
  }
  return labels[status]
}
