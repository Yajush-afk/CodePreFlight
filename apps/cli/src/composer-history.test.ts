import { describe, expect, it } from "vitest";
import { ComposerHistory } from "./composer-history.js";

describe("ComposerHistory", () => {
  it("deduplicates adjacent submissions and returns to an empty draft", () => {
    const history = new ComposerHistory();
    history.record("/status");
    history.record("/status");
    history.record("Explain finding 1");

    expect(history.navigate("previous")).toBe("Explain finding 1");
    expect(history.navigate("previous")).toBe("/status");
    expect(history.navigate("next")).toBe("Explain finding 1");
    expect(history.navigate("next")).toBe("");
  });

  it("drops ephemeral history on session disposal", () => {
    const history = new ComposerHistory();
    history.record("private question");
    history.clear();
    expect(history.navigate("previous")).toBe("");
  });
});
