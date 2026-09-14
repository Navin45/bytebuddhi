# Authentication

ByteBuddhi has one canonical user identity: `User.id`. Password, Google, and GitHub are ways to prove who that user is. After sign-in, clients use a **ByteBuddhi JWT**. Google and GitHub tokens never authorize API, CLI, or VS Code requests.

```text
Password / Google / GitHub
        ↓
   ExternalIdentity (provider + subject)
        ↓
          User
        ↓
   ByteBuddhi JWT
        ↓
  ExecutionContext.user_id
        ↓
  existing authorization
```

OAuth answers “who is this user?” Project access, tools, memory, and artifacts still use the existing authorization model.

## Password authentication

`POST /api/v1/auth/register` and `POST /api/v1/auth/login` remain available. Email is the unique **contact / login identifier**, not a verified OAuth key. Password hashes are bcrypt. OAuth-only accounts have `password_hash = null` and cannot use password login until they set a password (`POST /api/v1/auth/password/change` while authenticated).

JWT claims stay `sub`, `exp`, `iat`, `type`. OAuth callback parameters cannot overwrite protected claims.

`POST /api/v1/auth/logout` instructs clients to discard tokens. JWTs are stateless; the server does not maintain a session store.

## Google login

Enabled independently with `GOOGLE_OAUTH_ENABLED=true` plus client ID and secret.

1. Client opens `GET /api/v1/auth/google/login?client=web|vscode|cli`
2. Backend stores a single-use `state` (5–10 minutes) and redirects to Google
3. Google returns to the **configured** `GOOGLE_REDIRECT_URI`
4. Backend validates `state`, exchanges the code server-side, verifies the Google ID token (`sub` is the identity key)
5. Backend finds or creates `User` + `ExternalIdentity` and issues a **one-time exchange code**
6. Client posts `POST /api/v1/auth/oauth/exchange` with that code and receives ByteBuddhi JWTs

Scopes: `openid email profile`. Offline access and refresh tokens are not requested. Provider tokens are not stored.

Register a Google OAuth client (Web application). Authorized redirect URI must match `GOOGLE_REDIRECT_URI` exactly, for example `http://127.0.0.1:8000/api/v1/auth/google/callback` in development.

## GitHub login

Enabled independently with `GITHUB_OAUTH_ENABLED=true` plus client ID and secret.

Flow matches Google. The stable GitHub **numeric account id** is `provider_subject`. Usernames are not identity keys.

Login scopes are `read:user` and `user:email` only. This is **not** repository access. Connecting GitHub repositories remains a separate connector/MCP capability.

If GitHub hides email on the profile, ByteBuddhi reads `/user/emails` and uses a **verified** address when one exists. Unverified strings are not treated as verified.

Register a GitHub OAuth App (not a GitHub App) for login. Callback URL must match `GITHUB_REDIRECT_URI` exactly.

## Account linking and unlinking

Email match is **not** enough to attach Google or GitHub to an existing password user. That would be account takeover.

Authenticated linking:

- `POST /api/v1/auth/google/link`
- `POST /api/v1/auth/github/link`

Unlinking:

- `DELETE /api/v1/auth/google/link`
- `DELETE /api/v1/auth/github/link`

The last remaining sign-in method cannot be removed. Set a password or link another provider first.

`GET /api/v1/auth/identities` lists linked providers and whether a password exists.

`GET /api/v1/auth/providers` reports `{ "google": true, "github": false }` without secrets.

## JWT, CLI, and VS Code

| Client | How identity is established | Token storage |
|---|---|---|
| API / browser | Password or OAuth → ByteBuddhi JWT | Caller-controlled; not in URL query strings |
| VS Code | Password command, or Continue with Google/GitHub → backend browser flow → one-time code on `vscode://bytebuddhi.bytebuddhi/oauth` → `POST /auth/oauth/exchange` | VS Code SecretStorage |
| CLI | `bytebuddhi login --provider google\|github` opens the backend login URL; paste the one-time code (`--code`) | `~/.bytebuddhi/credentials.json` (mode 0600) |

The VS Code extension and CLI **must not** contain `GOOGLE_CLIENT_SECRET` or `GITHUB_CLIENT_SECRET`. They never call Google or GitHub token endpoints.

CLI `run` / `chat` still execute locally through `ExecuteTaskUseCase` using `User.id` from `--user-id`, `BYTEBUDDHI_USER_ID`, or the stored login. They do not send Google tokens to the runtime.

`bytebuddhi logout` deletes the local credential file. VS Code Sign Out deletes SecretStorage keys.

## Configuration

```env
GOOGLE_OAUTH_ENABLED=false
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback
GITHUB_OAUTH_ENABLED=false
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/github/callback
OAUTH_POST_LOGIN_REDIRECT=
OAUTH_VSCODE_REDIRECT=vscode://bytebuddhi.bytebuddhi/oauth
OAUTH_CLI_REDIRECT=
```

Each provider can be enabled without the other. Disabling both leaves password login working. Enabled + missing client ID or secret fails startup. A client ID without its secret also fails, even if the provider is disabled.

Redirect URIs are exact configured values. `?next=` is ignored. Production non-loopback callbacks must be HTTPS.

OAuth `state` is stored in Redis when Redis is connected, otherwise in a bounded in-process store (single worker). Multi-worker API deployments should run Redis so login state is shared.

## Local development callbacks

1. Create Google and/or GitHub OAuth clients.
2. Set the callback URIs to the localhost values above.
3. Copy client ID and secret into `.env` (never into git, Dockerfiles, or workflows).
4. Set `GOOGLE_OAUTH_ENABLED=true` and/or `GITHUB_OAUTH_ENABLED=true`.
5. Restart the API. Open `http://127.0.0.1:8000/api/v1/auth/google/login?client=web`.

## Security model

- Identity key is `(provider, provider_subject)`, unique in PostgreSQL.
- New OAuth users are normal users. Google Workspace domain or GitHub org does not grant admin.
- First-time login creates `User` and `ExternalIdentity` in one database transaction after provider HTTP finishes.
- Concurrent first logins for the same subject cannot create two users; uniqueness plus conflict handling apply.
- Provider HTTP uses the shared bounded HTTP client (timeouts, TLS).
- Access logs redact `code` and `state` query parameters.
- Telemetry records `auth.provider`, `auth.flow`, `auth.result`, `auth.failure_category` only.

Manual browser checks (staging): Google/GitHub login and logout for new and existing users; link/unlink; deny consent; expired/invalid callback. Default CI uses mocks and must not require live provider secrets.
