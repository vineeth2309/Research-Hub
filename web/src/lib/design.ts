// Designs are plain data: boxes, groups and text with a position, and arrows between them. These helpers keep that
// data consistent while it is edited, and compare two revisions.
import type { DesignEdge, DesignGraph, DesignKind, DesignNode } from "./api";

export const COLORS = ["neutral", "blue", "green", "amber", "red", "violet"] as const;
export type Mark = "added" | "changed" | "removed";
export const edgeKey = (e: DesignEdge) => `${e.from}->${e.to}`;
const area = (n: DesignNode) => n.w * n.h;

/** Membership follows the drawing: a node belongs to the smallest group that holds its centre. */
export function regroup(nodes: DesignNode[]): DesignNode[] {
  const groups = nodes.filter((n) => n.kind === "group");
  return nodes.map((n) => {
    const cx = n.x + n.w / 2, cy = n.y + n.h / 2;
    const holder = groups
      .filter((g) => g.id !== n.id && (n.kind !== "group" || area(g) > area(n)) && cx >= g.x && cx <= g.x + g.w && cy >= g.y && cy <= g.y + g.h)
      .sort((a, b) => area(a) - area(b))[0];
    const next = { ...n };
    if (holder) next.group = holder.id;
    else delete next.group;
    return next;
  });
}

/** Everything inside a group, at any depth. */
export function members(nodes: DesignNode[], id: string): Set<string> {
  const out = new Set<string>();
  let grew = true;
  while (grew) {
    grew = false;
    for (const n of nodes) if (n.group && !out.has(n.id) && (n.group === id || out.has(n.group))) { out.add(n.id); grew = true; }
  }
  return out;
}

export function freshId(nodes: DesignNode[], kind: DesignKind): string {
  const taken = new Set(nodes.map((n) => n.id));
  let i = 1;
  while (taken.has(`${kind}-${i}`)) i++;
  return `${kind}-${i}`;
}

export interface Box { x: number; y: number; w: number; h: number }
const overlap = (a: Box, b: Box, gap = 0) => a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap;

/** Which sides of two boxes an arrow should leave and enter: [from side, to side] as t, r, b or l. An arrow whose
 * straight path would cross one of `between` leaves and enters on the same side instead, and so curves around. */
export function sides(a: Box, b: Box, between: Box[] = []): [string, string] {
  const ax = a.x + a.w / 2, ay = a.y + a.h / 2, dx = b.x + b.w / 2 - ax, dy = b.y + b.h / 2 - ay;
  const stacked = a.x < b.x + b.w && b.x < a.x + a.w, beside = a.y < b.y + b.h && b.y < a.y + a.h;
  const vertical = stacked !== beside ? stacked : Math.abs(dy) >= Math.abs(dx);
  const crossed = between.some((o) => [0.2, 0.35, 0.5, 0.65, 0.8].some((t) => { const x = ax + dx * t, y = ay + dy * t; return x > o.x && x < o.x + o.w && y > o.y && y < o.y + o.h; }));
  if (crossed) return vertical ? ["r", "r"] : ["b", "b"];
  return vertical ? (dy >= 0 ? ["b", "t"] : ["t", "b"]) : dx >= 0 ? ["r", "l"] : ["l", "r"];
}

/** `next` with what `base` had and `next` dropped added back, and a mark on everything that differs. Moving or
 * resizing a node is not a change; its text, notes, colour, kind and group are. */
export function diffDesign(base: DesignGraph, next: DesignGraph): { graph: DesignGraph; marks: Record<string, Mark> } {
  const marks: Record<string, Mark> = {};
  const was = new Map(base.nodes.map((n) => [n.id, n])), now = new Set(next.nodes.map((n) => n.id));
  for (const n of next.nodes) {
    const old = was.get(n.id);
    if (!old) marks[n.id] = "added";
    else if (old.label !== n.label || (old.detail ?? "") !== (n.detail ?? "") || (old.color ?? "") !== (n.color ?? "") || old.kind !== n.kind || (old.group ?? "") !== (n.group ?? "")) marks[n.id] = "changed";
  }
  // what was removed is drawn where it stood, moved aside if something new now stands there
  const solid = next.nodes.filter((n) => n.kind !== "group");
  const gone = base.nodes.filter((n) => !now.has(n.id)).map((n) => {
    if (n.kind === "group") return n;
    const step = n.h + 24, spots = [0, 1, -1, 2, -2, 3, -3].map((k) => ({ ...n, y: n.y + k * step }));
    const free = spots.find((s) => !solid.some((o) => overlap(s, o, 8))) ?? n;
    solid.push(free);
    return free;
  });
  for (const n of gone) marks[n.id] = "removed";
  const wasEdge = new Map(base.edges.map((e) => [edgeKey(e), e])), nowEdge = new Set(next.edges.map(edgeKey));
  for (const e of next.edges) {
    const old = wasEdge.get(edgeKey(e));
    if (!old) marks[edgeKey(e)] = "added";
    else if ((old.label ?? "") !== (e.label ?? "") || !!old.dashed !== !!e.dashed) marks[edgeKey(e)] = "changed";
  }
  const goneEdges = base.edges.filter((e) => !nowEdge.has(edgeKey(e)));
  for (const e of goneEdges) marks[edgeKey(e)] = "removed";
  return { graph: { nodes: [...next.nodes, ...gone], edges: [...next.edges, ...goneEdges] }, marks };
}
