const SECRET_MARKERS = [/bearer\s+[a-z0-9._-]+/gi, /sk-[a-z0-9]+/gi, /eyj[a-z0-9_-]+\.[a-z0-9_-]+/gi];

export function redactSecrets(text: string): string {
  let result = text;
  for (const marker of SECRET_MARKERS) {
    result = result.replace(marker, "[redacted]");
  }
  return result;
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
