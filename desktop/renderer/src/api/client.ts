import type { RunEventPage } from "../generated/contracts"
import { GatewayConnectionError, GatewayRequestError, messageForStatus } from "./errors"
import { validateRunEventPage } from "./validate"

export type GatewayCall = {
  method: string
  path: string
  body?: unknown
  headers?: Record<string, string>
}

export type GatewayResult = { status: number; body: unknown }

export interface GatewayTransport {
  request(call: GatewayCall): Promise<GatewayResult>
  readRunSocket(runId: string, afterSequence: number, signal: AbortSignal): AsyncIterable<unknown>
}

export type Project = {
  id: string
  name: string
}

export type Conversation = {
  id: string
  title: string
  projectId: string | null
  updatedAt: string
}

export type ChatMessage = {
  id: string
  role: string
  content: string
}

export type ModelDescriptor = {
  provider: string
  model: string
  displayName: string
  capabilities: string[]
  available: boolean
}

export type ModelCatalog = {
  defaultProvider: string
  defaultModel: string
  models: ModelDescriptor[]
}

export type RunCreateResult = {
  runId: string
  conversationId: string | null
  status: string
}

export class GatewayClient {
  constructor(private readonly transport: GatewayTransport) {}

  health(): Promise<void> {
    return this.expectOk("GET", "/api/v1/health/live")
  }

  readiness(): Promise<void> {
    return this.expectOk("GET", "/api/v1/health/ready")
  }

  async listProjects(): Promise<Project[]> {
    const body = await this.json("GET", "/api/v1/projects")
    if (!Array.isArray(body)) throw new GatewayRequestError(502, "The gateway returned an unexpected project list.")
    return body.flatMap((item) => {
      const project = asRecord(item)
      if (!project || typeof project.id !== "string" || typeof project.name !== "string") return []
      return [{ id: project.id, name: project.name }]
    })
  }

  async listConversations(): Promise<Conversation[]> {
    const body = await this.json("GET", "/api/v1/chat/conversations")
    if (!Array.isArray(body)) throw new GatewayRequestError(502, "The gateway returned an unexpected conversation list.")
    return body.flatMap((item) => {
      const conversation = asRecord(item)
      if (!conversation || typeof conversation.id !== "string") return []
      return [
        {
          id: conversation.id,
          title: typeof conversation.title === "string" && conversation.title ? conversation.title : "Untitled",
          projectId: typeof conversation.project_id === "string" ? conversation.project_id : null,
          updatedAt: typeof conversation.updated_at === "string" ? conversation.updated_at : "",
        },
      ]
    })
  }

  async listModels(): Promise<ModelCatalog> {
    const body = asRecord(await this.json("GET", "/api/v1/models"))
    if (!body || !Array.isArray(body.models)) {
      throw new GatewayRequestError(502, "The gateway returned an unexpected model catalog.")
    }
    return {
      defaultProvider: typeof body.default_provider === "string" ? body.default_provider : "",
      defaultModel: typeof body.default_model === "string" ? body.default_model : "",
      models: body.models.flatMap((item) => {
        const model = asRecord(item)
        if (!model || typeof model.provider !== "string" || typeof model.model !== "string") return []
        return [
          {
            provider: model.provider,
            model: model.model,
            displayName: typeof model.display_name === "string" ? model.display_name : model.model,
            capabilities: Array.isArray(model.capabilities) ? model.capabilities.filter((entry) => typeof entry === "string") : [],
            available: model.available !== false,
          },
        ]
      }),
    }
  }

  async getMessages(conversationId: string): Promise<ChatMessage[]> {
    const body = await this.json("GET", `/api/v1/chat/conversations/${encodeURIComponent(conversationId)}/messages?limit=200`)
    if (!Array.isArray(body)) throw new GatewayRequestError(502, "The gateway returned an unexpected message list.")
    return body.flatMap((item) => {
      const message = asRecord(item)
      if (!message || typeof message.id !== "string" || typeof message.role !== "string" || typeof message.content !== "string") {
        return []
      }
      return [{ id: message.id, role: message.role, content: message.content }]
    })
  }

  async createConversation(projectId: string | null, title: string): Promise<Conversation> {
    const body = asRecord(
      await this.json("POST", "/api/v1/chat/conversations", { project_id: projectId, title }),
    )
    if (!body || typeof body.id !== "string") throw new GatewayRequestError(502, "The gateway returned an unexpected conversation.")
    return {
      id: body.id,
      title: typeof body.title === "string" && body.title ? body.title : title,
      projectId: typeof body.project_id === "string" ? body.project_id : projectId,
      updatedAt: typeof body.updated_at === "string" ? body.updated_at : "",
    }
  }

  async renameConversation(conversationId: string, title: string): Promise<void> {
    await this.json("PATCH", `/api/v1/chat/conversations/${encodeURIComponent(conversationId)}`, { title })
  }

  async createRun(input: {
    prompt: string
    projectId: string | null
    conversationId: string | null
    modelProvider: string | null
    modelName: string | null
    idempotencyKey: string
  }): Promise<RunCreateResult> {
    const payload: Record<string, unknown> = {
      prompt: input.prompt,
      project_id: input.projectId,
      conversation_id: input.conversationId,
    }
    if (input.modelProvider && input.modelName) {
      payload.model = { provider: input.modelProvider, model: input.modelName }
    }
    const body = asRecord(
      await this.json("POST", "/api/v1/runs", payload, { "Idempotency-Key": input.idempotencyKey }),
    )
    if (!body || typeof body.run_id !== "string") throw new GatewayRequestError(502, "The gateway returned an unexpected run.")
    return {
      runId: body.run_id,
      conversationId: typeof body.conversation_id === "string" ? body.conversation_id : input.conversationId,
      status: typeof body.status === "string" ? body.status : "queued",
    }
  }

  async cancelRun(runId: string): Promise<void> {
    await this.json("POST", `/api/v1/runs/${encodeURIComponent(runId)}/cancel`)
  }

  async submitApproval(runId: string, action: string, decision: "approved" | "rejected"): Promise<void> {
    await this.json("POST", `/api/v1/runs/${encodeURIComponent(runId)}/approval`, { action, decision })
  }

  async getRunEvents(runId: string, afterSequence: number): Promise<RunEventPage> {
    const body = await this.json(
      "GET",
      `/api/v1/runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}&limit=200`,
    )
    const page = validateRunEventPage(body)
    if (!page) throw new GatewayRequestError(502, "The gateway returned an unexpected event page.")
    return page
  }

  readRunSocket(runId: string, afterSequence: number, signal: AbortSignal): AsyncIterable<unknown> {
    return this.transport.readRunSocket(runId, afterSequence, signal)
  }

  private async expectOk(method: string, path: string): Promise<void> {
    const result = await this.transport.request({ method, path })
    if (result.status === 0) throw new GatewayConnectionError()
    if (result.status >= 400) throw new GatewayRequestError(result.status, messageForStatus(result.status, result.body))
  }

  private async json(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<unknown> {
    const result = await this.transport.request({ method, path, body, headers })
    if (result.status === 0) throw new GatewayConnectionError(messageForStatus(0, result.body))
    if (result.status >= 400) throw new GatewayRequestError(result.status, messageForStatus(result.status, result.body))
    return result.body
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}
