// A run's model architecture, captured from one training step (research_hub/modelgraph.py): scroll and zoom,
// open and close blocks, click a layer to see what flows in and out, click a loss to see everything that feeds it,
// and replay the forward and backward pass. Drawn as SVG by hand; loaded only when the Model tab opens.
import { Maximize, Minus, Play, Plus, Rewind } from "lucide-react";
import * as React from "react";
import { Segmented } from "@/components/ui/controls";
import { Button, Card } from "@/components/ui/primitives";
import type { GraphNode, ModelGraphData } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

type Mode = "shapes" | "gradients" | "activations";
interface VNode extends Omit<GraphNode, "kind"> {
  kind: GraphNode["kind"] | "group"; members: GraphNode[]; w: number; h: number; x: number; y: number; rank: number; ins: string[]; outs: string[];
}
interface Route { from: string; to: string; shape?: number[] | null; d: string; mid: { x: number; y: number } }
interface Layout { nodes: VNode[]; byId: Map<string, VNode>; routes: Route[]; ranks: number }
interface Bend { id: string; rank: number; w: number; up: string[]; down: string[]; x: number; i: number }

const NS = "http://www.w3.org/2000/svg";
const FAMILY: [RegExp, string][] = [[/Conv|Upsample/, "conv"], [/Norm/, "norm"], [/ReLU|GELU|SiLU|Sigmoid|Tanh|Softmax|Relu|Gelu|Silu/, "act"], [/Linear|Embedding/, "linear"], [/Attention/, "attn"]];
const family = (t: string) => FAMILY.find(([re]) => re.test(t))?.[1] ?? "pool";
const shape = (s?: number[] | null) => (s == null ? "" : s.length ? s.join(" × ") : "scalar");
const count = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : String(v));
const sci = (v?: number | null) => (v == null ? "—" : v !== 0 && (Math.abs(v) < 0.01 || Math.abs(v) >= 1000) ? v.toExponential(1) : fmt(v));
const groupsOf = (g: ModelGraphData) => [...new Set(g.nodes.map((n) => n.group).filter((x): x is string => !!x))];
const lossName = (n: { loss?: string }) => (n.loss === "total" ? "Total loss" : n.loss ?? "loss");

/** The graph with every collapsed block replaced by one node. */
function visible(g: ModelGraphData, collapsed: Set<string>) {
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const rep = (n: GraphNode) => {
    const parts = (n.group ?? "").split(".");
    for (let i = 1; n.group && i <= parts.length; i++) { const p = parts.slice(0, i).join("."); if (collapsed.has(p)) return `group:${p}`; }
    return n.id;
  };
  const nodes = new Map<string, Omit<VNode, "w" | "h" | "x" | "y" | "rank" | "ins" | "outs">>();
  for (const n of g.nodes) {
    const r = rep(n);
    if (r === n.id) { nodes.set(r, { ...n, members: [] }); continue; }
    const name = r.slice(6);
    const v = nodes.get(r) ?? { id: r, kind: "group" as const, name, type: g.blocks?.[name] ?? "", members: [], params: 0, grad_norm: 0 };
    v.members.push(n); v.params = (v.params ?? 0) + (n.params ?? 0); v.grad_norm = Math.max(v.grad_norm ?? 0, n.grad_norm ?? 0);
    nodes.set(r, v);
  }
  const edges = new Map<string, { from: string; to: string; shape?: number[] | null }>();
  for (const e of g.edges) {
    const a = rep(byId.get(e.from)!), b = rep(byId.get(e.to)!);
    if (a !== b && !edges.has(`${a}→${b}`)) edges.set(`${a}→${b}`, { from: a, to: b, shape: e.shape });
  }
  for (const v of nodes.values()) if (v.kind === "group") {
    v.out_shape = [...edges.values()].find((e) => e.from === v.id)?.shape ?? null;
    const types: Record<string, number> = {};
    v.members.forEach((m) => { types[m.type] = (types[m.type] ?? 0) + 1; });
    v.detail = Object.entries(types).map(([t, c]) => (c > 1 ? `${t} ×${c}` : t)).join(", ");
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** Blocks to start collapsed: open one level of nesting at a time while the picture stays small enough to read. */
function overview(g: ModelGraphData): Set<string> {
  const collapsed = new Set<string>();
  if (g.nodes.length <= 22) return collapsed;
  groupsOf(g).forEach((p) => p.split(".").forEach((_, i, a) => collapsed.add(a.slice(0, i + 1).join("."))));
  const shown = () => visible(g, collapsed).nodes;
  for (let level = 0; ; level++) {
    const closed = shown().filter((n) => n.kind === "group").map((n) => n.name);
    if (!closed.length) break;
    closed.forEach((c) => collapsed.delete(c));
    if (shown().length <= 48) continue;
    closed.forEach((c) => collapsed.add(c));
    if (!level) for (const c of closed) { collapsed.delete(c); if (shown().length > 48) collapsed.add(c); } // at the top, open what fits
    break;
  }
  return collapsed;
}

const size = (n: { kind: string; type: string; out_shape?: number[] | null }): [number, number] =>
  n.kind === "op" ? [Math.max(96, 30 + 6.6 * (n.type.length + (n.out_shape ? shape(n.out_shape).length + 3 : 0))), 30] : n.kind === "group" ? [236, 66] : [218, 62];

/** Layered layout: rank by longest path, order by neighbours, route long edges through bend points. */
function layout(vis: ReturnType<typeof visible>): Layout {
  const N = new Map<string, VNode>(vis.nodes.map((n) => { const [w, h] = size(n); return [n.id, { ...n, w, h, x: 0, y: 0, rank: 0, ins: [], outs: [] }]; }));
  vis.edges.forEach((e) => { N.get(e.from)!.outs.push(e.to); N.get(e.to)!.ins.push(e.from); });
  // a collapsed block can both feed and be fed by a neighbour; ignore the returning edge when ranking
  const mark = new Map<string, number>(), back = new Set<string>();
  const walk = (id: string) => { mark.set(id, 1); for (const t of N.get(id)!.outs) { if (mark.get(t) === 1) back.add(`${id}→${t}`); else if (!mark.has(t)) walk(t); } mark.set(id, 2); };
  for (const n of N.values()) if (!mark.has(n.id)) walk(n.id);
  for (const key of back) { const [a, b] = key.split("→"); N.get(a)!.outs = N.get(a)!.outs.filter((x) => x !== b); N.get(b)!.ins = N.get(b)!.ins.filter((x) => x !== a); }
  const indeg = new Map([...N.values()].map((n) => [n.id, n.ins.length])), queue = [...N.values()].filter((n) => !n.ins.length).map((n) => n.id);
  while (queue.length) { const n = N.get(queue.shift()!)!; for (const t of n.outs) { const m = N.get(t)!; m.rank = Math.max(m.rank, n.rank + 1); indeg.set(t, indeg.get(t)! - 1); if (!indeg.get(t)) queue.push(t); } }
  for (const n of N.values()) if (!n.ins.length && n.outs.length) n.rank = Math.min(...n.outs.map((t) => N.get(t)!.rank)) - 1; // an input sits right above its first consumer
  const L = new Map<string, Bend>([...N.values()].map((n) => [n.id, { id: n.id, rank: n.rank, w: n.w, up: [], down: [], x: 0, i: 0 }]));
  const paths: { from: string; to: string; shape?: number[] | null; path: string[] }[] = [];
  let bends = 0;
  for (const e of vis.edges) {
    if (back.has(`${e.from}→${e.to}`)) continue;
    const a = N.get(e.from)!, b = N.get(e.to)!, path = [e.from];
    for (let r = a.rank + 1; r < b.rank; r++) { const id = `bend:${bends++}`; L.set(id, { id, rank: r, w: 16, up: [], down: [], x: 0, i: 0 }); path.push(id); }
    path.push(e.to);
    for (let i = 0; i + 1 < path.length; i++) { L.get(path[i])!.down.push(path[i + 1]); L.get(path[i + 1])!.up.push(path[i]); }
    paths.push({ ...e, path });
  }
  const layers: Bend[][] = [], seen = new Set<string>();
  const visit = (id: string) => { if (seen.has(id)) return; seen.add(id); const n = L.get(id)!; (layers[n.rank] ??= []).push(n); n.down.forEach(visit); };
  [...L.values()].filter((n) => !n.up.length).sort((a, b) => a.rank - b.rank).forEach((n) => visit(n.id));
  for (let r = 0; r < layers.length; r++) layers[r] ??= [];
  const index = () => layers.forEach((l) => l.forEach((n, i) => { n.i = i; }));
  const bary = (n: Bend, ids: string[]) => (ids.length ? ids.reduce((s, id) => s + L.get(id)!.i, 0) / ids.length : n.i);
  for (let it = 0; it < 6; it++) {
    index(); for (let r = 1; r < layers.length; r++) { layers[r].sort((a, b) => bary(a, a.up) - bary(b, b.up)); index(); }
    for (let r = layers.length - 2; r >= 0; r--) { layers[r].sort((a, b) => bary(a, a.down) - bary(b, b.down)); index(); }
  }
  const GAP = 30, ROW = 104;
  layers.forEach((l) => { let x = 0; l.forEach((n) => { n.x = x + n.w / 2; x += n.w + GAP; }); l.forEach((n) => { n.x -= x / 2; }); });
  const relax = (l: Bend[], want: number[]) => {  // the average of packing from the left and from the right keeps the order and the gaps
    const left: number[] = [], right: number[] = [];
    l.forEach((n, i) => { left[i] = i ? Math.max(want[i], left[i - 1] + (l[i - 1].w + n.w) / 2 + GAP) : want[i]; });
    for (let i = l.length - 1; i >= 0; i--) right[i] = i < l.length - 1 ? Math.min(want[i], right[i + 1] - (l[i + 1].w + l[i].w) / 2 - GAP) : want[i];
    l.forEach((n, i) => { n.x = (left[i] + right[i]) / 2; });
  };
  const mean = (n: Bend, ids: string[]) => (ids.length ? ids.reduce((s, id) => s + L.get(id)!.x, 0) / ids.length : n.x);
  for (let it = 0; it < 24; it++) {
    for (let r = 1; r < layers.length; r++) relax(layers[r], layers[r].map((n) => mean(n, n.up)));
    for (let r = layers.length - 2; r >= 0; r--) relax(layers[r], layers[r].map((n) => mean(n, n.down)));
  }
  for (const n of N.values()) { n.x = L.get(n.id)!.x; n.y = n.rank * ROW; }
  const routes = paths.map((p) => {
    const a = N.get(p.from)!, b = N.get(p.to)!;
    const pts = p.path.map((id, i) => (i === 0 ? { x: a.x, y: a.y + a.h / 2 } : i === p.path.length - 1 ? { x: b.x, y: b.y - b.h / 2 - 3 } : { x: L.get(id)!.x, y: L.get(id)!.rank * ROW }));
    const d = pts.reduce((s, q, i) => { if (!i) return `M${q.x} ${q.y}`; const o = pts[i - 1], m = (o.y + q.y) / 2; return `${s}C${o.x} ${m} ${q.x} ${m} ${q.x} ${q.y}`; }, "");
    return { from: p.from, to: p.to, shape: p.shape, d, mid: { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 } };
  });
  return { nodes: [...N.values()], byId: N, routes, ranks: layers.length };
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>, parent?: Element, text?: string): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, String(attrs[k]));
  if (text != null) e.textContent = text;
  parent?.appendChild(e);
  return e;
}
const clip = (s: string, n: number, tail = false) => (s.length <= n ? s : tail ? `…${s.slice(1 - n)}` : `${s.slice(0, n - 1)}…`);

export default function ModelGraph({ graph }: { graph: ModelGraphData }) {
  const [collapsed, setCollapsed] = React.useState(() => overview(graph));
  const [sel, setSel] = React.useState<string | null>(null);
  const [upstream, setUpstream] = React.useState(false);
  const [mode, setMode] = React.useState<Mode>("shapes");
  const [status, setStatus] = React.useState("");
  const stage = React.useRef<HTMLDivElement>(null);
  const root = React.useRef<SVGGElement>(null);
  const view = React.useRef({ x: 0, y: 0, k: 1 });
  const dom = React.useRef<{ nodes: Map<string, SVGGElement>; edges: { from: string; to: string; el: SVGPathElement }[] }>({ nodes: new Map(), edges: [] });
  const playing = React.useRef(0);
  const refit = React.useRef(true);    // fit the view after the next draw
  const dragged = React.useRef(false);
  const [tick, setTick] = React.useState(0);
  const G = React.useMemo(() => layout(visible(graph, collapsed)), [graph, collapsed]);
  const picked = sel ? G.byId.get(sel) ?? null : null;

  const apply = () => root.current?.setAttribute("transform", `translate(${view.current.x},${view.current.y}) scale(${view.current.k})`);
  const fit = React.useCallback(() => {
    const s = stage.current!.getBoundingClientRect(), xs = G.nodes.flatMap((n) => [n.x - n.w / 2, n.x + n.w / 2]), ys = G.nodes.flatMap((n) => [n.y - n.h / 2, n.y + n.h / 2]);
    const x0 = Math.min(...xs) - 40, x1 = Math.max(...xs) + 40, y0 = Math.min(...ys) - 50, y1 = Math.max(...ys) + 50;
    const whole = Math.min(1.1, s.width / (x1 - x0), s.height / (y1 - y0)), k = Math.max(whole, Math.min(0.75, s.width / (x1 - x0)));
    // a tall graph is shown readable from the top and scrolled, not shrunk until the text disappears
    view.current = { k, x: (s.width - (x0 + x1) * k) / 2, y: k > whole ? 16 - y0 * k : (s.height - (y0 + y1) * k) / 2 };
    apply();
  }, [G]);
  const zoom = (f: number, mx: number, my: number) => {
    const v = view.current, k = Math.min(3, Math.max(0.12, v.k * f));
    view.current = { k, x: mx - (mx - v.x) * (k / v.k), y: my - (my - v.y) * (k / v.k) };
    apply();
  };
  const select = (id: string | null) => { playing.current++; setSel(id); setUpstream(!!id && G.byId.get(id)?.kind === "loss"); };
  const toggle = (name: string, open: boolean) => {
    const next = new Set(collapsed);
    if (open) next.delete(name); else { next.add(name); [...next].forEach((c) => c.startsWith(`${name}.`) && next.delete(c)); }
    playing.current++; setSel(null); setCollapsed(next);
  };

  React.useEffect(() => {   // wheel scrolls; pinch or Ctrl+wheel zooms around the pointer; drag pans
    const el = stage.current!;
    let drag: { x: number; y: number; vx: number; vy: number } | null = null;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) zoom(Math.exp(-e.deltaY * 0.01), e.clientX - r.left, e.clientY - r.top);
      else { view.current.x -= e.deltaX; view.current.y -= e.deltaY; apply(); }
    };
    const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY, vx: view.current.x, vy: view.current.y }; };
    const move = (e: PointerEvent) => { if (drag && Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) { dragged.current = true; view.current.x = drag.vx + e.clientX - drag.x; view.current.y = drag.vy + e.clientY - drag.y; apply(); } };
    const up = () => { drag = null; };
    el.addEventListener("wheel", wheel, { passive: false }); el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { el.removeEventListener("wheel", wheel); el.removeEventListener("pointerdown", down); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  React.useEffect(() => {   // draw
    const g = root.current!;
    g.replaceChildren();
    const boxes = svg("g", {}, g), edges = svg("g", {}, g), nodes = svg("g", {}, g), labels = svg("g", {}, g);
    const groups = groupsOf(graph);
    for (const grp of groups) {   // outline of each open block that has no blocks inside it
      const mem = G.nodes.filter((n) => n.kind !== "group" && (n.group === grp || (n.group ?? "").startsWith(`${grp}.`)));
      if (!mem.length || groups.some((o) => o.startsWith(`${grp}.`))) continue;
      const x0 = Math.min(...mem.map((n) => n.x - n.w / 2)) - 14, x1 = Math.max(...mem.map((n) => n.x + n.w / 2)) + 14;
      const y0 = Math.min(...mem.map((n) => n.y - n.h / 2)) - 26, y1 = Math.max(...mem.map((n) => n.y + n.h / 2)) + 12;
      svg("rect", { class: "mg-box", x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 12 }, boxes);
      svg("text", { class: "mg-boxlabel", x: x0 + 10, y: y0 + 16 }, boxes, `▾ ${grp}${graph.blocks?.[grp] ? ` · ${graph.blocks[grp]}` : ""}`)
        .addEventListener("click", (ev) => { ev.stopPropagation(); toggle(grp, false); });
    }
    const anc = picked && upstream ? (() => { const s = new Set([picked.id]), todo = [picked.id]; while (todo.length) for (const p of G.byId.get(todo.pop()!)!.ins) if (!s.has(p)) { s.add(p); todo.push(p); } return s; })() : null;
    dom.current = { nodes: new Map(), edges: [] };
    for (const r of G.routes) {
      const cls = !picked ? "" : anc ? (anc.has(r.from) && anc.has(r.to) ? " mg-up" : " mg-dim") : r.to === picked.id ? " mg-in" : r.from === picked.id ? " mg-out" : " mg-dim";
      dom.current.edges.push({ from: r.from, to: r.to, el: svg("path", { class: `mg-edge${cls}`, d: r.d, "marker-end": "url(#mg-arrow)" }, edges) });
      if (picked && !anc && (r.to === picked.id || r.from === picked.id) && r.shape) {
        const text = shape(r.shape), w = text.length * 6.3 + 14, lg = svg("g", { class: `mg-elabel ${r.to === picked.id ? "mg-in" : "mg-out"}` }, labels);
        svg("rect", { x: r.mid.x - w / 2, y: r.mid.y - 9, width: w, height: 18, rx: 9 }, lg);
        svg("text", { x: r.mid.x, y: r.mid.y + 3.5 }, lg, text);
      }
    }
    const hottest = Math.max(...G.nodes.map((n) => Math.log10(n.grad_norm || 1e-12)));
    const third = (n: VNode) => (mode === "gradients" ? (n.grad_norm != null ? `‖∇‖ ${sci(n.grad_norm)}` : "") : mode === "activations" ? (n.act_std != null ? `μ ${sci(n.act_mean)}  σ ${sci(n.act_std)}` : "") : shape(n.out_shape));
    for (const n of G.nodes) {
      const lit = !picked || (anc ? anc.has(n.id) : n.id === picked.id || picked.ins.includes(n.id) || picked.outs.includes(n.id));
      const el = svg("g", { class: cn("mg-node", `mg-${n.kind}`, n.id === picked?.id && "mg-sel", !lit && "mg-dim"), transform: `translate(${n.x - n.w / 2},${n.y - n.h / 2})` }, nodes);
      dom.current.nodes.set(n.id, el);
      const body = svg("rect", { class: "mg-body", width: n.w, height: n.h, rx: n.kind === "op" ? 15 : 10 }, el);
      if (mode === "gradients" && n.grad_norm) body.style.fill = `color-mix(in srgb, hsl(var(--mg-out)) ${Math.round(Math.max(0, 1 - (hottest - Math.log10(n.grad_norm)) / 3) * 30)}%, hsl(var(--card)))`;
      if (n.kind === "op") {
        const t = svg("text", { class: "mg-t1", x: n.w / 2, y: 19, "text-anchor": "middle" }, el, n.type);
        if (third(n)) svg("tspan", { class: "mg-t2", dx: 7 }, t, third(n));
      } else {
        const colour = n.kind === "input" ? "success" : n.kind === "loss" ? "danger" : n.kind === "group" ? "primary" : `mg-${family(n.type)}`;
        svg("rect", { x: 0, y: 8, width: 4, height: n.h - 16, rx: 2, fill: `hsl(var(--${colour}))` }, el);
        const title = n.kind === "input" ? `Input${n.name && n.name !== "input" ? ` · ${n.name}` : ""}` : n.kind === "loss" ? lossName(n) : n.kind === "group" ? `▸ ${n.name}` : n.type;
        const sub = n.kind === "loss" ? `${n.type}${n.value != null ? ` = ${sci(n.value)}` : ""}` : n.kind === "group" ? `${n.type ? `${n.type} · ` : ""}${n.members.length} layers` : n.kind === "input" ? n.dtype ?? "" : n.name;
        svg("text", { class: "mg-t1", x: 14, y: 21 }, el, clip(title, 27));
        svg("text", { class: "mg-t2", x: 14, y: 37 }, el, clip(sub, 31, true));
        svg("text", { class: "mg-t3", x: 14, y: n.h - 9 }, el, third(n));
        if (n.params) svg("text", { class: "mg-t2", x: n.w - 10, y: 21, "text-anchor": "end" }, el, count(n.params));
        if (n.kind === "group") svg("rect", { class: "mg-stack", x: 4, y: n.h - 1, width: n.w - 8, height: 4, rx: 2 }, el);
      }
      el.addEventListener("click", (ev) => { ev.stopPropagation(); select(n.id); });
      el.addEventListener("dblclick", (ev) => { ev.stopPropagation(); if (n.kind === "group") toggle(n.name, true); });
    }
    setStatus("");
    if (refit.current) { refit.current = false; fit(); }
  }, [G, mode, sel, upstream, tick]);

  const play = (backward: boolean) => {
    const token = ++playing.current;
    setSel(null); setMode(backward ? "gradients" : "shapes");
    const step = Math.max(110, Math.min(260, 4200 / G.ranks)), order = [...Array(G.ranks).keys()];
    if (backward) order.reverse();
    setTimeout(() => order.forEach((rank, i) => setTimeout(() => {   // after the redraw for the new mode
      if (token !== playing.current) return;
      G.nodes.filter((n) => n.rank === rank).forEach((n) => dom.current.nodes.get(n.id)?.classList.add(backward ? "mg-lit-b" : "mg-lit-f"));
      dom.current.edges.filter((e) => G.byId.get(backward ? e.to : e.from)!.rank === rank).forEach((e) => e.el.classList.add(backward ? "mg-flow-b" : "mg-flow-f"));
      setStatus(backward ? `Backward pass: gradients flowing back from the loss, step ${i + 1} of ${G.ranks}` : `Forward pass: data flowing from the input, step ${i + 1} of ${G.ranks}`);
    }, i * step)), 60);
    setTimeout(() => { if (token === playing.current) setTick((t) => t + 1); }, order.length * step + 1500);
  };
  const centre = (): [number, number] => { const r = stage.current!.getBoundingClientRect(); return [r.width / 2, r.height / 2]; };
  const losses = G.nodes.filter((n) => n.kind === "loss");
  const ins = picked ? G.routes.filter((r) => r.to === picked.id) : [], outs = picked ? G.routes.filter((r) => r.from === picked.id) : [];
  const label = (id: string) => { const m = G.byId.get(id)!; return m.kind === "loss" ? lossName(m) : m.kind === "input" ? `input ${m.name}` : m.kind === "op" ? m.type : m.name; };
  const facts: [string, React.ReactNode][] = !picked ? [] : ([
    ["Value", picked.kind === "loss" && picked.value != null ? sci(picked.value) : null],
    [picked.kind === "group" ? "Contains" : "Settings", picked.detail],
    ["Parameters", picked.params ? picked.params.toLocaleString() : null],
    ["Input shape", picked.in_shapes?.length ? picked.in_shapes.map((s, i) => <div key={i}>{shape(s)}</div>) : null],
    ["Output shape", picked.out_shape ? shape(picked.out_shape) : null],
    ["Activation", picked.act_std != null ? `mean ${sci(picked.act_mean)}, std ${sci(picked.act_std)}` : null],
    ["Gradient norm", picked.grad_norm != null ? sci(picked.grad_norm) : null],
  ] as [string, React.ReactNode][]).filter((f) => f[1]);

  return (
    <div className="mg space-y-3">
      <Card className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <Segmented size="sm" value={mode} onChange={setMode} options={[{ value: "shapes", label: "Shapes" }, { value: "gradients", label: "Gradients" }, { value: "activations", label: "Activations" }]} />
        <span className="hidden text-[12px] text-muted-foreground lg:inline">{graph.model} · {count(graph.params)} parameters{graph.trainable != null && graph.trainable !== graph.params ? ` (${count(graph.trainable)} trainable)` : ""} · {G.nodes.length} of {graph.nodes.length} nodes shown</span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="primary" onClick={() => play(false)}><Play className="h-3.5 w-3.5" /> Forward pass</Button>
          <Button size="sm" onClick={() => play(true)}><Rewind className="h-3.5 w-3.5" /> Backward pass</Button>
          <Button size="sm" onClick={() => { refit.current = true; setSel(null); setCollapsed(new Set()); }}>Expand all</Button>
          <Button size="sm" onClick={() => { refit.current = true; setSel(null); setCollapsed(overview(graph)); }}>Overview</Button>
          <Button size="icon" onClick={() => zoom(1.25, ...centre())} aria-label="Zoom in"><Plus className="h-3.5 w-3.5" /></Button>
          <Button size="icon" onClick={() => zoom(0.8, ...centre())} aria-label="Zoom out"><Minus className="h-3.5 w-3.5" /></Button>
          <Button size="icon" onClick={fit} aria-label="Fit to view"><Maximize className="h-3.5 w-3.5" /></Button>
        </div>
      </Card>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div ref={stage} className="card relative h-[max(520px,calc(100vh-250px))] cursor-grab touch-none overflow-hidden active:cursor-grabbing" onClick={() => { if (dragged.current) dragged.current = false; else select(null); }}>
          <svg className="block h-full w-full select-none" role="img" aria-label={`Architecture of ${graph.model}`}>
            <defs><marker id="mg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="context-stroke" /></marker></defs>
            <g ref={root} />
          </svg>
          <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border bg-card px-2.5 py-1 text-[11.5px] text-muted-foreground shadow-card">{status || "Scroll or drag to move · Ctrl+scroll to zoom · click a layer · double-click a block to open it"}</div>
        </div>
        <Card className="h-fit p-4 text-[12.5px]">
          {picked ? (
            <>
              <h2 className="text-[15px] font-semibold tracking-tight">{picked.kind === "loss" ? lossName(picked) : picked.kind === "group" ? picked.name : picked.kind === "input" ? `Input ${picked.name}` : picked.type}</h2>
              <div className="mt-0.5 break-all font-mono text-[11.5px] text-muted-foreground">{picked.kind === "module" ? picked.name : picked.kind === "op" ? `operation${picked.group ? ` in ${picked.group}` : ""}` : picked.kind === "group" ? `${picked.members.length} layers · double-click to open` : picked.kind === "loss" ? `computed by ${picked.type}` : picked.dtype}</div>
              <dl className="my-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">{facts.map(([k, v]) => <React.Fragment key={k}><dt className="whitespace-nowrap text-muted-foreground">{k}</dt><dd className="break-words text-right font-mono">{v}</dd></React.Fragment>)}</dl>
              {[["Comes from", ins, "from", "text-[hsl(var(--mg-in))]"] as const, ["Goes to", outs, "to", "text-[hsl(var(--mg-out))]"] as const].map(([title, list, end, tone]) => list.length > 0 && (
                <div key={title} className="mt-3"><div className={cn("label mb-1.5", tone)}>{title}</div>
                  {list.map((r) => <button key={r[end]} onClick={() => select(r[end])} className="mb-1 flex w-full justify-between gap-2 rounded-md border px-2 py-1 text-left hover:border-primary focus-ring"><span className="truncate">{label(r[end])}</span><span className="shrink-0 font-mono text-muted-foreground">{shape(r.shape)}</span></button>)}
                </div>
              ))}
              <div className="mt-4 flex flex-wrap gap-2"><Button size="sm" onClick={() => setUpstream(!upstream)}>{upstream ? "Show neighbours only" : "Show everything that feeds this"}</Button><Button size="sm" variant="ghost" onClick={() => select(null)}>Clear</Button></div>
            </>
          ) : (
            <>
              <h2 className="text-[15px] font-semibold tracking-tight">{graph.model}</h2>
              <p className="mt-2 leading-relaxed text-muted-foreground">Captured from the first training step. Click a layer to light up what flows <b className="text-[hsl(var(--mg-in))]">into</b> it and <b className="text-[hsl(var(--mg-out))]">out</b> of it, with tensor shapes on the connections. Click a loss to see everything that feeds it.</p>
              <div className="label mb-1.5 mt-4">Colours</div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground">{[["mg-conv", "Convolution"], ["mg-norm", "Normalisation"], ["mg-act", "Activation"], ["mg-linear", "Linear, embedding"], ["mg-attn", "Attention"], ["mg-pool", "Other layers"], ["success", "Input"], ["danger", "Loss"]].map(([c, t]) => <span key={c} className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm" style={{ background: `hsl(var(--${c}))` }} />{t}</span>)}</div>
              {losses.length > 0 && <><div className="label mb-1.5 mt-4">Losses</div>{losses.map((l) => <button key={l.id} onClick={() => select(l.id)} className="mb-1 flex w-full justify-between gap-2 rounded-md border px-2 py-1 text-left hover:border-primary focus-ring"><span className="truncate">{lossName(l)}</span><span className="font-mono text-muted-foreground">{sci(l.value)}</span></button>)}</>}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
