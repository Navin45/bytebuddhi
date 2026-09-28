import type { JSX } from "react"

import { connectionLabel, type AppState } from "../state/app-state"

export function ConnectionIndicator({ state }: { state: AppState }): JSX.Element {
  return <span aria-live="polite">{connectionLabel(state)}</span>
}
