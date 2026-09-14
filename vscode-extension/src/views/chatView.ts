import * as vscode from "vscode";
import { ByteBuddhiApiClient, ByteBuddhiApiError } from "../transport/apiClient";
import { parseWebviewMessage, type HostToWebview } from "../protocol/messages";
import { buildPrompt } from "../protocol/prompt";
import { ClientSession } from "../protocol/session";
import { redactSecrets } from "../protocol/redact";
import { matchProjectId } from "../protocol/projects";
import { chatHtml } from "./chatHtml";

export class ChatViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
  public static readonly viewId = "bytebuddhi.chat";
  private view?: vscode.WebviewView;
  private abort?: AbortController;
  readonly session = new ClientSession();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly client: ByteBuddhiApiClient,
    private readonly output: vscode.OutputChannel,
    private readonly hasSession: () => Promise<boolean>,
  ) {
    this.session.modelProvider = context.workspaceState.get<string>("bytebuddhi.modelProvider");
    this.session.modelName = context.workspaceState.get<string>("bytebuddhi.modelName");
  }

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    const nonce = this.nonce();
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.context.extensionUri],
    };
    webviewView.webview.html = chatHtml(nonce, webviewView.webview.cspSource);
    this.disposables.push(
      webviewView.webview.onDidReceiveMessage(async (raw: unknown) => {
        const message = parseWebviewMessage(raw);
        if (!message) {
          this.output.appendLine("Ignored invalid webview message");
          return;
        }
        if (message.type === "ready") {
          this.post({ type: "auth", signedIn: await this.hasSession() });
          this.post({ type: "model", label: this.modelLabel() });
        }
        if (message.type === "send_message") {
          await this.runPrompt(message.prompt);
        }
        if (message.type === "cancel_task") {
          await this.cancel();
        }
        if (message.type === "sign_in") {
          await vscode.commands.executeCommand("bytebuddhi.signIn");
        }
        if (message.type === "sign_in_google") {
          await vscode.commands.executeCommand("bytebuddhi.signInWithGoogle");
        }
        if (message.type === "sign_in_github") {
          await vscode.commands.executeCommand("bytebuddhi.signInWithGitHub");
        }
        if (message.type === "select_model") {
          await this.selectModel();
        }
      }),
    );
  }

  async runPrompt(userText: string): Promise<void> {
    const clientRequestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    if (!this.session.beginRequest(clientRequestId)) {
      vscode.window.showWarningMessage("ByteBuddhi already has a task in progress");
      return;
    }
    this.post({ type: "status", status: "running" });
    this.abort = new AbortController();
    try {
      await this.ensureProject();
      if (!this.session.conversationId) {
        const created = await this.client.createConversation(this.session.projectId);
        this.session.conversationId = created.id;
      }
      const snippet = this.activeSnippet();
      const prompt = buildPrompt(userText, snippet);
      const events = await this.client.sendMessage(
        this.session.conversationId,
        prompt,
        this.abort.signal,
        this.session.modelProvider && this.session.modelName
          ? { provider: this.session.modelProvider, model: this.session.modelName }
          : undefined,
      );
      let answer = "";
      let runId = this.session.runId;
      const tools: string[] = [];
      let terminal: "completed" | "failed" | "cancelled" = "failed";
      for (const event of events) {
        if (event.event === "run_started" && typeof event.data.run_id === "string") {
          runId = event.data.run_id;
          this.session.runId = runId;
        }
        if (event.event === "content" && typeof event.data.content === "string") {
          answer = event.data.content;
        }
        if (event.event === "tool_call" && typeof event.data.name === "string") {
          tools.push(event.data.name);
        }
        if (event.event === "done") {
          terminal = "completed";
        }
        if (event.event === "cancelled") {
          terminal = "cancelled";
        }
        if (event.event === "error") {
          terminal = "failed";
        }
      }
      this.session.complete(terminal, runId, this.session.conversationId);
      this.post({ type: "status", status: terminal });
      if (terminal === "completed") {
        this.post({
          type: "result",
          answer,
          runId,
          conversationId: this.session.conversationId,
          tools,
        });
      } else if (terminal === "cancelled") {
        this.post({ type: "error", message: "Cancelled" });
      } else {
        this.post({ type: "error", message: "Task failed" });
      }
    } catch (error) {
      const aborted = error instanceof Error && error.name === "AbortError";
      this.session.complete(aborted ? "cancelled" : "failed");
      this.post({ type: "status", status: this.session.status });
      const message = aborted
        ? "Cancelled"
        : error instanceof ByteBuddhiApiError
          ? error.message
          : "Request failed";
      this.post({ type: "error", message });
      this.output.appendLine(redactSecrets(message));
    } finally {
      this.abort = undefined;
    }
  }

  async cancel(): Promise<void> {
    this.abort?.abort();
    if (this.session.runId) {
      try {
        await this.client.cancelRun(this.session.runId);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Cancel failed";
        this.output.appendLine(redactSecrets(message));
      }
    }
  }

  async selectModel(): Promise<void> {
    try {
      const catalog = await this.client.listModels();
      const items = catalog.models
        .filter((item) => item.available)
        .map((item) => ({
          label: item.display_name,
          description: `${item.provider}/${item.model}`,
          provider: item.provider,
          model: item.model,
        }));
      if (items.length === 0) {
        vscode.window.showWarningMessage("No available models are configured on the server");
        return;
      }
      const picked = await vscode.window.showQuickPick(items, {
        title: "ByteBuddhi model",
        ignoreFocusOut: true,
      });
      if (!picked) {
        return;
      }
      this.session.modelProvider = picked.provider;
      this.session.modelName = picked.model;
      await this.context.workspaceState.update("bytebuddhi.modelProvider", picked.provider);
      await this.context.workspaceState.update("bytebuddhi.modelName", picked.model);
      this.post({ type: "model", label: this.modelLabel() });
      vscode.window.showInformationMessage(`Using ${picked.provider}/${picked.model}`);
    } catch (error) {
      const message = error instanceof ByteBuddhiApiError ? error.message : "Could not load models";
      vscode.window.showErrorMessage(message);
    }
  }

  private modelLabel(): string {
    return this.session.modelProvider && this.session.modelName
      ? `${this.session.modelProvider}/${this.session.modelName}`
      : "Auto";
  }

  notifyAuthState(signedIn: boolean): void {
    this.post({ type: "auth", signedIn });
  }

  async showStatus(): Promise<void> {
    try {
      const health = await this.client.health();
      vscode.window.showInformationMessage(
        `ByteBuddhi ${health.status} · ui ${this.session.status} · project ${this.session.projectId ?? "(none)"}`,
      );
    } catch {
      vscode.window.showErrorMessage("ByteBuddhi server unavailable");
    }
  }

  dispose(): void {
    this.abort?.abort();
    for (const item of this.disposables) {
      item.dispose();
    }
  }

  private post(message: HostToWebview): void {
    void this.view?.webview.postMessage(message);
  }

  private nonce(): string {
    return [...Array(16)].map(() => Math.floor(Math.random() * 16).toString(16)).join("");
  }

  private activeSnippet() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
      return undefined;
    }
    return {
      path: editor.document.fileName,
      language: editor.document.languageId,
      startLine: editor.selection.start.line + 1,
      endLine: editor.selection.end.line + 1,
      text: editor.document.getText(editor.selection),
    };
  }

  private async ensureProject(): Promise<void> {
    const configured = vscode.workspace.getConfiguration("bytebuddhi").get<string>("project")?.trim();
    if (configured) {
      this.session.bindProject(configured);
      return;
    }
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!folder) {
      this.session.bindProject(undefined);
      return;
    }
    const projects = await this.client.listProjects();
    this.session.bindProject(matchProjectId(folder, projects));
  }
}
