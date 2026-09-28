import { useEffect, useRef, type JSX } from "react"

import type { AppState } from "../state/app-state"
import { Message } from "./Message"

export function ConversationView({
  state,
  onStickToBottom,
}: {
  state: AppState
  onStickToBottom: (stick: boolean) => void
}): JSX.Element {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = scroller.current
    if (element && state.stickToBottom) element.scrollTop = element.scrollHeight
  }, [state.transcript, state.stickToBottom])

  return (
    <div
      className="conversation"
      ref={scroller}
      onScroll={(event) => {
        const element = event.currentTarget
        const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 80
        if (nearBottom !== state.stickToBottom) onStickToBottom(nearBottom)
      }}
    >
      {state.transcript.length === 0 ? <p>No messages yet. Send one when the gateway is connected.</p> : null}
      {state.transcript.map((item) => (
        <Message key={item.id} item={item} />
      ))}
      {state.stickToBottom ? null : (
        <button type="button" className="jump" onClick={() => onStickToBottom(true)}>Jump to latest</button>
      )}
    </div>
  )
}
