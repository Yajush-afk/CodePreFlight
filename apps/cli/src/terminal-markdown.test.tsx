import React from "react";
import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";
import { TerminalMarkdown } from "./terminal-markdown.js";

describe("terminal markdown", () => {
  it("renders supported markdown semantics without showing control syntax", () => {
    const view = render(
      <TerminalMarkdown
        value={
          "# Explanation\n\n- inspect `auth.py`\n- **restore validation**\n\n```ts\nconst safe = true;\n```"
        }
        height={20}
      />,
    );
    const frame = view.lastFrame() ?? "";
    expect(frame).toContain("Explanation");
    expect(frame).toContain("• inspect auth.py");
    expect(frame).toContain("• restore validation");
    expect(frame).toContain("const safe = true;");
    expect(frame).not.toContain("**");
    expect(frame).not.toContain("```");
    view.unmount();
  });

  it("removes provider-supplied terminal escape sequences", () => {
    const view = render(
      <TerminalMarkdown value={"safe\u001b[31munsafe"} height={2} />,
    );
    expect(view.lastFrame()).toContain("safeunsafe");
    expect(view.lastFrame()).not.toContain("\u001b");
    view.unmount();
  });
});
