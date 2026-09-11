export interface EditorSnippet {
  path: string;
  language?: string;
  startLine: number;
  endLine: number;
  text: string;
}

const MAX_SNIPPET_CHARS = 8000;

export function buildPrompt(userText: string, snippet?: EditorSnippet): string {
  const prompt = userText.trim();
  if (!snippet || !snippet.text.trim()) {
    return prompt;
  }
  const clipped = snippet.text.slice(0, MAX_SNIPPET_CHARS);
  const truncated = snippet.text.length > MAX_SNIPPET_CHARS ? "\n[selection truncated]\n" : "";
  return [
    prompt,
    "",
    `Active file: ${snippet.path} (lines ${snippet.startLine}-${snippet.endLine})`,
    "```",
    clipped + truncated,
    "```",
  ].join("\n");
}

export interface RunTaskRequest {
  prompt: string;
  projectId?: string;
  conversationId?: string;
  clientRequestId: string;
}

export function buildRunTaskRequest(input: {
  prompt: string;
  projectId?: string;
  conversationId?: string;
  clientRequestId: string;
}): RunTaskRequest {
  return {
    prompt: input.prompt,
    projectId: input.projectId,
    conversationId: input.conversationId,
    clientRequestId: input.clientRequestId,
  };
}
