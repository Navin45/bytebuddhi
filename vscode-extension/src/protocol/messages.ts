export type UiStatus =
  | "idle"
  | "connecting"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

export type HostToWebview =
  | { type: "ready" }
  | { type: "status"; status: UiStatus }
  | { type: "result"; answer: string; runId?: string; conversationId?: string; tools: string[] }
  | { type: "error"; message: string }
  | { type: "history"; messages: Array<{ role: "user" | "assistant"; content: string }> };

export type WebviewToHost =
  | { type: "ready" }
  | { type: "send_message"; prompt: string }
  | { type: "cancel_task" };

const WEBVIEW_TYPES = new Set(["ready", "send_message", "cancel_task"]);

const FORBIDDEN_KEYS = new Set([
  "user_id",
  "userId",
  "approved_actions",
  "approvedActions",
  "approval_granted",
  "tool_permissions",
  "workspace_path_override",
  "password",
  "access_token",
  "refresh_token",
  "authorization",
]);

export function parseWebviewMessage(raw: unknown): WebviewToHost | undefined {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  const record = raw as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (FORBIDDEN_KEYS.has(key)) {
      return undefined;
    }
  }
  const type = record.type;
  if (typeof type !== "string" || !WEBVIEW_TYPES.has(type)) {
    return undefined;
  }
  if (type === "ready" || type === "cancel_task") {
    return { type };
  }
  if (type === "send_message") {
    if (typeof record.prompt !== "string") {
      return undefined;
    }
    const prompt = record.prompt.trim();
    if (!prompt) {
      return undefined;
    }
    return { type: "send_message", prompt };
  }
  return undefined;
}
