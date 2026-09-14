export function chatHtml(nonce: string, cspSource: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource}; style-src ${cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ByteBuddhi</title>
  <style nonce="${nonce}">
    * { box-sizing: border-box; }
    html, body {
      height: 100%;
      margin: 0;
      padding: 0;
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size, 13px);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background, var(--vscode-editor-background));
    }
    .app {
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid var(--vscode-widget-border, var(--vscode-panel-border));
      flex: 0 0 auto;
    }
    .title {
      font-weight: 600;
    }
    .status-pill {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 10px;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .log {
      flex: 1 1 auto;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .empty {
      margin: auto;
      text-align: center;
      color: var(--vscode-descriptionForeground);
      padding: 24px;
    }
    .msg {
      max-width: 88%;
      padding: 8px 12px;
      border-radius: 10px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .msg .role {
      display: block;
      font-size: 11px;
      font-weight: 600;
      opacity: 0.65;
      margin-bottom: 3px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .msg.user {
      align-self: flex-end;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    .msg.assistant {
      align-self: flex-start;
      background: var(--vscode-editorWidget-background, var(--vscode-input-background));
      border: 1px solid var(--vscode-widget-border, var(--vscode-panel-border));
    }
    .msg.error {
      align-self: flex-start;
      background: var(--vscode-inputValidation-errorBackground);
      border: 1px solid var(--vscode-inputValidation-errorBorder);
      color: var(--vscode-inputValidation-errorForeground, var(--vscode-foreground));
    }
    .msg pre {
      margin: 6px 0;
      padding: 8px 10px;
      border-radius: 6px;
      overflow-x: auto;
      background: var(--vscode-textCodeBlock-background, rgba(0, 0, 0, 0.2));
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: var(--vscode-editor-font-size, 12px);
    }
    .msg code {
      font-family: var(--vscode-editor-font-family, monospace);
    }
    .signed-out {
      margin: auto;
      text-align: center;
      padding: 24px;
      max-width: 260px;
      display: none;
      flex-direction: column;
      gap: 8px;
    }
    .signed-out p {
      color: var(--vscode-descriptionForeground);
      margin: 0 0 4px;
    }
    .composer {
      flex: 0 0 auto;
      display: none;
      flex-direction: column;
      gap: 6px;
      padding: 10px 12px;
      border-top: 1px solid var(--vscode-widget-border, var(--vscode-panel-border));
      background: var(--vscode-sideBar-background, var(--vscode-editor-background));
    }
    textarea {
      width: 100%;
      min-height: 60px;
      max-height: 160px;
      resize: vertical;
      font-family: inherit;
      font-size: inherit;
      color: var(--vscode-input-foreground);
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, var(--vscode-widget-border));
      border-radius: 6px;
      padding: 8px;
    }
    textarea:focus {
      outline: 1px solid var(--vscode-focusBorder);
    }
    .actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 6px;
    }
    .actions .right {
      display: flex;
      gap: 6px;
    }
    .model-btn {
      color: var(--vscode-descriptionForeground);
      background: transparent;
      border: 1px solid var(--vscode-widget-border, var(--vscode-panel-border));
    }
    .model-btn:hover {
      color: var(--vscode-foreground);
      background: var(--vscode-list-hoverBackground);
    }
    button {
      font-family: inherit;
      font-size: 12px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 5px 12px;
      cursor: pointer;
      background: var(--vscode-button-secondaryBackground, transparent);
      color: var(--vscode-button-secondaryForeground, var(--vscode-foreground));
    }
    button:hover {
      background: var(--vscode-button-secondaryHoverBackground, var(--vscode-list-hoverBackground));
    }
    button.primary {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    button.primary:hover {
      background: var(--vscode-button-hoverBackground);
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <span class="title">ByteBuddhi</span>
      <span class="status-pill" id="status">idle</span>
    </div>
    <div id="log" class="log">
      <div class="empty" id="empty">Ask ByteBuddhi anything about this workspace.</div>
    </div>
    <div class="signed-out" id="signedOut">
      <p>Sign in to start chatting with ByteBuddhi.</p>
      <button id="signin" class="primary">Sign In</button>
      <button id="google">Continue with Google</button>
      <button id="github">Continue with GitHub</button>
    </div>
    <div class="composer" id="composer">
      <textarea id="prompt" placeholder="Ask ByteBuddhi... (Enter to send, Shift+Enter for newline)"></textarea>
      <div class="actions">
        <button id="modelBtn" class="model-btn" title="Select model">Auto</button>
        <div class="right">
          <button id="cancel">Cancel</button>
          <button id="send" class="primary">Send</button>
        </div>
      </div>
    </div>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const log = document.getElementById("log");
    const empty = document.getElementById("empty");
    const statusEl = document.getElementById("status");
    const promptEl = document.getElementById("prompt");
    const sendBtn = document.getElementById("send");
    const composer = document.getElementById("composer");
    const signedOut = document.getElementById("signedOut");

    function send() {
      const prompt = promptEl.value;
      if (!prompt.trim()) {
        return;
      }
      addLine("user", prompt);
      promptEl.value = "";
      vscode.postMessage({ type: "send_message", prompt });
    }

    sendBtn.addEventListener("click", send);
    promptEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });
    document.getElementById("cancel").addEventListener("click", () => {
      vscode.postMessage({ type: "cancel_task" });
    });
    document.getElementById("signin").addEventListener("click", () => {
      vscode.postMessage({ type: "sign_in" });
    });
    document.getElementById("google").addEventListener("click", () => {
      vscode.postMessage({ type: "sign_in_google" });
    });
    document.getElementById("github").addEventListener("click", () => {
      vscode.postMessage({ type: "sign_in_github" });
    });
    document.getElementById("modelBtn").addEventListener("click", () => {
      vscode.postMessage({ type: "select_model" });
    });

    window.addEventListener("message", (event) => {
      const msg = event.data || {};
      if (msg.type === "auth") {
        setSignedIn(Boolean(msg.signedIn));
      } else if (msg.type === "status") {
        const status = String(msg.status || "");
        statusEl.textContent = status;
        sendBtn.disabled = status === "running";
      } else if (msg.type === "error") {
        addLine("error", String(msg.message || "error"));
      } else if (msg.type === "result") {
        addLine("assistant", String(msg.answer || ""));
      } else if (msg.type === "history" && Array.isArray(msg.messages)) {
        log.textContent = "";
        for (const item of msg.messages) {
          addLine(item.role === "user" ? "user" : "assistant", String(item.content || ""));
        }
      } else if (msg.type === "model") {
        document.getElementById("modelBtn").textContent = String(msg.label || "Auto");
      }
    });

    function setSignedIn(signedIn) {
      composer.style.display = signedIn ? "flex" : "none";
      signedOut.style.display = signedIn ? "none" : "flex";
    }

    function addLine(role, content) {
      if (empty.parentNode) {
        empty.remove();
      }
      const wrap = document.createElement("div");
      wrap.className = "msg " + role;
      const label = document.createElement("span");
      label.className = "role";
      label.textContent = role;
      wrap.appendChild(label);
      appendFormatted(wrap, content);
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    }

    function appendFormatted(container, content) {
      const fence = /\`\`\`[a-zA-Z0-9]*\\n?([\\s\\S]*?)\`\`\`/g;
      let last = 0;
      let match;
      let any = false;
      while ((match = fence.exec(content)) !== null) {
        any = true;
        if (match.index > last) {
          appendText(container, content.slice(last, match.index));
        }
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = match[1].replace(/\\n$/, "");
        pre.appendChild(code);
        container.appendChild(pre);
        last = fence.lastIndex;
      }
      if (!any) {
        appendText(container, content);
      } else if (last < content.length) {
        appendText(container, content.slice(last));
      }
    }

    function appendText(container, text) {
      if (!text) {
        return;
      }
      const span = document.createElement("span");
      span.textContent = text;
      container.appendChild(span);
    }

    vscode.postMessage({ type: "ready" });
  </script>
</body>
</html>`;
}
