export function chatHtml(nonce: string, cspSource: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource}; style-src ${cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ByteBuddhi</title>
  <style nonce="${nonce}">
    body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); margin: 0; padding: 8px; }
    #log { min-height: 120px; max-height: 60vh; overflow: auto; }
    .msg { margin: 8px 0; white-space: pre-wrap; }
    .status { opacity: 0.8; font-size: 12px; }
    textarea { width: 100%; box-sizing: border-box; min-height: 64px; }
    button { margin-top: 6px; margin-right: 6px; }
  </style>
</head>
<body>
  <div class="status" id="status">idle</div>
  <div id="log"></div>
  <textarea id="prompt" placeholder="Task prompt"></textarea>
  <button id="send">Send</button>
  <button id="cancel">Cancel</button>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const log = document.getElementById("log");
    const statusEl = document.getElementById("status");
    const promptEl = document.getElementById("prompt");
    document.getElementById("send").addEventListener("click", () => {
      const prompt = promptEl.value;
      vscode.postMessage({ type: "send_message", prompt });
    });
    document.getElementById("cancel").addEventListener("click", () => {
      vscode.postMessage({ type: "cancel_task" });
    });
    window.addEventListener("message", (event) => {
      const msg = event.data || {};
      if (msg.type === "status") {
        statusEl.textContent = String(msg.status || "");
      } else if (msg.type === "error") {
        addLine("error", String(msg.message || "error"));
      } else if (msg.type === "result") {
        addLine("assistant", String(msg.answer || ""));
      } else if (msg.type === "history" && Array.isArray(msg.messages)) {
        log.textContent = "";
        for (const item of msg.messages) {
          addLine(item.role === "user" ? "user" : "assistant", String(item.content || ""));
        }
      }
    });
    function addLine(role, content) {
      const wrap = document.createElement("div");
      wrap.className = "msg";
      const who = document.createElement("strong");
      who.textContent = role;
      const body = document.createElement("div");
      body.textContent = content;
      wrap.appendChild(who);
      wrap.appendChild(body);
      log.appendChild(wrap);
    }
    vscode.postMessage({ type: "ready" });
  </script>
</body>
</html>`;
}
