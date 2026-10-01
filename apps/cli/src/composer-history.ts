export class ComposerHistory {
  private readonly entries: string[] = [];
  private index = 0;

  record(value: string): void {
    if (this.entries.at(-1) !== value) this.entries.push(value);
    this.index = this.entries.length;
  }

  navigate(direction: "previous" | "next"): string {
    if (!this.entries.length) return "";
    this.index =
      direction === "previous"
        ? Math.max(0, this.index - 1)
        : Math.min(this.entries.length, this.index + 1);
    return this.entries[this.index] ?? "";
  }

  clear(): void {
    this.entries.length = 0;
    this.index = 0;
  }
}
