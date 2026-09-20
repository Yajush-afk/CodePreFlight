export class WorkflowCoordinator {
  private interruptionAt: number | undefined;
  interrupt(
    actor: string | undefined,
    busy: boolean,
    now = Date.now(),
  ): "idle" | "confirm" | "cancel" {
    if (!busy) return "idle";
    if (actor !== "Provider") {
      this.reset();
      return "cancel";
    }
    if (
      this.interruptionAt !== undefined &&
      now - this.interruptionAt <= 2000
    ) {
      this.reset();
      return "cancel";
    }
    this.interruptionAt = now;
    return "confirm";
  }
  reset(): void {
    this.interruptionAt = undefined;
  }
}
