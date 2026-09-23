export function sanitizeComposerInput(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]/g, "");
}
