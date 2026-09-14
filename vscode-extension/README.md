# ByteBuddhi VS Code extension

Thin IDE client over the ByteBuddhi HTTP API. Execution stays on `ExecuteTaskUseCase`. This package is not an agent runtime.

Requires VS Code 1.90+ and a running API (`http://127.0.0.1:8000` by default).

```bash
npm install
npm run compile
npm test
npm run package
```

Commands: Sign In, Sign Out, Run Task, Open Chat, Cancel Task, Show Status.

Tokens use VS Code SecretStorage. The chat webview uses a nonce CSP and validated messages.
