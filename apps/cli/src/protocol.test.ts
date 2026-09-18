import { describe, expect, it } from "vitest";
import { EngineProtocolError, parseEngineEvent } from "./protocol.js";

describe("parseEngineEvent", () => {
  it("parses a valid event", () => {
    expect(
      parseEngineEvent(
        JSON.stringify({
          protocolVersion: 2,
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
    ).toThrow(EngineProtocolError);
  });

  it("rejects unknown event names", () => {
    expect(() =>
      parseEngineEvent(
        JSON.stringify({
          protocolVersion: 2,
          requestId: "r1",
          event: "surprise",
        }),
      ),
    ).toThrow(EngineProtocolError);
  });
});
