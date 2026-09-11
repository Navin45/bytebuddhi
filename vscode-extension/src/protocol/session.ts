import type { UiStatus } from "./messages";

export class ClientSession {
  conversationId?: string;
  runId?: string;
  projectId?: string;
  status: UiStatus = "idle";
  inflight = false;
  lastClientRequestId?: string;

  bindProject(projectId: string | undefined): void {
    if (this.projectId !== projectId) {
      this.resetConversation();
      this.projectId = projectId;
    }
  }

  beginRequest(clientRequestId: string): boolean {
    if (this.inflight) {
      return false;
    }
    this.inflight = true;
    this.lastClientRequestId = clientRequestId;
    this.status = "running";
    return true;
  }

  complete(status: UiStatus, runId?: string, conversationId?: string): void {
    this.inflight = false;
    this.status = status;
    if (runId) {
      this.runId = runId;
    }
    if (conversationId) {
      this.conversationId = conversationId;
    }
  }

  resetConversation(): void {
    this.conversationId = undefined;
    this.runId = undefined;
    this.inflight = false;
    this.lastClientRequestId = undefined;
    this.status = "idle";
  }

  clearAuth(): void {
    this.resetConversation();
    this.projectId = undefined;
  }
}
