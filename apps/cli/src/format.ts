export function printValue(value: unknown, json: boolean): void {
  if (json) {
    process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${formatHuman(value)}\n`);
}

function formatHuman(value: unknown, indent = 0): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => `${" ".repeat(indent)}- ${formatHuman(item, indent + 2)}`)
      .join("\n");
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        if (item && typeof item === "object") {
          return `${" ".repeat(indent)}${key}:\n${formatHuman(item, indent + 2)}`;
        }
        return `${" ".repeat(indent)}${key}: ${String(item)}`;
      })
      .join("\n");
  }
  return `${" ".repeat(indent)}${String(value)}`;
}
