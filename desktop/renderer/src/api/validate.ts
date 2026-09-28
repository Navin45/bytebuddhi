import {
  ALLOWED_EVENT_DATA_KEYS,
  RUN_EVENT_TYPES,
  SCHEMA_VERSION,
  type EventDataKey,
  type EventDataValue,
  type RunEvent,
  type RunEventPage,
  type RunEventType,
} from "../generated/contracts"

const EVENT_TYPES = new Set<string>(RUN_EVENT_TYPES)
const DATA_KEYS = new Set<string>(ALLOWED_EVENT_DATA_KEYS)

export type ValidationResult = { ok: true; event: RunEvent } | { ok: false; reason: string }

export function validateRunEvent(value: unknown): ValidationResult {
  if (!value || typeof value !== "object") return { ok: false, reason: "Event envelope is missing." }
  const record = value as Record<string, unknown>
  if (typeof record.event_id !== "string" || typeof record.run_id !== "string" || typeof record.created_at !== "string") {
    return { ok: false, reason: "Event envelope is incomplete." }
  }
  if (typeof record.sequence !== "number" || !Number.isInteger(record.sequence) || record.sequence < 1) {
    return { ok: false, reason: "Event sequence is invalid." }
  }
  if (typeof record.type !== "string" || !EVENT_TYPES.has(record.type)) {
    return { ok: false, reason: "Event type is not part of the run protocol." }
  }
  if (record.schema_version !== SCHEMA_VERSION) {
    return { ok: false, reason: "Event schema version is unsupported." }
  }
  return {
    ok: true,
    event: {
      event_id: record.event_id,
      run_id: record.run_id,
      sequence: record.sequence,
      type: record.type as RunEventType,
      schema_version: SCHEMA_VERSION,
      created_at: record.created_at,
      data: sanitizeData(record.data),
    },
  }
}

export function validateRunEventPage(value: unknown): RunEventPage | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.events) || typeof record.has_more !== "boolean") return null
  const events: RunEvent[] = []
  for (const item of record.events) {
    const parsed = validateRunEvent(item)
    if (!parsed.ok) return null
    events.push(parsed.event)
  }
  const next = typeof record.next_sequence === "number" ? record.next_sequence : events.at(-1)?.sequence ?? 0
  return { events, next_sequence: next, has_more: record.has_more }
}

function sanitizeData(value: unknown): Partial<Record<EventDataKey, EventDataValue>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {}
  const data: Partial<Record<EventDataKey, EventDataValue>> = {}
  for (const [key, item] of Object.entries(value)) {
    if (!DATA_KEYS.has(key)) continue
    if (typeof item === "string" || typeof item === "number" || typeof item === "boolean" || item === null) {
      data[key as EventDataKey] = item
    }
  }
  return data
}
