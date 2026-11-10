// Line chart on uPlot: several series over step (or epoch), optional smoothing and log y, cursor synced across charts.
import * as React from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Series } from "@/lib/api";
import { fmt } from "@/lib/utils";

export interface ChartSeries { name: string; data: Series; color: string; dashed?: boolean }

function smooth(v: Series, a: number): Series {
  if (!a || v.length < 3) return v;
  let s = v[0][1];
  return v.map(([x, y], i) => { s = i ? a * s + (1 - a) * y : y; return [x, s]; });
}

export function Chart({ title, series, smoothing = 0, logy = false, syncKey = "hub", xLabel = "step", height = 150, headerRight }: {
  title: string; series: ChartSeries[]; smoothing?: number; logy?: boolean; syncKey?: string; xLabel?: string; height?: number; headerRight?: React.ReactNode;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const plot = React.useRef<uPlot | null>(null);
  const [hover, setHover] = React.useState<{ x: number; vals: (number | null)[] } | null>(null);
  const prepared = React.useMemo(() => series.map((s) => ({ ...s, data: smooth(s.data.filter((d) => !logy || d[1] > 0), smoothing) })).filter((s) => s.data.length), [series, smoothing, logy]);

  React.useEffect(() => {
    const el = ref.current;
    if (!el || !prepared.length) return;
    const xs = Array.from(new Set(prepared.flatMap((s) => s.data.map((d) => d[0])))).sort((a, b) => a - b);
    const idx = new Map(xs.map((x, i) => [x, i]));
    const data: (number | null)[][] = [xs, ...prepared.map((s) => { const col = new Array(xs.length).fill(null); s.data.forEach(([x, y]) => { col[idx.get(x)!] = y; }); return col; })];
    const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const muted = `hsl(${css("--muted-foreground")})`, grid = `hsl(${css("--border")})`;
    const opts: uPlot.Options = {
      width: el.clientWidth, height, cursor: { sync: { key: syncKey }, points: { size: 7 }, drag: { x: false, y: false } },
      legend: { show: false }, padding: [6, 8, 0, 0],
      scales: { x: { time: false }, y: { distr: logy ? 3 : 1 } },
      axes: [
        { stroke: muted, grid: { show: false }, ticks: { stroke: grid }, font: "10px JetBrains Mono", size: 22, values: (_u, vals) => vals.map((v) => (v >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : String(v))) },
        { stroke: muted, grid: { stroke: grid, width: 1 }, ticks: { show: false }, font: "10px JetBrains Mono", size: 58, values: (_u, vals) => { const step = vals.length > 1 ? Math.abs(vals[1] - vals[0]) : Math.abs(vals[0]) || 1; const dp = Math.max(0, Math.min(6, Math.ceil(-Math.log10(step || 1)))); return vals.map((v) => (Math.abs(v) >= 1000 ? fmt(v) : v.toFixed(dp))); } },
      ],
      series: [{}, ...prepared.map((s) => ({ stroke: s.color, width: s.dashed ? 1.2 : 1.8, dash: s.dashed ? [4, 3] : undefined, spanGaps: true, points: { show: false } }))],
      hooks: { setCursor: [(u) => { const i = u.cursor.idx; if (i == null) { setHover(null); return; } setHover({ x: u.data[0][i] as number, vals: prepared.map((_s, k) => (u.data[k + 1][i] as number | null)) }); }] },
    };
    plot.current = new uPlot(opts, data as uPlot.AlignedData, el);
    const ro = new ResizeObserver(() => plot.current?.setSize({ width: el.clientWidth, height }));
    ro.observe(el);
    return () => { ro.disconnect(); plot.current?.destroy(); plot.current = null; };
  }, [prepared, logy, syncKey, height]);

  if (!prepared.length) return null;
  const last = prepared[0].data[prepared[0].data.length - 1][1];
  return (
    <figure className="card min-w-0 px-3 pb-2 pt-2.5">
      <figcaption className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[12px] font-medium" title={title}>{title}</span>
        <span className="flex shrink-0 items-center gap-2 font-mono text-[11.5px] text-muted-foreground">
          {hover ? <span>{xLabel} {hover.x.toLocaleString()} · {hover.vals.map((v, i) => <span key={i} style={{ color: prepared[i].color }}>{fmt(v)}{i < hover.vals.length - 1 ? " " : ""}</span>)}</span> : <span>{fmt(last)}</span>}
          {headerRight}
        </span>
      </figcaption>
      <div ref={ref} className="mt-1" />
      {prepared.length > 1 && (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
          {prepared.map((s) => <span key={s.name} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.name}</span>)}
        </div>
      )}
    </figure>
  );
}

export function Sparkline({ data, color = "hsl(var(--primary))", height = 36 }: { data: Series; color?: string; height?: number }) {
  if (data.length < 2) return <div style={{ height }} />;
  const xs = data.map((d) => d[0]), ys = data.map((d) => d[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1, lo = Math.min(...ys), hi = Math.max(...ys);
  const pts = data.map((d) => `${(300 * (d[0] - x0) / (x1 - x0 || 1)).toFixed(1)},${(height - 4 - (height - 8) * ((d[1] - lo) / (hi - lo || 1))).toFixed(1)}`).join(" ");
  return <svg viewBox={`0 0 300 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} aria-hidden="true"><polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg>;
}
