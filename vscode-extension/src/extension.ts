import * as vscode from "vscode";
import { ByteBuddhiApiClient } from "./transport/apiClient";
import { ChatViewProvider } from "./views/chatView";
import { redactSecrets } from "./protocol/redact";

const ACCESS_SECRET = "bytebuddhi.accessToken";
const REFRESH_SECRET = "bytebuddhi.refreshToken";

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const output = vscode.window.createOutputChannel("ByteBuddhi");
  const client = new ByteBuddhiApiClient(
    (input, init) => fetch(input, init),
    () => vscode.workspace.getConfiguration("bytebuddhi").get<string>("serverUrl") || "http://127.0.0.1:8000",
    async () => context.secrets.get(ACCESS_SECRET),
    async () => {
      const refresh = await context.secrets.get(REFRESH_SECRET);
      if (!refresh) {
        return undefined;
      }
      try {
        const tokens = await new ByteBuddhiApiClient(
          (input, init) => fetch(input, init),
          () => vscode.workspace.getConfiguration("bytebuddhi").get<string>("serverUrl") || "http://127.0.0.1:8000",
          async () => refresh,
        ).refresh(refresh);
        await context.secrets.store(ACCESS_SECRET, tokens.accessToken);
        await context.secrets.store(REFRESH_SECRET, tokens.refreshToken);
        return tokens.accessToken;
      } catch {
        await context.secrets.delete(ACCESS_SECRET);
        await context.secrets.delete(REFRESH_SECRET);
        return undefined;
      }
    },
  );

  const chat = new ChatViewProvider(context, client, output);
  context.subscriptions.push(
    output,
    chat,
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, chat),
    vscode.commands.registerCommand("bytebuddhi.signIn", async () => {
      const email = await vscode.window.showInputBox({ prompt: "ByteBuddhi email", ignoreFocusOut: true });
      if (!email) {
        return;
      }
      const password = await vscode.window.showInputBox({
        prompt: "Password",
        password: true,
        ignoreFocusOut: true,
      });
      if (!password) {
        return;
      }
      try {
        const tokens = await client.login(email, password);
        await context.secrets.store(ACCESS_SECRET, tokens.accessToken);
        await context.secrets.store(REFRESH_SECRET, tokens.refreshToken);
        vscode.window.showInformationMessage("Signed in to ByteBuddhi");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Sign-in failed";
        output.appendLine(redactSecrets(message));
        vscode.window.showErrorMessage(message);
      }
    }),
    vscode.commands.registerCommand("bytebuddhi.signOut", async () => {
      await context.secrets.delete(ACCESS_SECRET);
      await context.secrets.delete(REFRESH_SECRET);
      chat.session.clearAuth();
      vscode.window.showInformationMessage("Signed out of ByteBuddhi");
    }),
    vscode.commands.registerCommand("bytebuddhi.openChat", async () => {
      await vscode.commands.executeCommand("bytebuddhi.chat.focus");
    }),
    vscode.commands.registerCommand("bytebuddhi.runTask", async () => {
      const prompt = await vscode.window.showInputBox({
        prompt: "ByteBuddhi task",
        ignoreFocusOut: true,
      });
      if (!prompt) {
        return;
      }
      await vscode.commands.executeCommand("bytebuddhi.chat.focus");
      await chat.runPrompt(prompt);
    }),
    vscode.commands.registerCommand("bytebuddhi.cancelTask", async () => {
      await chat.cancel();
    }),
    vscode.commands.registerCommand("bytebuddhi.showStatus", async () => {
      await chat.showStatus();
    }),
  );
}

export function deactivate(): void {
  // In-flight HTTP is aborted by ChatViewProvider.dispose. The API decides
  // whether a disconnected stream cancels the run.
}
