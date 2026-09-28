import { useState, useSyncExternalStore, type JSX } from "react"

import type { ChatSession } from "../../state/session"

export function AuthScreen({ session }: { session: ChatSession }): JSX.Element {
  const state = useSyncExternalStore(session.subscribe.bind(session), session.getState.bind(session))
  const [code, setCode] = useState("")
  return (
    <main className="auth">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void session.exchange(code)
        }}
      >
        <h1>Sign in to ByteBuddhi</h1>
        <p>Sign-in opens in your browser. Paste the one-time code here. Passwords are not entered in this app.</p>
        <button type="button" onClick={() => void session.signIn("google")}>Continue with Google</button>
        <button type="button" onClick={() => void session.signIn("github")}>Continue with GitHub</button>
        <label>
          One-time code
          <input aria-label="One-time code" value={code} onChange={(event) => setCode(event.target.value)} />
        </label>
        <button type="submit">Use code</button>
        {state.error ? <p className="error" role="alert">{state.error}</p> : null}
      </form>
    </main>
  )
}
