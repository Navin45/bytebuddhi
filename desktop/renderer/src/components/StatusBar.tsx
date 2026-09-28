import type { JSX } from "react"

import type { AppState } from "../state/app-state"
import { connectionLabel, runLabel } from "../state/app-state"

export function StatusBar({ state }: { state: AppState }): JSX.Element {
  const model = state.selectedModel ?? "server default"
  return (
    <footer className="status" aria-live="polite">
      <span>{connectionLabel(state)}</span>
      <span>{runLabel(state.runStatus)}</span>
      <span>{model}</span>
      <span>Enter sends. Shift+Enter inserts a newline. Closing this window does not cancel the run.</span>
    </footer>
  )
}
