import type { ChatMessage, Conversation, GatewayClient, ModelDescriptor, Project } from "../api/client"
import { humanizeGatewayError } from "../api/errors"
import {
  initialState,
  runActive,
  visibleConversations,
  type AppState,
  type ConnectionState,
  type TranscriptItem,
} from "./app-state"
import { reduceRunEvent, withUserMessage } from "./reducer"
import { RunStreamController, type StreamStatus } from "./stream"

export type DesktopSettings = {
  gatewayUrl: string
  theme: AppState["theme"]
  fontSize: number
  autoStartLocalGateway: boolean
  modelProvider: string | null
  modelName: string | null
  releaseChannel?: "stable" | "beta"
}

export type DesktopBridge = {
  auth: {
    status(): Promise<{ signedIn: boolean }>
    start(provider: "google" | "github"): Promise<void>
    exchange(code: string): Promise<void>
    signOut(): Promise<void>
  }
  settings: {
    load(): Promise<DesktopSettings>
    save(patch: Partial<DesktopSettings>): Promise<DesktopSettings>
  }
}

export class ChatSession {
  state: AppState = initialState()
  readonly createdRunIds: string[] = []
  private readonly listeners = new Set<() => void>()
  private controller: RunStreamController | null = null

  constructor(
    private readonly client: GatewayClient,
    private readonly bridge: DesktopBridge,
  ) {}

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getState(): AppState {
    return this.state
  }

  async bootstrap(): Promise<void> {
    const settings = await this.bridge.settings.load()
    const auth = await this.bridge.auth.status()
    this.commit({
      ...this.state,
      ...settingsFrom(settings),
      signedIn: auth.signedIn,
      connection: auth.signedIn ? "connecting" : "authentication_required",
    })
    if (!auth.signedIn) return
    await this.loadWorkspace()
  }

  async send(text: string): Promise<void> {
    const prompt = text.trim()
    if (!prompt || runActive(this.state)) return
    const itemId = `user-${crypto.randomUUID()}`
    this.commit({ ...withUserMessage(this.state, prompt, itemId), composer: "" })
    try {
      const conversationId = await this.ensureConversation(prompt)
      const created = await this.client.createRun({
        prompt,
        projectId: this.state.activeProjectId,
        conversationId,
        modelProvider: this.state.selectedProvider,
        modelName: this.state.selectedModel,
        idempotencyKey: crypto.randomUUID(),
      })
      this.createdRunIds.push(created.runId)
      this.commit({
        ...this.state,
        activeRunId: created.runId,
        activeConversationId: created.conversationId,
        submitting: true,
        cancelSent: false,
        lastSequence: 0,
        error: null,
      })
      await this.follow(created.runId)
    } catch (error) {
      this.commit({
        ...this.state,
        transcript: this.state.transcript.filter((item) => item.id !== itemId),
        submitting: false,
        composer: prompt,
        error: humanizeGatewayError(error),
      })
    }
  }

  async cancel(): Promise<void> {
    if (!this.state.activeRunId || !runActive(this.state) || this.state.cancelSent) return
    const runId = this.state.activeRunId
    this.commit({ ...this.state, cancelSent: true })
    try {
      await this.client.cancelRun(runId)
    } catch (error) {
      this.commit({ ...this.state, cancelSent: false, error: humanizeGatewayError(error) })
    }
  }

  async approveTool(action: string): Promise<void> {
    const runId = this.state.pendingApproval?.runId || this.state.activeRunId
    if (!runId) return
    try {
      await this.client.submitApproval(runId, action, "approved")
      this.commit({ ...this.state, pendingApproval: null })
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async rejectTool(action: string): Promise<void> {
    const runId = this.state.pendingApproval?.runId || this.state.activeRunId
    if (!runId) return
    try {
      await this.client.submitApproval(runId, action, "rejected")
      this.commit({ ...this.state, pendingApproval: null })
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async selectProject(projectId: string): Promise<void> {
    if (runActive(this.state)) {
      this.commit({ ...this.state, error: "Wait for the current run to finish before changing projects." })
      return
    }
    if (projectId === this.state.activeProjectId) return
    this.commit({
      ...this.state,
      activeProjectId: projectId,
      activeConversationId: null,
      transcript: [],
      activeRunId: null,
      runStatus: "idle",
      lastSequence: 0,
      error: null,
    })
    const first = visibleConversations(this.state)[0]
    if (first) await this.openConversation(first.id)
  }

  async openConversation(conversationId: string): Promise<void> {
    if (runActive(this.state)) {
      this.commit({ ...this.state, error: "Wait for the current run to finish before changing conversations." })
      return
    }
    try {
      const messages = await this.client.getMessages(conversationId)
      this.commit({
        ...this.state,
        activeConversationId: conversationId,
        transcript: historyItems(messages),
        activeRunId: null,
        runStatus: "idle",
        lastSequence: 0,
        error: null,
      })
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async newConversation(): Promise<void> {
    if (runActive(this.state)) return
    try {
      const created = await this.client.createConversation(this.state.activeProjectId, "New conversation")
      this.commit({
        ...this.state,
        conversations: [created, ...this.state.conversations],
        activeConversationId: created.id,
        transcript: [],
        activeRunId: null,
        runStatus: "idle",
        lastSequence: 0,
      })
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async renameConversation(conversationId: string, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    try {
      await this.client.renameConversation(conversationId, trimmed)
      this.commit({
        ...this.state,
        conversations: this.state.conversations.map((item) => (item.id === conversationId ? { ...item, title: trimmed } : item)),
      })
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async selectModel(provider: string, model: string): Promise<void> {
    const chosen = this.state.models.find((item) => item.provider === provider && item.model === model)
    if (!chosen) {
      this.commit({ ...this.state, error: "That model is not available." })
      return
    }
    this.commit({ ...this.state, selectedProvider: provider, selectedModel: model, error: null })
    await this.bridge.settings.save({ modelProvider: provider, modelName: model })
  }

  setComposer(value: string): void {
    this.commit({ ...this.state, composer: value })
  }

  setStickToBottom(stickToBottom: boolean): void {
    this.commit({ ...this.state, stickToBottom })
  }

  async signIn(provider: "google" | "github"): Promise<void> {
    await this.bridge.auth.start(provider)
  }

  async exchange(code: string): Promise<void> {
    try {
      await this.bridge.auth.exchange(code)
      this.commit({ ...this.state, signedIn: true, error: null, connection: "connecting" })
      await this.loadWorkspace()
    } catch (error) {
      this.commit({ ...this.state, error: humanizeGatewayError(error) })
    }
  }

  async signOut(): Promise<void> {
    this.stop()
    await this.bridge.auth.signOut()
    this.commit({ ...initialState(), connection: "authentication_required", gatewayUrl: this.state.gatewayUrl })
  }

  async saveSettings(patch: Partial<DesktopSettings>): Promise<void> {
    if (runActive(this.state) && patch.gatewayUrl && patch.gatewayUrl !== this.state.gatewayUrl) {
      this.commit({ ...this.state, error: "Wait for the current run to finish before changing the gateway." })
      return
    }
    const saved = await this.bridge.settings.save(patch)
    this.commit({ ...this.state, ...settingsFrom(saved), error: null })
  }

  stop(): void {
    this.controller?.stop()
    this.controller = null
  }

  private async loadWorkspace(): Promise<void> {
    try {
      await this.client.readiness()
      const [projects, conversations, catalog] = await Promise.all([
        this.client.listProjects(),
        this.client.listConversations(),
        this.client.listModels(),
      ])
      const projectId = this.state.activeProjectId ?? projects[0]?.id ?? null
      const draft = {
        ...this.state,
        connection: "connected" as ConnectionState,
        signedIn: true,
        projects,
        conversations,
        models: catalog.models,
        activeProjectId: projectId,
        error: null,
      }
      const visible = visibleConversations(draft)
      const conversationId = visible[0]?.id ?? null
      this.commit({ ...draft, activeConversationId: conversationId })
      if (
        this.state.selectedModel &&
        !catalog.models.some((item) => item.provider === this.state.selectedProvider && item.model === this.state.selectedModel)
      ) {
        this.commit({ ...this.state, error: "The saved model is no longer available. Choose another model before sending." })
      }
      if (conversationId) {
        const messages = await this.client.getMessages(conversationId)
        this.commit({ ...this.state, transcript: historyItems(messages) })
      }
    } catch (error) {
      this.commit({ ...this.state, connection: "disconnected", error: humanizeGatewayError(error) })
    }
  }

  private async ensureConversation(prompt: string): Promise<string | null> {
    if (this.state.activeConversationId) return this.state.activeConversationId
    const created = await this.client.createConversation(this.state.activeProjectId, prompt.slice(0, 60) || "New conversation")
    this.commit({
      ...this.state,
      conversations: [created, ...this.state.conversations],
      activeConversationId: created.id,
    })
    return created.id
  }

  private async follow(runId: string): Promise<void> {
    this.controller?.stop()
    const controller = new RunStreamController(this.client)
    this.controller = controller
    await controller.follow(
      runId,
      (event) => this.commit(reduceRunEvent(this.state, event)),
      (connection: StreamStatus, attempt: number) => {
        const mapped: ConnectionState = connection === "connected" ? "connected" : connection
        this.commit({ ...this.state, connection: mapped, reconnectAttempt: attempt })
      },
      (message) => this.commit({ ...this.state, diagnostics: message }),
    )
  }

  private commit(state: AppState): void {
    this.state = state
    for (const listener of this.listeners) listener()
  }
}

function settingsFrom(settings: DesktopSettings): Pick<
  AppState,
  "gatewayUrl" | "theme" | "fontSize" | "autoStartLocalGateway" | "selectedProvider" | "selectedModel" | "releaseChannel"
> {
  return {
    gatewayUrl: settings.gatewayUrl,
    theme: settings.theme,
    fontSize: settings.fontSize,
    autoStartLocalGateway: settings.autoStartLocalGateway,
    selectedProvider: settings.modelProvider,
    selectedModel: settings.modelName,
    releaseChannel: settings.releaseChannel ?? "stable",
  }
}

function historyItems(messages: ChatMessage[]): TranscriptItem[] {
  return messages.map((message) => ({
    id: `hist-${message.id}`,
    kind: message.role === "assistant" ? "assistant" : message.role === "user" ? "user" : "notice",
    title: message.role === "assistant" ? "ByteBuddhi" : message.role === "user" ? "You" : message.role,
    body: message.content,
    detail: "",
    runId: null,
    streaming: false,
    toolOpen: false,
  }))
}

export type { Conversation, ModelDescriptor, Project }
