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
  baseHead?: string;
  current: string;
  upstream?: string;
  ahead?: number;
  behind?: number;
  conflicts?: number;
  base?: string;
  fingerprint: string;
  note?: string;
}

export interface GitGraphSegment {
  text: string;
  tone: string;
  dim?: boolean;
}

export interface GitGraphLine {
  text: string;
  lane: string;
  segments: GitGraphSegment[];
}

interface TopologyRow {
  prefix: string;
  tones: string[];
}

export class GitGraphPresenter {
  lines(graph: GitGraph): GitGraphLine[] {
    const output = [this.workingTreeLine(graph)];
    const toneByOid = new Map(
      graph.commits.map((commit) => [commit.oid, commit.lane]),
    );
    const active: string[] = graph.commits[0] ? [graph.commits[0].oid] : [];

    for (const commit of graph.commits) {
      const row = this.topologyRow(commit, active, toneByOid);
      const references = this.references(graph, commit.oid);
      const suffix = `${commit.subject}${references ? `  ${references}` : ""}`;
      const segments = this.topologySegments(row);
      segments.push({ text: ` ${commit.subject}`, tone: "text" });
      if (references)
        segments.push({ text: `  ${references}`, tone: commit.lane });
      output.push({
        text: `${row.prefix} ${suffix}`,
        lane: commit.lane,
        segments,
      });
    }
    if (graph.note) output.push(this.plainLine(graph.note, "shared", true));
    return output;
  }

  summary(graph: GitGraph): string {
    return `${graph.lanes.map((item) => item.label).join(" ↔ ")} · local refs · /graph`;
  }

  private workingTreeLine(graph: GitGraph): GitGraphLine {
    const { staged, unstaged, untracked } = graph.workingTree;
    const state =
      staged || unstaged || untracked
        ? `+${staged} ~${unstaged} ?${untracked}`
        : "clean";
    return {
      text: `◇ working tree  ${state}`,
      lane: "working",
      segments: [
        { text: "◇", tone: "working" },
        { text: ` working tree  ${state}`, tone: "muted" },
      ],
    };
  }

  private topologyRow(
    commit: GitGraph["commits"][number],
    active: string[],
    toneByOid: Map<string, string>,
  ): TopologyRow {
    let index = active.indexOf(commit.oid);
    if (index < 0) {
      active.push(commit.oid);
      index = active.length - 1;
    }
    const before = [...active];
    const after = [...active];
    after.splice(index, 1);
    for (const [parentIndex, parent] of commit.parents.entries()) {
      if (!after.includes(parent)) after.splice(index + parentIndex, 0, parent);
    }

    const existingParent = commit.parents
      .map((parent) => before.indexOf(parent))
      .find((parentIndex) => parentIndex >= 0);
    const split = after.length > before.length;
    let prefix: string;
    if (existingParent !== undefined && existingParent < index) {
      prefix = `${this.verticalPrefix(existingParent)}├${"─".repeat(
        Math.max(1, (index - existingParent) * 2 - 1),
      )}●`;
    } else {
      prefix = this.regularPrefix(before.length, index);
      if (split) prefix += "─╮";
    }

    const width = Math.max(before.length, after.length);
    const tones = Array.from({ length: width }, (_, laneIndex) => {
      const oid = before[laneIndex] ?? after[laneIndex];
      return toneByOid.get(oid) ?? commit.lane ?? "shared";
    });
    tones[index] = commit.lane;
    active.splice(0, active.length, ...after);
    return { prefix, tones };
  }

  private regularPrefix(lanes: number, node: number): string {
    return Array.from({ length: lanes }, (_, index) =>
      index === node ? "●" : "│",
    ).join(" ");
  }

  private verticalPrefix(lanes: number): string {
    return lanes
      ? `${Array.from({ length: lanes }, () => "│").join(" ")} `
      : "";
  }

  private topologySegments(row: TopologyRow): GitGraphSegment[] {
    const segments: GitGraphSegment[] = [];
    for (const [index, character] of [...row.prefix].entries()) {
      const column = Math.floor(index / 2);
      const tone =
        row.tones[Math.min(column, row.tones.length - 1)] ?? "shared";
      const previous = segments.at(-1);
      if (previous?.tone === tone && previous.dim === (character === " ")) {
        previous.text += character;
      } else {
        segments.push({ text: character, tone, dim: character === " " });
      }
    }
    return segments;
  }

  private references(graph: GitGraph, oid: string): string {
    const references: string[] = [];
    if (oid === graph.head) {
      references.push(
        graph.current === graph.base
          ? `◉ ${graph.current}`
          : `◆ ${graph.current}`,
      );
    }
    if (oid === graph.baseHead && graph.current !== graph.base)
      references.push(`◉ ${graph.base}`);
    if (oid === graph.mergeBase && graph.current !== graph.base)
      references.push("merge base");
    return references.join("  ");
  }

  private plainLine(text: string, lane: string, dim = false): GitGraphLine {
    return {
      text,
      lane,
      segments: [{ text, tone: lane, dim }],
    };
  }
}
