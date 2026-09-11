import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (full.endsWith(".ts")) {
      out.push(full);
    }
  }
  return out;
}

test("extension source does not implement a second runtime or shell executor", () => {
  const root = join(__dirname, "..", "..", "src");
  const files = walk(root).filter((path) => !path.split(/[\\/]/).includes("test"));
  assert.ok(files.length > 0, "expected TypeScript sources under src/");
  const banned = [
    "AgentRuntime",
    "MultiAgentOrchestrator",
    "ToolExecutor",
    "ToolPolicyEngine",
    "ProcessManager",
    "WebResearchService",
    "playwright",
    "duckduckgo",
    "child_process",
    "spawn(",
    "execSync",
    "eval(",
    "new Function",
  ];
  const hits: string[] = [];
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const token of banned) {
      if (text.includes(token)) {
        hits.push(`${file} contains ${token}`);
      }
    }
  }
  assert.deepEqual(hits, []);
});
