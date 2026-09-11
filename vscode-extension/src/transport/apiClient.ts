import { parseSseStream, type SseEvent } from "../protocol/sse";

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

export interface ApiProject {
  id: string;
  name: string;
  local_path?: string | null;
}

export interface FetchLike {
  (input: string, init?: RequestInit): Promise<Response>;
}

export class ByteBuddhiApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ByteBuddhiApiError";
  }
}

export class ByteBuddhiApiClient {
  constructor(
    private readonly fetchImpl: FetchLike,
    private readonly getBaseUrl: () => string,
    private readonly getAccessToken: () => Promise<string | undefined>,
    private readonly onUnauthorized?: () => Promise<string | undefined>,
  ) {}

  async health(): Promise<{ status: string }> {
    const response = await this.fetchImpl(`${this.apiRoot()}/health`, { method: "GET" });
    if (!response.ok) {
      throw new ByteBuddhiApiError("Server unavailable", response.status);
    }
    return (await response.json()) as { status: string };
  }

  async login(email: string, password: string): Promise<TokenPair> {
    const response = await this.fetchImpl(`${this.apiRoot()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      throw new ByteBuddhiApiError("Authentication failed", response.status);
    }
    const body = (await response.json()) as { access_token: string; refresh_token: string };
    return { accessToken: body.access_token, refreshToken: body.refresh_token };
  }

  async refresh(refreshToken: string): Promise<TokenPair> {
    const response = await this.fetchImpl(`${this.apiRoot()}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      throw new ByteBuddhiApiError("Session expired", response.status);
    }
    const body = (await response.json()) as { access_token: string; refresh_token: string };
    return { accessToken: body.access_token, refreshToken: body.refresh_token };
  }

  async listProjects(): Promise<ApiProject[]> {
    const response = await this.authorized("/projects");
    return (await response.json()) as ApiProject[];
  }

  async createConversation(projectId?: string): Promise<{ id: string }> {
    const response = await this.authorized("/chat/conversations", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId ?? null, title: "VS Code" }),
    });
    return (await response.json()) as { id: string };
  }

  async sendMessage(
    conversationId: string,
    content: string,
    signal?: AbortSignal,
  ): Promise<SseEvent[]> {
    const response = await this.authorized(
      `/chat/conversations/${conversationId}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ content }),
        signal,
      },
    );
    const text = await response.text();
    return parseSseStream(text);
  }

  async cancelRun(runId: string): Promise<void> {
    const response = await this.authorized(`/agent/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
    if (response.status !== 202 && !response.ok) {
      throw new ByteBuddhiApiError("Cancel failed", response.status);
    }
  }

  private apiRoot(): string {
    return `${this.getBaseUrl().replace(/\/+$/, "")}/api/v1`;
  }

  private async authorized(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
    const token = await this.getAccessToken();
    if (!token) {
      throw new ByteBuddhiApiError("Not signed in", 401);
    }
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await this.fetchImpl(`${this.apiRoot()}${path}`, { ...init, headers });
    if (response.status === 401 && !retried && this.onUnauthorized) {
      const refreshed = await this.onUnauthorized();
      if (refreshed) {
        return this.authorized(path, init, true);
      }
    }
    if (!response.ok && response.status !== 202) {
      throw new ByteBuddhiApiError(this.safeStatusMessage(response.status), response.status);
    }
    return response;
  }

  private safeStatusMessage(status: number): string {
    if (status === 401) {
      return "Authentication expired";
    }
    if (status === 403) {
      return "Not authorized";
    }
    if (status === 404) {
      return "Not found";
    }
    if (status >= 500) {
      return "Server error";
    }
    return "Request failed";
  }
}
