export class GatewayRequestError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "GatewayRequestError"
    this.status = status
  }
}

export class GatewayConnectionError extends Error {
  constructor(message = "Cannot connect to the ByteBuddhi gateway.") {
    super(message)
    this.name = "GatewayConnectionError"
  }
}

export function humanizeGatewayError(error: unknown): string {
  if (error instanceof GatewayConnectionError) return error.message
  if (error instanceof GatewayRequestError) return error.message
  if (error instanceof Error && error.message && !error.message.includes("Bearer ")) return error.message
  return "The gateway request failed."
}

export function messageForStatus(status: number, body: unknown): string {
  const detail = detailText(body)
  if (status === 401) return "Session expired. Sign in again."
  if (status === 403) return "You do not have access to this project."
  if (status === 404) return "That conversation or project was not found."
  if (status === 409) return detail || "The gateway rejected the request because it conflicts with the current run."
  if (status === 400 || status === 422) return detail || "The gateway rejected the request."
  if (status === 429) return "Request rate limited. Please retry shortly."
  if (status === 0 || status >= 500) return detail || "ByteBuddhi gateway returned an internal error."
  return detail || "The gateway request failed."
}

function detailText(body: unknown): string {
  if (!body || typeof body !== "object") return ""
  const detail = (body as Record<string, unknown>).detail
  if (typeof detail === "string") return redact(detail)
  return ""
}

function redact(value: string): string {
  if (/bearer\s+/i.test(value) || value.includes("access_token") || value.length > 400) {
    return "The gateway rejected the request."
  }
  return value
}
