import { afterEach, describe, expect, it, vi } from "vitest";
import { printValue } from "./format.js";

describe("direct command formatting", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("removes terminal control sequences from human-readable Git previews", () => {
    let output = "";
    vi.spyOn(process.stdout, "write").mockImplementation((value) => {
      output += String(value);
      return true;
    });

    printValue(
      {
        preview:
          "safe\u001b]8;;https://example.test\u0007click\u001b]8;;\u0007",
      },
      false,
    );

    expect(output).toContain("safeclick");
    expect(output).not.toContain("\u001b");
    expect(output).not.toContain("https://example.test");
  });
});
