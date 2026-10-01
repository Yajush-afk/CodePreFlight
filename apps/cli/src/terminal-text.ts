const OSC = /\u001b\][\s\S]*?(?:\u0007|\u001b\\)/g;
const STRING_CONTROL = /\u001b[PX^_][\s\S]*?\u001b\\/g;
const CSI = /(?:\u001b\[|\u009b)[0-?]*[ -/]*[@-~]/g;
const ESCAPE = /\u001b[ -/]*[@-~]/g;
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g;

/** Remove terminal instructions while preserving printable text, tabs and line breaks. */
export function sanitizeTerminalText(value: string): string {
  return value
    .replace(OSC, "")
    .replace(STRING_CONTROL, "")
    .replace(CSI, "")
    .replace(ESCAPE, "")
    .replace(CONTROL, "");
}
