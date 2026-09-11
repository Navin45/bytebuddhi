export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export function parseSseBlock(block: string): SseEvent | undefined {
  const lines = block.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  if (dataLines.length === 0) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(dataLines.join("\n"));
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return undefined;
    }
    return { event, data: parsed as Record<string, unknown> };
  } catch {
    return undefined;
  }
}

export function parseSseStream(raw: string): SseEvent[] {
  return raw
    .split(/\r?\n\r?\n/)
    .map((block) => parseSseBlock(block))
    .filter((item): item is SseEvent => item !== undefined);
}
