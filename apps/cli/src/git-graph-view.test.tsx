import React from "react";
import { render } from "ink-testing-library";
import { expect, it } from "vitest";
import { SessionView } from "./tui.js";
import type { SessionState } from "./session-controller.js";

it("shows the display-only panel on wide terminals and summary on narrow ones", () => {
  const state: SessionState = {
    started: true,
    busy: false,
    transcript: [],
    shouldExit: false,
    graph: {
      lanes: [{ id: "base", label: "main" }],
      commits: [],
      workingTree: { staged: 0, unstaged: 0, untracked: 0 },
      current: "main",
      fingerprint: "test",
    },
  };
  const wide = render(
    <SessionView
      state={state}
      input=""
      onInput={() => {}}
      onSubmit={() => {}}
      terminalWidth={120}
    />,
  );
  expect(wide.lastFrame()).toContain("Local history");
  expect(wide.lastFrame()).toContain("Display only");
  expect(wide.lastFrame()).toContain("┌");
  wide.unmount();
  const copy = render(
    <SessionView
      state={{ ...state, transcriptOnly: true }}
      input=""
      onInput={() => {}}
      onSubmit={() => {}}
      terminalWidth={120}
    />,
  );
  expect(copy.lastFrame()).not.toContain("Local history");
  expect(copy.lastFrame()).toContain("/copyview");
  copy.unmount();
  const narrow = render(
    <SessionView
      state={state}
      input=""
      onInput={() => {}}
      onSubmit={() => {}}
      terminalWidth={80}
    />,
  );
  expect(narrow.lastFrame()).not.toContain("Local commit graph");
  expect(narrow.lastFrame()).toContain("main · local refs · /graph");
  narrow.unmount();
});
