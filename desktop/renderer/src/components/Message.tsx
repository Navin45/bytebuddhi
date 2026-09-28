import { memo, type JSX } from "react"
import ReactMarkdown from "react-markdown"
import rehypeHighlight from "rehype-highlight"
import remarkGfm from "remark-gfm"

import { isSafeExternalUrl } from "../../../electron/security"
import type { TranscriptItem } from "../state/app-state"
import { ToolActivity } from "./ToolActivity"

export const Message = memo(function Message({ item }: { item: TranscriptItem }): JSX.Element {
  if (item.kind === "tool") return <ToolActivity item={item} />
  return (
    <article className={`message ${item.kind}`}>
      <header>
        <span>{item.title}</span>
        {item.kind === "assistant" ? (
          <button type="button" onClick={() => void navigator.clipboard.writeText(item.body)}>Copy message</button>
        ) : null}
      </header>
      {item.kind === "assistant" ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
          components={{
            a: ({ href, children }) => (
              <a
                href={href}
                onClick={(event) => {
                  event.preventDefault()
                  if (href && isSafeExternalUrl(href)) void window.bytebuddhi.desktop.openExternal(href)
                }}
              >
                {children}
              </a>
            ),
            code: ({ className, children }) => {
              const text = String(children).replace(/\n$/, "")
              if (!className) return <code>{text}</code>
              return (
                <span className="code-block">
                  <button type="button" onClick={() => void navigator.clipboard.writeText(text)}>Copy code</button>
                  <code className={className}>{text}</code>
                </span>
              )
            },
          }}
        >
          {item.body}
        </ReactMarkdown>
      ) : (
        <p>{item.body}</p>
      )}
    </article>
  )
})
