export interface GitGraph {
  lanes: Array<{ id: string; label: string }>;
  commits: Array<{
    oid: string;
    parents: string[];
    subject: string;
    lane: string;
  }>;
  workingTree: { staged: number; unstaged: number; untracked: number };
  mergeBase?: string;
  head?: string;
  current: string;
  upstream?: string;
  ahead?: number;
  behind?: number;
  conflicts?: number;
  base?: string;
  fingerprint: string;
  note?: string;
}

export class GitGraphPresenter {
  lines(graph: GitGraph): Array<{ text: string; lane: string }> {
    const dual = graph.lanes.length > 1;
    const output = graph.lanes.map((lane) => ({
      text: `${lane.id === "base" ? "B" : "C"} │ ${lane.label}`,
      lane: lane.id,
    }));
    output.push({
      text: `◇ working tree +${graph.workingTree.staged} ~${graph.workingTree.unstaged} ?${graph.workingTree.untracked}`,
      lane: "current",
    });
    for (const commit of graph.commits) {
      const marker = !dual
        ? "●"
        : commit.lane === "base"
          ? "● │"
          : commit.lane === "current"
            ? "│ ●"
            : "└─◆";
      output.push({
        text: `${marker} ${commit.oid.slice(0, 7)} ${commit.oid === graph.mergeBase ? "merge base · " : ""}${commit.subject}`,
        lane: commit.lane,
      });
    }
    if (graph.note) output.push({ text: graph.note, lane: "shared" });
    return output;
  }
  summary(graph: GitGraph): string {
    return `${graph.lanes.map((item) => item.label).join(" ↔ ")} · local refs · /graph`;
  }
}
