import type { JSX } from "react"

export function Composer({
  value,
  disabled,
  running,
  onChange,
  onSend,
  onStop,
}: {
  value: string
  disabled: boolean
  running: boolean
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
}): JSX.Element {
  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        if (!disabled) onSend()
      }}
    >
      <textarea
        aria-label="Message"
        value={value}
        disabled={disabled}
        placeholder="Type a message..."
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault()
            if (!disabled) onSend()
          }
        }}
      />
      {running ? (
        <button type="button" onClick={onStop}>Stop</button>
      ) : (
        <button type="submit" disabled={disabled || !value.trim()}>Send</button>
      )}
    </form>
  )
}
