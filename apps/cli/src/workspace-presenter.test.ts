import { describe, expect, it } from "vitest";
import { WorkspacePresenter } from "./workspace-presenter.js";

describe("WorkspacePresenter transcript", () => {
  it("preserves fenced code metadata while removing fence markers", () => {
    const lines = new WorkspacePresenter().transcript(
      [
        {
          id: "answer",
          kind: "answer",
          body: "## Fix\n```ts\nconst safe = true;\n```",
        },
      ],
      80,
      20,
    );
    expect(lines.map((line) => line.text)).not.toContain("```ts");
    expect(lines).toContainEqual({ text: "const safe = true;", code: true });
  });
});
