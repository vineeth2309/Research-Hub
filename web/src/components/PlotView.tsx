// Draws a logged chart (see research_hub/plots.py) with Observable Plot, in the dashboard's own colours.
// Loaded on demand, so pages without charts do not pay for the plotting library.
import * as Plot from "@observablehq/plot";
import * as React from "react";
import type { ChartSpec } from "@/lib/api";
import { useHub } from "@/lib/state";
import { PALETTE, fmt } from "@/lib/utils";

type Cell = number | string | boolean | null;
type Row = Record<string, Cell>;
type Ref = { x?: number; y?: number; diagonal?: boolean };
interface Options {
  xlabel?: string; ylabel?: string; xlog?: boolean; ylog?: boolean; xdomain?: [number, number]; ydomain?: [number, number];
  refs?: Ref[]; xorder?: string[]; yorder?: string[]; points?: boolean; curve?: string; stack?: boolean; horizontal?: boolean;
  annotate?: boolean; diverging?: boolean; percent?: boolean; square?: boolean;
}
type RGB = [number, number, number];

const CURVES: Record<string, Plot.CurveName> = { step: "step", "step-after": "step-after", "step-before": "step-before", smooth: "catmull-rom" };

function rowsOf(spec: ChartSpec): Row[] {
  const cols = spec.data.columns, names = Object.keys(cols);
  return Array.from({ length: names.length ? cols[names[0]].length : 0 }, (_, i) => Object.fromEntries(names.map((k) => [k, cols[k][i]])));
}

/** Theme colours as the browser resolves them, so charts follow light and dark mode. */
function palette() {
  const ctx = document.createElement("canvas").getContext("2d")!;
  const style = getComputedStyle(document.documentElement);
  const rgb = (name: string): RGB => {
    ctx.fillStyle = `hsl(${style.getPropertyValue(name).trim().split(/\s+/).join(", ")})`;
    const hex = ctx.fillStyle as string;
    return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as RGB;
  };
  const str = (c: RGB) => `rgb(${c.join(",")})`;
  const c = { primary: rgb("--primary"), card: rgb("--card"), fg: rgb("--foreground"), muted: rgb("--muted-foreground"), border: rgb("--border"), danger: rgb("--danger"), onPrimary: rgb("--primary-foreground") };
  const mix = (a: RGB, b: RGB, t: number) => str(a.map((v, i) => Math.round(v + (b[i] - v) * t)) as RGB);
  return {
    primary: str(c.primary), card: str(c.card), fg: str(c.fg), muted: str(c.muted), border: str(c.border), onPrimary: str(c.onPrimary),
    sequential: (t: number) => mix(c.card, c.primary, t),
    diverging: (t: number) => (t < 0.5 ? mix(c.danger, c.card, t * 2) : mix(c.card, c.primary, t * 2 - 1)),
  };
}

const isNum = (v: Cell): v is number => typeof v === "number";
const extent = (values: Cell[]): [number, number] => { const n = values.filter(isNum); return [Math.min(...n), Math.max(...n)]; };
const count = (v: number) => (Number.isInteger(v) ? v.toLocaleString() : fmt(v));
const longest = (labels: string[]) => labels.reduce((m, s) => Math.max(m, s.length), 0);

function build(spec: ChartSpec, width: number, height: number): Element {
  const e = spec.encoding, o = spec.options as Options, data = rowsOf(spec), c = palette();
  const f = (col: string) => (d: Row) => d[col];
  const cat = (col: string) => (d: Row) => String(d[col] ?? "");
  const tip = { fill: c.card, stroke: c.border, fontSize: 11.5 };
  // every column that is not already on an axis shows up in the hover tip
  const used = new Set([e.x, e.y, e.color, e.low, e.high, e.value, e.group, e.density, e.q1, e.q3, e.median, e.outlier]);
  const channels = Object.fromEntries(Object.keys(spec.data.columns).filter((k) => !used.has(k)).slice(0, 5).map((k) => [k, { value: f(k), label: k }]));
  const curve = CURVES[o.curve ?? ""] ?? "linear";
  const one = !e.color;
  const colours = e.color ? [...new Set(data.map(cat(e.color)))] : [];
  const numericColour = !!e.color && spec.kind === "scatter" && data.some((d) => isNum(d[e.color]));
  const colour = (col: string) => (numericColour ? f(col) : cat(col));
  let color: Plot.ScaleOptions | undefined = e.color
    ? numericColour ? { type: "linear", scheme: "viridis", legend: true, label: e.color }
      : { domain: colours, range: colours.map((_, i) => PALETTE[i % PALETTE.length]), legend: colours.length <= 12 }
    : undefined;
  const axis = (label: string | undefined, column: string | undefined, log?: boolean, domain?: [number, number]): Plot.ScaleOptions =>
    ({ label: label === "" ? null : label ?? column, type: log ? "log" : undefined, domain });
  let x: Plot.ScaleOptions = axis(o.xlabel, e.x, o.xlog, o.xdomain), y: Plot.ScaleOptions = { ...axis(o.ylabel, e.y, o.ylog, o.ydomain), grid: true };
  let fx: Plot.ScaleOptions | undefined, fy: Plot.ScaleOptions | undefined;
  let marginLeft = 52, marginBottom = 38;
  const marks: Plot.Markish[] = [];
  const dashed = { stroke: c.muted, strokeOpacity: 0.7, strokeDasharray: "4 3" };
  const references = () => (o.refs ?? []).map((r) => {
    if (r.x != null) return Plot.ruleX([r.x], dashed);
    if (r.y != null) return Plot.ruleY([r.y], dashed);
    const [x0, x1] = o.xdomain ?? extent(data.map(f(e.x))), [y0, y1] = o.ydomain ?? extent(data.map(f(e.y)));
    const lo = Math.max(x0, y0), hi = Math.min(x1, y1);
    return Plot.line([[lo, lo], [hi, hi]], dashed);
  });

  if (spec.kind === "line" || spec.kind === "area") {
    marks.push(...references());
    if (spec.kind === "area") marks.push(o.stack
      ? Plot.areaY(data, { x: f(e.x), y: f(e.y), fill: one ? c.primary : cat(e.color), fillOpacity: 0.55, curve })
      : Plot.areaY(data, { x: f(e.x), y1: 0, y2: f(e.y), z: one ? undefined : cat(e.color), fill: one ? c.primary : cat(e.color), fillOpacity: 0.18, curve }));
    if (e.low && e.high) marks.push(Plot.areaY(data, { x: f(e.x), y1: f(e.low), y2: f(e.high), z: one ? undefined : cat(e.color), fill: one ? c.primary : cat(e.color), fillOpacity: 0.14, curve }));
    if (!(spec.kind === "area" && o.stack)) marks.push(Plot.lineY(data, { x: f(e.x), y: f(e.y), stroke: one ? c.primary : cat(e.color), strokeWidth: 1.8, curve }));
    if (o.points) marks.push(Plot.dot(data, { x: f(e.x), y: f(e.y), fill: one ? c.primary : cat(e.color), r: 3, stroke: c.card, strokeWidth: 1 }));
    if (!(spec.kind === "area" && o.stack)) marks.push(Plot.tip(data, Plot.pointer({ x: f(e.x), y: f(e.y), channels: one ? channels : { [e.color]: cat(e.color), ...channels }, ...tip })));
  } else if (spec.kind === "scatter") {
    const dense = data.length > 2000;
    marks.push(...references(), Plot.dot(data, { x: f(e.x), y: f(e.y), fill: one ? c.primary : colour(e.color), r: e.size ? f(e.size) : dense ? 1.6 : 2.6, fillOpacity: dense || e.size ? 0.5 : 0.78, channels, tip }));
  } else if (spec.kind === "bar") {
    const names = o.xorder ?? [...new Set(data.map(cat(e.x)))];
    const grouped = !one && !o.stack;
    const value: Plot.ScaleOptions = { ...axis(o.ylabel, e.y, o.ylog, o.ydomain), grid: true };
    const band: Plot.ScaleOptions = { domain: names, label: o.xlabel === "" ? null : o.xlabel ?? e.x };
    const fill = one ? c.primary : cat(e.color);
    const floor = o.ylog ? Math.min(...data.map(f(e.y)).filter((v): v is number => isNum(v) && v > 0)) / 2 : 0;
    const base = o.ylog ? [] : [0];
    if (o.horizontal) {
      marginLeft = Math.min(240, 16 + 6.4 * longest(names));
      marks.push(Plot.ruleX(base, { stroke: c.border }), grouped
        ? Plot.barX(data, { fy: cat(e.x), y: cat(e.color), x1: floor, x2: f(e.y), fill, channels, tip })
        : o.stack ? Plot.barX(data, { y: cat(e.x), x: f(e.y), fill, channels, tip }) : Plot.barX(data, { y: cat(e.x), x1: floor, x2: f(e.y), fill, channels, tip }));
      if (e.low && e.high && one) marks.push(Plot.ruleY(data, { y: cat(e.x), x1: f(e.low), x2: f(e.high), stroke: c.fg }));
      x = value;
      y = grouped ? { axis: null } : { ...band, padding: 0.25 };
      fy = grouped ? { ...band, padding: 0.2 } : undefined;
    } else {
      const tilt = longest(names) * names.length * 6.2 > width - 70;
      marginBottom = tilt ? Math.min(110, 26 + 4.6 * longest(names)) : 38;
      marks.push(Plot.ruleY(base, { stroke: c.border }), grouped
        ? Plot.barY(data, { fx: cat(e.x), x: cat(e.color), y1: floor, y2: f(e.y), fill, channels, tip })
        : o.stack ? Plot.barY(data, { x: cat(e.x), y: f(e.y), fill, channels, tip }) : Plot.barY(data, { x: cat(e.x), y1: floor, y2: f(e.y), fill, channels, tip }));
      if (e.low && e.high && one) marks.push(Plot.ruleX(data, { x: cat(e.x), y1: f(e.low), y2: f(e.high), stroke: c.fg }));
      y = value;
      x = grouped ? { axis: null } : { ...band, padding: 0.25, tickRotate: tilt ? -35 : 0 };
      fx = grouped ? { ...band, padding: 0.2, tickRotate: tilt ? -35 : 0 } : undefined;
    }
  } else if (spec.kind === "histogram") {
    x = axis(o.xlabel, "value", o.xlog, o.xdomain);
    y = { ...axis(o.ylabel, e.value, o.ylog, o.ydomain), grid: true };
    marks.push(Plot.rectY(data, { x1: f(e.low), x2: f(e.high), y1: 0, y2: f(e.value), fill: one ? c.primary : cat(e.color), fillOpacity: one ? 0.85 : 0.5, insetLeft: 0.5, insetRight: 0.5, tip }), Plot.ruleY([0], { stroke: c.border }), ...references());
  } else if (spec.kind === "box") {
    const boxes = data.filter((d) => d[e.median] != null), far = e.outlier ? data.filter((d) => d[e.outlier] != null) : [];
    const g = cat(e.group ?? ""), unnamed = boxes.every((d) => g(d) === "");
    const band: Plot.ScaleOptions = { padding: 0.5, label: null, axis: unnamed ? null : undefined };
    const value: Plot.ScaleOptions = { ...axis(o.ylabel, "value", o.ylog, o.ydomain), grid: true };
    const stats = { max: f(e.high), q3: f(e.q3), median: f(e.median), q1: f(e.q1), min: f(e.low), ...channels };
    if (o.horizontal) {
      marginLeft = Math.min(200, 16 + 6.4 * longest(boxes.map(g)));
      marks.push(Plot.ruleY(boxes, { y: g, x1: f(e.low), x2: f(e.high), stroke: c.muted }), Plot.barX(boxes, { y: g, x1: f(e.q1), x2: f(e.q3), fill: c.primary, fillOpacity: 0.22, stroke: c.primary }),
        Plot.tickX(boxes, { y: g, x: f(e.median), stroke: c.primary, strokeWidth: 2.2 }), Plot.dot(far, { y: g, x: f(e.outlier), r: 1.8, fill: c.muted, fillOpacity: 0.6 }),
        Plot.tip(boxes, Plot.pointerY({ y: g, x: f(e.median), channels: stats, ...tip })));
      x = value; y = band;
    } else {
      marks.push(Plot.ruleX(boxes, { x: g, y1: f(e.low), y2: f(e.high), stroke: c.muted }), Plot.barY(boxes, { x: g, y1: f(e.q1), y2: f(e.q3), fill: c.primary, fillOpacity: 0.22, stroke: c.primary }),
        Plot.tickY(boxes, { x: g, y: f(e.median), stroke: c.primary, strokeWidth: 2.2 }), Plot.dot(far, { x: g, y: f(e.outlier), r: 1.8, fill: c.muted, fillOpacity: 0.6 }),
        Plot.tip(boxes, Plot.pointerX({ x: g, y: f(e.median), channels: stats, ...tip })));
      x = band; y = value;
    }
  } else if (spec.kind === "violin") {
    const unnamed = data.every((d) => !d[e.group]);
    marks.push(Plot.areaX(data, { fx: cat(e.group), y: f(e.y), x1: (d: Row) => -(d[e.density] as number), x2: f(e.density), fill: c.primary, fillOpacity: 0.22, stroke: c.primary, strokeWidth: 1.2, curve: "basis" }));
    x = { axis: null };
    y = { ...axis(o.ylabel, "value", o.ylog, o.ydomain), grid: true };
    fx = { label: null, padding: 0.12, axis: unnamed ? null : undefined };
  } else if (spec.kind === "heatmap") {
    const xs = o.xorder ?? [...new Set(data.map(cat(e.x)))], ys = o.yorder ?? [...new Set(data.map(cat(e.y)))];
    const [lo, hi] = extent(data.map(f(e.value))), span = o.diverging ? Math.max(Math.abs(lo), Math.abs(hi)) || 1 : hi - Math.min(0, lo) || 1;
    const strength = (v: number) => (o.diverging ? Math.abs(v) / span : (v - Math.min(0, lo)) / span);
    const show = (v: number) => (o.percent ? `${(v * 100).toFixed(v > 0 && v < 0.1 ? 1 : 0)}%` : count(v));
    const tilt = longest(xs) * xs.length * 6.2 > width - 90;
    marginLeft = Math.min(180, 22 + 6.4 * longest(ys));
    marginBottom = tilt ? Math.min(110, 26 + 4.6 * longest(xs)) : 38;
    color = o.diverging ? { type: "diverging", pivot: 0, symmetric: true, interpolate: c.diverging, legend: true, label: e.value }
      : { type: "linear", domain: [Math.min(0, lo), hi], interpolate: c.sequential, legend: true, label: e.value, tickFormat: o.percent ? "%" : undefined };
    marks.push(Plot.cell(data, { x: cat(e.x), y: cat(e.y), fill: f(e.value), stroke: c.border, strokeOpacity: 0.7, inset: 0.75, rx: 3, channels, tip }));
    if (o.annotate ?? data.length <= 400) marks.push(Plot.text(data, { x: cat(e.x), y: cat(e.y), text: (d: Row) => (isNum(d[e.value]) ? show(d[e.value] as number) : ""), fill: (d: Row) => (strength((d[e.value] as number) ?? 0) > 0.55 ? c.onPrimary : c.fg), fontSize: 11 }));
    x = { domain: xs, label: o.xlabel === "" ? null : o.xlabel ?? e.x, padding: 0, tickRotate: tilt ? -35 : 0 };
    y = { domain: ys, label: o.ylabel === "" ? null : o.ylabel ?? e.y, padding: 0 };
  }
  return Plot.plot({
    width: o.square ? Math.min(width, height + 40) : width, height, marginTop: 26, marginRight: 14, marginBottom, marginLeft,
    style: { background: "transparent", fontFamily: "inherit", fontSize: "11px", overflow: "visible" },
    x, y, fx, fy, color, r: e.size ? { range: [1.5, 8] } : undefined, marks,
  });
}

/** A histogram logged at many steps, as one picture: step across, value up, colour for how many fall in each bin. */
function buildHistory(history: (ChartSpec & { step: number })[], width: number, height: number): Element {
  const c = palette();
  const bins = history.flatMap((h) => rowsOf(h).map((d) => ({ step: h.step, low: d[h.encoding.low] as number, high: d[h.encoding.high] as number, count: d[h.encoding.value] as number })));
  const steps = history.map((h) => h.step);
  return Plot.plot({
    width, height, marginTop: 26, marginRight: 14, marginBottom: 38, marginLeft: 52,
    style: { background: "transparent", fontFamily: "inherit", fontSize: "11px", overflow: "visible" },
    x: { domain: steps, label: "step", padding: 0, ticks: steps.filter((_, i) => i % Math.ceil(steps.length / 10) === 0) },
    y: { label: history[0]?.options.xlabel as string ?? "value", grid: true },
    color: { type: "sqrt", interpolate: c.sequential, legend: true, label: "count" },
    marks: [Plot.rect(bins, { x: "step", y1: "low", y2: "high", fill: "count", tip: { fill: c.card, stroke: c.border, fontSize: 11.5 } })],
  });
}

function Pie({ spec, height }: { spec: ChartSpec; height: number }) {
  const [hover, setHover] = React.useState<number | null>(null);
  const all = rowsOf(spec).map((d) => ({ label: String(d[spec.encoding.label] ?? ""), value: Number(d[spec.encoding.value]) || 0 })).filter((d) => d.value > 0).sort((a, b) => b.value - a.value);
  const slices = all.length > 10 ? [...all.slice(0, 9), { label: `${all.length - 9} others`, value: all.slice(9).reduce((s, d) => s + d.value, 0) }] : all;
  const total = slices.reduce((s, d) => s + d.value, 0);
  if (!total) return <p className="p-6 text-center text-[12.5px] text-muted-foreground">Nothing to show: every value is zero.</p>;
  const R = 100, r = 62, at = (radius: number, a: number) => `${(110 + radius * Math.sin(a)).toFixed(2)} ${(110 - radius * Math.cos(a)).toFixed(2)}`;
  let angle = 0;
  const arcs = slices.map((s) => { const a0 = angle, a1 = (angle += Math.min((s.value / total) * 2 * Math.PI, 2 * Math.PI - 1e-4)), big = a1 - a0 > Math.PI ? 1 : 0; return `M${at(R, a0)}A${R} ${R} 0 ${big} 1 ${at(R, a1)}L${at(r, a1)}A${r} ${r} 0 ${big} 0 ${at(r, a0)}Z`; });
  const shown = hover == null ? null : slices[hover];
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3" style={{ minHeight: height }}>
      <svg viewBox="0 0 220 220" style={{ height: Math.min(height, 260), width: Math.min(height, 260) }} role="img" aria-label={spec.title || "Pie chart"}>
        {arcs.map((d, i) => <path key={i} d={d} fill={PALETTE[i % PALETTE.length]} opacity={hover == null || hover === i ? 1 : 0.35} stroke="hsl(var(--card))" strokeWidth="1.5" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />)}
        <text x="110" y="106" textAnchor="middle" className="fill-foreground font-mono text-[20px] font-semibold">{shown ? `${((shown.value / total) * 100).toFixed(1)}%` : count(total)}</text>
        <text x="110" y="126" textAnchor="middle" className="fill-muted-foreground text-[11px]">{shown ? shown.label.slice(0, 22) : "total"}</text>
      </svg>
      <ul className="min-w-[150px] space-y-1 text-[12px]">
        {slices.map((s, i) => (
          <li key={s.label} className="flex items-center gap-2" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="min-w-0 flex-1 truncate">{s.label}</span>
            <span className="font-mono text-muted-foreground">{count(s.value)} · {((s.value / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Figure({ spec, history, height }: { spec: ChartSpec; history?: (ChartSpec & { step: number })[]; height: number }) {
  const { theme } = useHub();
  const ref = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    const el = ref.current!;
    const ro = new ResizeObserver(() => setWidth(Math.round(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  React.useEffect(() => {
    if (!width) return;
    try {
      ref.current!.replaceChildren(history ? buildHistory(history, width, height) : build(spec, width, height));
      setError("");
    } catch (err) {
      ref.current!.replaceChildren();
      setError((err as Error).message);
    }
  }, [spec, history, width, height, theme]);
  return (
    <>
      <div ref={ref} className="plot-host flex justify-center text-muted-foreground" style={{ minHeight: error ? 0 : height }} />
      {error && <p className="p-6 text-center text-[12.5px] text-muted-foreground">This chart could not be drawn: {error}</p>}
    </>
  );
}

export default function PlotView({ spec, history, height = 260 }: { spec: ChartSpec; history?: (ChartSpec & { step: number })[]; height?: number }) {
  return spec.kind === "pie" ? <Pie spec={spec} height={height} /> : <Figure spec={spec} history={history} height={height} />;
}
