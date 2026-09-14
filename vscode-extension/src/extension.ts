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

  const hasSession = async () => Boolean(await context.secrets.get(ACCESS_SECRET));
  const chat = new ChatViewProvider(context, client, output, hasSession);
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
        chat.notifyAuthState(true);
        vscode.window.showInformationMessage("Signed in to ByteBuddhi");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Sign-in failed";
        output.appendLine(redactSecrets(message));
        vscode.window.showErrorMessage(message);
      }
    }),
    vscode.commands.registerCommand("bytebuddhi.signInWithGoogle", async () => {
      await startOauthLogin(client, output, "google");
    }),
    vscode.commands.registerCommand("bytebuddhi.signInWithGitHub", async () => {
      await startOauthLogin(client, output, "github");
    }),
    vscode.window.registerUriHandler({
      handleUri: async (uri: vscode.Uri) => {
        const code = new URLSearchParams(uri.query).get("code");
        if (!code) {
          vscode.window.showErrorMessage("ByteBuddhi sign-in did not return a code");
          return;
        }
        try {
          const tokens = await client.exchangeOauthCode(code);
          await context.secrets.store(ACCESS_SECRET, tokens.accessToken);
          await context.secrets.store(REFRESH_SECRET, tokens.refreshToken);
          chat.notifyAuthState(true);
          vscode.window.showInformationMessage("Signed in to ByteBuddhi");
        } catch (error) {
          const message = error instanceof Error ? error.message : "Sign-in failed";
          output.appendLine(redactSecrets(message));
          vscode.window.showErrorMessage(message);
        }
      },
    }),
    vscode.commands.registerCommand("bytebuddhi.signOut", async () => {
      try {
        await client.logout();
      } catch {
        // JWT logout is client-side; ignore network errors.
      }
      await context.secrets.delete(ACCESS_SECRET);
      await context.secrets.delete(REFRESH_SECRET);
      chat.session.clearAuth();
      chat.notifyAuthState(false);
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
    vscode.commands.registerCommand("bytebuddhi.selectModel", async () => {
      await chat.selectModel();
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

async function startOauthLogin(
  client: ByteBuddhiApiClient,
  output: vscode.OutputChannel,
  provider: "google" | "github",
): Promise<void> {
  try {
    const enabled = await client.authProviders();
    if ((provider === "google" && !enabled.google) || (provider === "github" && !enabled.github)) {
      vscode.window.showErrorMessage(`${provider} sign-in is not enabled on this server`);
      return;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Server unavailable";
    output.appendLine(redactSecrets(message));
    vscode.window.showErrorMessage(message);
    return;
  }
  const base = vscode.workspace.getConfiguration("bytebuddhi").get<string>("serverUrl") || "http://127.0.0.1:8000";
  const url = `${base.replace(/\/+$/, "")}/api/v1/auth/${provider}/login?client=vscode`;
  await vscode.env.openExternal(vscode.Uri.parse(url));
}
