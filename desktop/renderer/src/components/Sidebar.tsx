import { useState, type JSX } from "react"

import { visibleConversations, type AppState } from "../state/app-state"
import type { ChatSession } from "../state/session"

export function Sidebar({ session, state, open }: { session: ChatSession; state: AppState; open: boolean }): JSX.Element {
  const [rename, setRename] = useState("")
  const conversations = visibleConversations(state)
  return (
    <aside className={open ? "sidebar open" : "sidebar"}>
      <h2>Projects</h2>
      {state.projects.length === 0 ? <p>No projects</p> : null}
      {state.projects.map((project) => (
        <button
          key={project.id}
          type="button"
          className="project-button"
          aria-current={project.id === state.activeProjectId}
          onClick={() => void session.selectProject(project.id)}
        >
          {project.id === state.activeProjectId ? "> " : ""}
          {project.name}
        </button>
      ))}
      <h2>Conversations</h2>
      <button type="button" onClick={() => void session.newConversation()}>New conversation</button>
      {conversations.length === 0 ? <p>No conversations</p> : null}
      {conversations.map((conversation) => (
        <button
          key={conversation.id}
          type="button"
          className="list-button"
          aria-current={conversation.id === state.activeConversationId}
          onClick={() => void session.openConversation(conversation.id)}
        >
          {conversation.title}
        </button>
      ))}
      {state.activeConversationId ? (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void session.renameConversation(state.activeConversationId ?? "", rename)
            setRename("")
          }}
        >
          <label>
            Rename
            <input aria-label="Conversation title" value={rename} onChange={(event) => setRename(event.target.value)} />
          </label>
          <button type="submit">Save title</button>
        </form>
      ) : null}
    </aside>
  )
}
