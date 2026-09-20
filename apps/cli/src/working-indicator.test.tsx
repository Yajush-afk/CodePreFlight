import React from "react";
import { render } from "ink-testing-library";
import { describe, expect, it, vi } from "vitest";
import { WorkingIndicator } from "./working-indicator.js";

describe("working indicator", () => {
  it("animates only when enabled and clears its interval on unmount", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const view = render(
      <WorkingIndicator label="Preflight is checking" animate />,
    );
    await new Promise<void>((resolve) => setImmediate(resolve));
    await vi.advanceTimersByTimeAsync(100);
    expect(view.lastFrame()).toContain("Preflight is checking");
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(vi.getTimerCount()).toBe(0);
    vi.useRealTimers();
  });
  it("renders statically for reduced motion", () => {
    const view = render(<WorkingIndicator label="Checking" animate={false} />);
    expect(view.lastFrame()).toContain("· Checking");
    view.unmount();
  });
});
