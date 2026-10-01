import { describe, expect, it } from "vitest";
import {
  EngineProtocolError,
  parseEngineEvent,
  PROTOCOL_VERSION,
} from "./protocol.js";
import {
  FINDING_LIFECYCLE_STATES,
  FINDING_SEVERITIES,
  GIT_OPERATION_RISK_LEVELS,
} from "./protocol.generated.js";

describe("parseEngineEvent", () => {
  it("publishes the v4 finding and Git contract vocabularies", () => {
    expect(PROTOCOL_VERSION).toBe(4);
    expect(FINDING_SEVERITIES).toEqual(["critical", "high", "medium", "low"]);
    expect(FINDING_LIFECYCLE_STATES).toEqual([
      "open",
      "needs_rereview",
      "resolved",
      "dismissed",
    ]);
    expect(GIT_OPERATION_RISK_LEVELS).toContain("irreversible");
  });

  it("parses a valid event", () => {
    expect(
      parseEngineEvent(
        JSON.stringify({
          protocolVersion: 4,
          requestId: "r1",
          event: "complete",
          payload: {},
        }),
      ).event,
    ).toBe("complete");
  });

  it("rejects incompatible versions", () => {
    expect(() =>
      parseEngineEvent(
        JSON.stringify({ protocolVersion: 1, requestId: "r1", event: "ready" }),
      ),
    ).toThrow(/rebuild or reinstall/);
  });

  it("rejects unknown event names", () => {
    expect(() =>
      parseEngineEvent(
        JSON.stringify({
          protocolVersion: 4,
          requestId: "r1",
          event: "surprise",
        }),
      ),
    ).toThrow(EngineProtocolError);
  });
});
