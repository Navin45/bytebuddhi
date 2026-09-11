export interface ListedProject {
  id: string;
  name: string;
  local_path?: string | null;
}

export function normalizePath(value: string): string {
  return value.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

export function matchProjectId(workspacePath: string, projects: ListedProject[]): string | undefined {
  const target = normalizePath(workspacePath);
  for (const project of projects) {
    if (!project.local_path) {
      continue;
    }
    if (normalizePath(project.local_path) === target) {
      return project.id;
    }
  }
  return undefined;
}
