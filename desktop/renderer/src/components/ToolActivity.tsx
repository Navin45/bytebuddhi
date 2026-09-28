import type { JSX } from "react"

import type { TranscriptItem } from "../state/app-state"

export function ToolActivity({ item }: { item: TranscriptItem }): JSX.Element {
  const mark = item.body === "failed" ? "✗" : item.body === "completed" ? "✓" : "●"
  return (
    <details className={`tool ${item.body}`} open={item.toolOpen}>
      <summary>
        {mark} {item.title} {item.body}
      </summary>
      {item.detail ? <p>{item.detail}</p> : <p>Details stay collapsed until you open them.</p>}
    </details>
  )
}
