// A run's logged charts and tables (run.log_chart, log_table, log_histogram), grouped by the prefix of their name.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Maximize2 } from "lucide-react";
import * as React from "react";
import { Segmented, Slider } from "@/components/ui/controls";
import { Pager, Table, Td, Th } from "@/components/ui/data";
import { Dialog } from "@/components/ui/overlays";
import { Button, Card, Empty, Input, Skeleton, Tag } from "@/components/ui/primitives";
import { get, type ChartData, type ChartInfo, type ChartSpec, type Run } from "@/lib/api";
import { cn, fmt, pref, setPref } from "@/lib/utils";

const PlotView = React.lazy(() => import("@/components/PlotView"));
const chartUrl = (slug: string) => `/api/runs/${encodeURIComponent(slug)}/chart`;

export function Plots({ run }: { run: Run }) {
  const [q, setQ] = React.useState("");
  const [cols, setCols] = React.useState<2 | 3>(() => pref("plots.cols", 2));
  const [closed, setClosed] = React.useState<Record<string, boolean>>({});
  const index = useQuery({ queryKey: ["charts", run.slug], queryFn: () => get<ChartInfo[]>(`/api/runs/${encodeURIComponent(run.slug)}/charts`), refetchInterval: run.status === "running" ? 15000 : false });
  if (!index.data) return <p className="text-[13px] text-muted-foreground">Loading…</p>;
  if (!index.data.length) return (
    <Empty title="No plots logged">
      Build a chart with <code>research_hub.plots</code> and log it: <code>run.log_chart("eval/roc", plots.roc_curve(y_true, y_score))</code>.
      Histograms, confusion matrices, scatter, bar, box, pie charts and tables work the same way, from NumPy arrays, pandas DataFrames or tensors.
    </Empty>
  );
  const groups: Record<string, ChartInfo[]> = {};
  index.data.filter((c) => !q || `${c.name} ${c.title}`.toLowerCase().includes(q.toLowerCase())).forEach((c) => { (groups[c.name.includes("/") ? c.name.slice(0, c.name.lastIndexOf("/") + 1) : "other"] ||= []).push(c); });
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 text-[12.5px]">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`filter ${index.data.length} plots`} className="h-8 w-52" aria-label="Filter plots" />
        <div className="ml-auto flex items-center gap-2 text-muted-foreground">columns <Segmented size="sm" value={String(cols) as "2" | "3"} onChange={(v) => { setCols(+v as 2 | 3); setPref("plots.cols", +v); }} options={[{ value: "2", label: "2" }, { value: "3", label: "3" }]} /></div>
      </Card>
      {Object.keys(groups).sort().map((g) => (
        <section key={g} className="space-y-3">
          <button className="flex w-full items-center gap-2 rounded-md border bg-card px-3 py-2 text-left hover:bg-muted/50" onClick={() => setClosed({ ...closed, [g]: !closed[g] })}>
            <ChevronRight className={cn("h-4 w-4 text-muted-foreground transition-transform", !closed[g] && "rotate-90")} /><span className="font-mono text-[12.5px] font-semibold">{g}</span><span className="text-[12px] text-muted-foreground">{groups[g].length} plot{groups[g].length === 1 ? "" : "s"}</span>
          </button>
          {!closed[g] && <div className={cn("grid gap-3", cols === 2 ? "lg:grid-cols-2" : "md:grid-cols-2 xl:grid-cols-3")}>{groups[g].map((c) => <ChartCard key={c.name} slug={run.slug} info={c} className={c.kind === "table" ? "col-span-full" : undefined} />)}</div>}
        </section>
      ))}
    </div>
  );
}

/** One chart of one run, with a step slider when it was logged more than once. ``label`` replaces the title (compare view). */
export function ChartCard({ slug, info, label, className }: { slug: string; info: Pick<ChartInfo, "name" | "kind" | "title">; label?: React.ReactNode; className?: string }) {
  const [step, setStep] = React.useState<number | null>(null);
  const [overTime, setOverTime] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const chart = useQuery({ queryKey: ["chart", slug, info.name, step, overTime], queryFn: () => get<ChartData>(chartUrl(slug), { name: info.name, step, history: overTime ? 1 : undefined }), placeholderData: keepPreviousData });
  const d = chart.data, steps = d?.steps ?? [];
  const at = d?.step != null ? steps.indexOf(d.step) : -1;
  const movable = d?.kind === "histogram" && !d.encoding.color && steps.length > 1;
  const sampled = d?.options.sampled_from as number | undefined;
  const body = (height: number, pageSize: number) => !d ? (chart.error ? <p className="p-6 text-center text-[12.5px] text-muted-foreground">{(chart.error as Error).message}</p> : <Skeleton className="m-2" style={{ height: height - 16 }} />)
    : d.kind === "table" ? <DataTable spec={d} size={pageSize} />
    : <React.Suspense fallback={<div style={{ height }} />}><PlotView spec={d} history={overTime ? d.history : undefined} height={height} /></React.Suspense>;
  const stepper = steps.length > 1 && (
    <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2 text-[12px] text-muted-foreground">
      {movable && <Segmented size="sm" value={overTime ? "all" : "one"} onChange={(v) => setOverTime(v === "all")} options={[{ value: "one", label: "one step" }, { value: "all", label: "over time" }]} />}
      {!overTime && <>
        <Button size="icon" variant="ghost" className="h-6 w-6" disabled={at <= 0} onClick={() => setStep(steps[at - 1])} aria-label="Previous step"><ChevronLeft className="h-3.5 w-3.5" /></Button>
        <Slider value={Math.max(0, at)} onChange={(i) => setStep(steps[i])} max={steps.length - 1} className="min-w-[80px] flex-1" label="Step" />
        <Button size="icon" variant="ghost" className="h-6 w-6" disabled={at >= steps.length - 1} onClick={() => setStep(steps[at + 1])} aria-label="Next step"><ChevronRight className="h-3.5 w-3.5" /></Button>
        <span className="font-mono text-foreground">step {d?.step?.toLocaleString()}</span>
      </>}
      <span className={overTime ? "ml-auto" : ""}>{steps.length} steps</span>
    </div>
  );
  const title = d?.title || info.title || info.name.slice(info.name.lastIndexOf("/") + 1).replace(/[_-]/g, " ");
  return (
    <figure className={cn("card flex min-w-0 flex-col", className)}>
      <figcaption className="flex items-start justify-between gap-2 px-3.5 pb-1 pt-3">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold tracking-tight">{label ?? title}</div>
          <div className="truncate font-mono text-[11px] text-muted-foreground">{label ? title : info.name}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {sampled && <Tag>{d!.rows.toLocaleString()} of {sampled.toLocaleString()} points</Tag>}
          <button className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground focus-ring" onClick={() => setOpen(true)} aria-label={`Enlarge ${info.name}`}><Maximize2 className="h-3.5 w-3.5" /></button>
        </div>
      </figcaption>
      <div className="min-w-0 flex-1 px-2 pb-2">{body(260, 8)}</div>
      {stepper}
      <Dialog open={open} onOpenChange={setOpen} wide title={title} description={<span className="font-mono">{slug} · {info.name}{d?.step != null ? ` · step ${d.step.toLocaleString()}` : ""}</span>}>
        {open && body(Math.min(560, window.innerHeight - 260), 25)}
        {stepper}
        <div className="mt-3 flex justify-end"><a href={`${chartUrl(slug)}?name=${encodeURIComponent(info.name)}${d?.step != null ? `&step=${d.step}` : ""}`} download={`${slug}-${info.name.replace(/\//g, "-")}.json`}><Button size="sm"><Download className="h-3.5 w-3.5" /> Data (JSON)</Button></a></div>
      </Dialog>
    </figure>
  );
}

function DataTable({ spec, size }: { spec: ChartSpec; size: number }) {
  const [sort, setSort] = React.useState<{ col: string; desc: boolean } | null>(null);
  const [page, setPage] = React.useState(0);
  const cols = spec.data.columns, names = Object.keys(cols);
  const order = React.useMemo(() => {
    const idx = Array.from({ length: spec.rows }, (_, i) => i);
    if (!sort) return idx;
    const v = cols[sort.col], dir = sort.desc ? -1 : 1;
    return idx.sort((a, b) => (v[a] == null ? 1 : v[b] == null ? -1 : typeof v[a] === "number" && typeof v[b] === "number" ? ((v[a] as number) - (v[b] as number)) * dir : String(v[a]).localeCompare(String(v[b])) * dir));
  }, [cols, sort, spec.rows]);
  const numeric = (c: string) => cols[c].every((v) => v == null || typeof v === "number");
  const cycle = (c: string) => { setPage(0); setSort(sort?.col !== c ? { col: c, desc: true } : sort.desc ? { col: c, desc: false } : null); };
  return (
    <div className="overflow-hidden rounded-md border">
      <Table dense>
        <thead><tr>{names.map((c) => <Th key={c} num={numeric(c)} sort={sort?.col === c ? (sort.desc ? "desc" : "asc") : null} onSort={() => cycle(c)}>{c}</Th>)}</tr></thead>
        <tbody>{order.slice(page * size, page * size + size).map((i) => <tr key={i} className="hover:bg-muted/40">{names.map((c) => { const v = cols[c][i]; return <Td key={c} num={numeric(c)} className="max-w-[360px] truncate">{v == null ? <span className="text-muted-foreground">—</span> : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : fmt(v, 4)) : String(v)}</Td>; })}</tr>)}</tbody>
      </Table>
      <Pager page={page} total={spec.rows} size={size} onPage={setPage} className="border-t" />
    </div>
  );
}
