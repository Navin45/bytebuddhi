import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { parseWebviewMessage } from "../protocol/messages";
import { buildPrompt, buildRunTaskRequest } from "../protocol/prompt";
import { matchProjectId } from "../protocol/projects";
import { ClientSession } from "../protocol/session";
import { escapeHtml, redactSecrets } from "../protocol/redact";
import { parseSseStream } from "../protocol/sse";
import { ByteBuddhiApiClient } from "../transport/apiClient";

test("rejects webview identity and approval injection", () => {
  assert.equal(
    parseWebviewMessage({ type: "send_message", prompt: "hi", user_id: "attacker" }),
    undefined,
  );
  assert.equal(parseWebviewMessage({ type: "send_message", prompt: "hi", approved_actions: ["all"] }), undefined);
  assert.equal(parseWebviewMessage({ type: "run_shell", prompt: "rm -rf" }), undefined);
  assert.deepEqual(parseWebviewMessage({ type: "sign_in_google" }), { type: "sign_in_google" });
  assert.deepEqual(parseWebviewMessage({ type: "select_model" }), { type: "select_model" });
  assert.equal(parseWebviewMessage({ type: "sign_in_google", access_token: "tok" }), undefined);
  assert.deepEqual(parseWebviewMessage({ type: "send_message", prompt: "  hello  " }), {
    type: "send_message",
    prompt: "hello",
  });
});

test("run request never includes trusted identity fields", () => {
  const request = buildRunTaskRequest({
    prompt: "Explain",
    projectId: "proj-1",
    conversationId: "conv-1",
    clientRequestId: "req-1",
  });
  assert.equal("user_id" in request, false);
  assert.equal("approved_actions" in request, false);
  assert.equal(request.prompt, "Explain");
});

test("editor context is bounded and optional", () => {
  const huge = "x".repeat(9000);
  const prompt = buildPrompt("summarize", {
    path: "app.py",
    startLine: 1,
    endLine: 2,
    text: huge,
  });
  assert.match(prompt, /Active file: app.py/);
  assert.ok(prompt.length < huge.length + 200);
  assert.equal(buildPrompt("only"), "only");
});

test("project match uses listed local_path and ignores unmatched folders", () => {
  const id = matchProjectId("C:\\work\\alpha", [
    { id: "a", name: "alpha", local_path: "C:/work/alpha" },
    { id: "b", name: "beta", local_path: "C:/work/beta" },
  ]);
  assert.equal(id, "a");
  assert.equal(matchProjectId("/tmp/other", [{ id: "a", name: "alpha", local_path: "/tmp/alpha" }]), undefined);
});

test("switching projects clears conversation state", () => {
  const session = new ClientSession();
  session.bindProject("a");
  session.conversationId = "conv-a";
  session.runId = "run-a";
  session.bindProject("b");
  assert.equal(session.conversationId, undefined);
  assert.equal(session.runId, undefined);
  assert.equal(session.projectId, "b");
});

test("does not start a second inflight request", () => {
  const session = new ClientSession();
  assert.equal(session.beginRequest("1"), true);
  assert.equal(session.beginRequest("2"), false);
});

test("redacts tokens and escapes html", () => {
  assert.equal(redactSecrets("Authorization Bearer abc.def").includes("abc.def"), false);
  assert.equal(escapeHtml("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;");
});

test("sse parser reads run_started without executing content", () => {
  const events = parseSseStream(
    'event: run_started\ndata: {"type":"run_started","run_id":"run_1"}\n\nevent: content\ndata: {"content":"<img src=x>"}\n\n',
  );
  assert.equal(events[0]?.data.run_id, "run_1");
  assert.equal(events[1]?.data.content, "<img src=x>");
});

test("api client sendMessage omits model unless selected from catalog", async () => {
  let body = "";
  const client = new ByteBuddhiApiClient(
    async (_input, init) => {
      body = String(init?.body ?? "");
      return new Response('event: done\ndata: {"type":"done"}\n\n', { status: 200 });
    },
    () => "http://127.0.0.1:8000",
    async () => "token",
  );
  await client.sendMessage("conv", "hello");
  assert.equal(JSON.parse(body).content, "hello");
  assert.equal("model" in JSON.parse(body), false);
  await client.sendMessage("conv", "hello", undefined, { provider: "openai", model: "gpt-4o" });
  assert.deepEqual(JSON.parse(body).model, { provider: "openai", model: "gpt-4o" });
  assert.equal("base_url" in JSON.parse(body), false);
});

test("api client sendMessage does not retry after success path", async () => {
  let calls = 0;
  const client = new ByteBuddhiApiClient(
    async () => {
      calls += 1;
      return new Response('event: done\ndata: {"type":"done"}\n\n', { status: 200 });
    },
    () => "http://127.0.0.1:8000",
    async () => "token",
  );
  await client.sendMessage("conv", "hello");
  assert.equal(calls, 1);
});

test("api client does not retry a timeout as a second send", async () => {
  let calls = 0;
  const client = new ByteBuddhiApiClient(
    async () => {
      calls += 1;
      throw new Error("network timeout");
    },
    () => "http://127.0.0.1:8000",
    async () => "token",
  );
  await assert.rejects(() => client.sendMessage("conv", "hello"));
  assert.equal(calls, 1);
});

test("package metadata registers the command set", () => {
  const manifest = JSON.parse(readFileSync(join(__dirname, "..", "..", "package.json"), "utf8")) as {
    engines: { vscode: string };
    contributes: { commands: Array<{ command: string }> };
  };
  const commands = new Set(manifest.contributes.commands.map((item) => item.command));
  for (const command of [
    "bytebuddhi.runTask",
    "bytebuddhi.openChat",
    "bytebuddhi.cancelTask",
    "bytebuddhi.showStatus",
    "bytebuddhi.signIn",
    "bytebuddhi.signInWithGoogle",
    "bytebuddhi.signInWithGitHub",
    "bytebuddhi.signOut",
    "bytebuddhi.selectModel",
  ]) {
    assert.ok(commands.has(command), command);
  }
  assert.equal(manifest.engines.vscode, "^1.90.0");
});
