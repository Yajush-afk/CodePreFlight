export function interactiveEffects(
  tty: boolean,
  environment: NodeJS.ProcessEnv = process.env,
): boolean {
  return tty && !environment.CI && environment.TERM !== "dumb";
}

export class TerminalSession {
  readonly enabled: boolean;
  onExit?: () => void;
  private entered = false;
  private suspended = false;
  constructor(
    inline = false,
    private output = process.stdout,
    private input = process.stdin,
  ) {
    this.enabled =
      !inline && interactiveEffects(Boolean(output.isTTY && input.isTTY));
  }
  enter(): void {
    if (!this.enabled || this.entered) return;
    this.output.write("\u001b[?1049h\u001b[?25l");
    this.entered = true;
  }
  restore = (): void => {
    if (this.entered) this.output.write("\u001b[?25h\u001b[?1049l");
    this.entered = false;
    if (this.input.isTTY && this.input.isRaw) this.input.setRawMode(false);
  };
  suspend(): void {
    this.suspended = true;
    this.restore();
  }
  resume(): void {
    this.suspended = false;
    this.enter();
  }
  install(): void {
    this.enter();
    process.on("exit", this.restore);
    process.on("uncaughtExceptionMonitor", this.restore);
    process.on("SIGTERM", this.terminate);
    process.on("SIGHUP", this.terminate);
    process.on("SIGINT", this.interrupt);
  }
  dispose(): void {
    this.restore();
    process.off("exit", this.restore);
    process.off("uncaughtExceptionMonitor", this.restore);
    process.off("SIGTERM", this.terminate);
    process.off("SIGHUP", this.terminate);
    process.off("SIGINT", this.interrupt);
  }
  private interrupt = (): void => {
    if (!this.suspended) {
      this.onExit?.();
      this.restore();
      process.exit(130);
    }
  };
  private terminate = (): void => {
    this.onExit?.();
    this.restore();
    process.exit(143);
  };
}
