// Eval samples: every logged sample, filterable; masks, heatmaps and boxes are drawn in the browser over one image.
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, X } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { Checkbox, Chip, FacetFilter, Select, Slider } from "@/components/ui/controls";
import { Pager } from "@/components/ui/data";
import { Dialog, Popover, toast } from "@/components/ui/overlays";
import { Badge, Button, Card, Empty, Input, OUTCOME_LABEL, outcomeTone } from "@/components/ui/primitives";
import { get, type Facets, type Run, type SampleDetail, type SampleRow, type Side } from "@/lib/api";
import { useHub } from "@/lib/state";
import { PALETTE, cn, fmt, pref, setPref } from "@/lib/utils";

const PAGE = 24;
const list = (v?: string) => (v ? v.split(",") : []);
const OUTCOMES = ["missed", "false_alarm", "wrong_class", "mismatch", "correct", "unscored"];
const MASK_COLORS = [[255, 64, 24], [26, 204, 128], [60, 140, 255], [255, 200, 0], [200, 80, 255], [0, 200, 220], [255, 120, 180], [150, 220, 40]];
type Kinds = Record<string, "mask" | "heatmap">;
/** minScore hides predicted boxes below it; classScore overrides it for one class. */
type View = { show: Record<string, boolean>; op: number; th: number; minScore: number; classScore: Record<string, number> };
const defaultView: View = { show: {}, op: 0.55, th: 0.2, minScore: 0.3, classScore: {} };
// boxes are switched on and off like layers; a layer name cannot contain a colon, so these never clash with one
const TRUE_BOXES = ":true-boxes", PRED_BOXES = ":pred-boxes";
/** Overlay layers of a sample in a stable order: every layer the run logged, whatever it is called. */
const layerKeys = (layers: Record<string, string>) => Object.keys(layers).filter((k) => k !== "image" && k !== "audio").sort();
/** A mask keeps one colour per name across the whole eval set; a heatmap uses the inferno ramp. */
const layerColor = (k: string, kinds: Kinds) => (kinds[k] === "heatmap" ? null : MASK_COLORS[Math.max(0, Object.keys(kinds).filter((x) => kinds[x] === "mask").sort().indexOf(k)) % MASK_COLORS.length]);
const layerName = (k: string) => (k.endsWith("_gt") ? `${k.slice(0, -3)} (truth)` : k).replace(/_/g, " ");
/** Shown unless switched off. Heatmaps start hidden when the run also logged masks, so the image stays readable. */
const visible = (k: string, view: View, kinds: Kinds) => view.show[k] ?? (kinds[k] !== "heatmap" || !Object.values(kinds).includes("mask"));
const swatch = (c: number[] | null) => (c ? `rgb(${c.join(",")})` : "linear-gradient(90deg,#57106e,#bc3754,#f98e09,#fcffa4)");
const labelColor = (l: string) => { let h = 0; for (const c of l) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length]; };
const stepLabel = (s: { step: number; epoch: number | null }) => `${s.epoch != null && s.epoch >= 0 ? `epoch ${s.epoch} · ` : ""}step ${s.step.toLocaleString()}`;

// -------------------------------------------------------------- painting
const cache = new Map<string, Promise<HTMLImageElement>>();
function blob(sha: string) {
  if (!cache.has(sha)) { cache.set(sha, new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = `/blobs/${sha}`; })); if (cache.size > 800) cache.delete(cache.keys().next().value!); }
  return cache.get(sha)!;
}
const inferno = (t: number) => { const s = [[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]]; const x = Math.min(0.999, Math.max(0, t)) * 4, i = Math.floor(x), f = x - i; return s[i].map((v, j) => v + (s[i + 1][j] - v) * f); };

async function paint(ctx: CanvasRenderingContext2D, x0: number, W: number, H: number, layers: Record<string, string>, keys: string[], kinds: Kinds, truth: Side, pred: Side, view: View, sides = { gt: true, pred: true }) {
  const css = (n: string) => `hsl(${getComputedStyle(document.documentElement).getPropertyValue(n).trim()})`;
  ctx.fillStyle = css("--muted"); ctx.fillRect(x0, 0, W, H);
  let base: HTMLImageElement | null = null;
  if (layers.image) { try { base = await blob(layers.image); ctx.drawImage(base, x0, 0, W, H); } catch { /* missing */ } }
  if (!base && !keys.length && !truth.boxes && !pred.boxes) { ctx.fillStyle = css("--muted-foreground"); ctx.font = "12px Inter, sans-serif"; ctx.textAlign = "center"; ctx.fillText("no image logged", x0 + W / 2, H / 2); return; }
  const names = keys.filter((k) => visible(k, view, kinds));
  if (names.length) {
    const frame = ctx.getImageData(x0, 0, W, H), d = frame.data;
    const tmp = document.createElement("canvas"); tmp.width = W; tmp.height = H; const tx = tmp.getContext("2d", { willReadFrequently: true })!;
    for (const k of names) {
      let im: HTMLImageElement; try { im = await blob(layers[k]); } catch { continue; }
      const gt = k.endsWith("_gt"), color = layerColor(k, kinds);
      tx.clearRect(0, 0, W, H); tx.imageSmoothingEnabled = !gt; tx.drawImage(im, 0, 0, W, H);
      const p = tx.getImageData(0, 0, W, H).data;
      for (let j = 0; j < d.length; j += 4) { const val = p[j] / 255; if (val <= (gt ? 0.5 : view.th)) continue; const col = color ?? inferno(val); const a = gt ? view.op : view.op * Math.min(1, color ? val : val * 1.4);
        d[j] = d[j] * (1 - a) + col[0] * a; d[j + 1] = d[j + 1] * (1 - a) + col[1] * a; d[j + 2] = d[j + 2] * (1 - a) + col[2] * a; }
    }
    ctx.putImageData(frame, x0, 0);
  }
  const bw = base?.naturalWidth ?? 1, bh = base?.naturalHeight ?? 1;
  const norm = (boxes: (number | string)[][]) => boxes.map((b) => { const n = b.slice(0, 4).map(Number); return n.every((v) => v <= 1) ? [...n, ...b.slice(4)] : [n[0] / bw, n[1] / bh, n[2] / bw, n[3] / bh, ...b.slice(4)]; });
  const draw = (boxes: (number | string)[][], dashed: boolean) => { ctx.lineWidth = 2; for (const b of norm(boxes)) { const [bx, by, w, h] = b as number[]; const label = b[4] as string | undefined, score = b[5] as number | undefined;
    if (!dashed && score != null && score < (view.classScore[label ?? ""] ?? view.minScore)) continue;
    ctx.strokeStyle = dashed ? "#ffd400" : labelColor(label ?? ""); ctx.setLineDash(dashed ? [6, 4] : []); ctx.strokeRect(x0 + bx * W, by * H, w * W, h * H);
    if (label != null) { ctx.setLineDash([]); ctx.font = "11px Inter, sans-serif"; const t = `${label}${score != null ? " " + score.toFixed(2) : ""}`; const tw = ctx.measureText(t).width + 6; ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x0 + bx * W, Math.max(0, by * H - 14), tw, 14); ctx.fillStyle = dashed ? "#000" : "#fff"; ctx.textAlign = "left"; ctx.fillText(t, x0 + bx * W + 3, Math.max(11, by * H - 3)); } } ctx.setLineDash([]); };
  if (sides.gt && truth.boxes && view.show[TRUE_BOXES] !== false) draw(truth.boxes, true);
  if (sides.pred && pred.boxes && view.show[PRED_BOXES] !== false) draw(pred.boxes, false);
}

function Thumb({ row, view, kinds }: { row: SampleRow; view: View; kinds: Kinds }) {
  const ref = React.useRef<HTMLCanvasElement>(null);
  const visual = !!(row.layers.image || layerKeys(row.layers).length || row.truth.boxes || row.pred.boxes);
  React.useEffect(() => { const cv = ref.current; if (cv && visual) paint(cv.getContext("2d", { willReadFrequently: true })!, 0, cv.width, cv.height, row.layers, layerKeys(row.layers), kinds, row.truth, row.pred, view); }, [row, view, visual, kinds]);
  if (visual) return <canvas ref={ref} width={224} height={224} className="aspect-square w-full bg-muted" />;
  if (row.truth.text != null || row.pred.text != null) {
    const both = row.truth.text != null && row.pred.text != null;
    return <div className="aspect-square w-full space-y-1 overflow-hidden bg-muted p-2.5 text-[11.5px] leading-snug">{both && <div className="label">true</div>}<div className={both ? "line-clamp-3" : "line-clamp-[9] text-[12.5px]"}>{row.truth.text ?? row.pred.text}</div>{both && <><div className="label">pred</div><div className="line-clamp-3">{row.pred.text}</div></>}</div>;
  }
  return <div className="grid aspect-square w-full place-content-center bg-muted text-center"><div className="font-mono text-[26px] font-medium">{row.pred.value != null ? fmt(row.pred.value) : "—"}</div><div className="text-[11.5px] text-muted-foreground">true {fmt(row.truth.value)}</div></div>;
}

/** Box switches and the score filter: one minimum for every class, and a separate one for any class that needs it. */
function BoxControls({ view, updateView, classes }: { view: View; updateView: (v: Partial<View>) => void; classes: string[] }) {
  const setClass = (c: string, v: number | null) => { const next = { ...view.classScore }; if (v == null) delete next[c]; else next[c] = v; updateView({ classScore: next }); };
  const toggle = (k: string, label: React.ReactNode) => <Checkbox checked={view.show[k] !== false} onChange={(v) => updateView({ show: { ...view.show, [k]: v } })} label={label} />;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {toggle(TRUE_BOXES, <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border-2 border-dashed" style={{ borderColor: "#d4a900" }} />true boxes</span>)}
        {toggle(PRED_BOXES, <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border-2 border-primary" />predicted boxes</span>)}
      </div>
      <div className="flex items-center gap-2 text-[12px]"><span className="w-32 shrink-0 text-muted-foreground">min score, all classes</span><Slider value={view.minScore * 100} onChange={(v) => updateView({ minScore: v / 100 })} label="Minimum box score" /><span className="w-8 shrink-0 text-right font-mono">{view.minScore.toFixed(2)}</span><span className="w-4 shrink-0" /></div>
      {classes.length > 0 && (
        <div className="max-h-60 space-y-1 overflow-y-auto border-t pt-2">
          <div className="label">min score per class</div>
          {classes.map((c) => { const own = view.classScore[c]; return (
            <div key={c} className="flex items-center gap-2 text-[12px]">
              <span className="flex w-32 shrink-0 items-center gap-1.5" title={c}><span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: labelColor(c) }} /><span className="truncate">{c}</span></span>
              <Slider value={(own ?? view.minScore) * 100} onChange={(v) => setClass(c, v / 100)} label={`Minimum score for ${c}`} />
              <span className={cn("w-8 shrink-0 text-right font-mono", own == null && "text-muted-foreground")}>{(own ?? view.minScore).toFixed(2)}</span>
              <button className="w-4 shrink-0 text-muted-foreground hover:text-foreground disabled:invisible" disabled={own == null} onClick={() => setClass(c, null)} title="Follow the minimum for all classes again" aria-label={`Follow the minimum for all classes again for ${c}`}><X className="h-3 w-3" /></button>
            </div>
          ); })}
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- panel
export function Samples({ run }: { run: Run }) {
  const hub = useHub();
  const sets = run.eval_sets;
  const [set, setSet] = React.useState(() => sets.reduce((a, b) => (Math.max(...b.steps.map((x) => x.samples)) > Math.max(...a.steps.map((x) => x.samples)) ? b : a), sets[0])?.set ?? "");
  const steps = sets.find((s) => s.set === set)?.steps ?? [];
  const [step, setStep] = React.useState<number | null>(null);
  const curStep = step != null && steps.some((s) => s.step === step) ? step : steps[steps.length - 1]?.step;
  const [f, setF] = React.useState<Record<string, string>>({});
  const [sort, setSort] = React.useState("error");
  const [page, setPage] = React.useState(0);
  const [view, setView] = React.useState<View>(() => ({ ...defaultView, ...pref("samples.view", {}) }));
  const updateView = (v: Partial<View>) => setView((old) => { const next = { ...old, ...v }; setPref("samples.view", next); return next; });
  const [open, setOpen] = React.useState<number | null>(null);
  const facets = useQuery({ queryKey: ["facets", run.slug, set, curStep], enabled: !!set && curStep != null, queryFn: () => get<Facets>(`/api/runs/${encodeURIComponent(run.slug)}/eval/facets`, { set, step: curStep }) });
  const rows = useQuery({ queryKey: ["samples", run.slug, set, curStep, f, sort, page], enabled: !!set && curStep != null, queryFn: () => get<{ total: number; rows: SampleRow[] }>(`/api/runs/${encodeURIComponent(run.slug)}/eval/samples`, { set, step: curStep, sort, limit: PAGE, offset: page * PAGE, ...f }) });
  const setFilter = (k: string, v: string) => { setF((o) => { const n = { ...o }; if (v) n[k] = v; else delete n[k]; return n; }); setPage(0); };
  if (!sets.length) return <Empty title="No eval samples logged">Log one row per sample at each checkpoint with <code>run.log_eval(rows, step=…, eval_set=…)</code>; classes, values, masks, boxes and text all work.</Empty>;
  const fc = facets.data;
  const outs = (f.outcome || "").split(",").filter(Boolean);
  const classes = fc ? [...new Set(fc.confusion.flatMap((c) => [c[0], c[1]]))].filter(Boolean) : [];
  const cell = (t: string, p: string) => fc?.confusion.find((x) => x[0] === t && x[1] === p)?.[2] ?? 0;
  const kinds = fc?.layers ?? {};
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        {sets.length > 1 ? <Select size="sm" value={set} onChange={(v) => { setSet(v); setStep(null); setF({}); setPage(0); }} options={sets.map((s) => ({ value: s.set, label: s.set }))} className="w-72" /> : <span className="px-1 font-mono text-[12.5px]">{set}</span>}
        <Select size="sm" value={String(curStep)} onChange={(v) => { setStep(+v); setPage(0); }} options={steps.map((s) => ({ value: String(s.step), label: stepLabel(s), hint: `${s.samples.toLocaleString()}${s.layered ? ` · ${s.layered} with overlays` : ""}` }))} className="w-64" />
        <Input value={f.q ?? ""} onChange={(e) => setFilter("q", e.target.value)} placeholder="sample id or any fact" className="h-8 w-52" />
        <Select size="sm" value={sort} onChange={setSort} options={[{ value: "error", label: "Worst first" }, { value: "value", label: "True value" }, { value: "value_pred", label: "Predicted value" }, { value: "score", label: "Score" }, { value: "sample", label: "Sample id" }]} className="w-40" />
        <div className="ml-auto flex items-center gap-2">
        {fc?.kinds.layers && (
          <Popover align="end" className="w-80" trigger={<Button size="sm">Layers</Button>}>
            <div className="space-y-2">
              {Object.keys(kinds).map((k) => <Checkbox key={k} checked={visible(k, view, kinds)} onChange={(v) => updateView({ show: { ...view.show, [k]: v } })} label={<span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-sm" style={{ background: swatch(layerColor(k, kinds)) }} />{layerName(k)}</span>} />)}
              <label className="block space-y-1 pt-1"><span className="label">opacity {Math.round(view.op * 100)}%</span><Slider value={view.op * 100} onChange={(v) => updateView({ op: v / 100 })} label="Opacity" /></label>
              <label className="block space-y-1"><span className="label">threshold {view.th.toFixed(2)}</span><Slider value={view.th * 100} onChange={(v) => updateView({ th: v / 100 })} max={95} label="Threshold" /></label>
            </div>
          </Popover>
        )}
        {fc?.kinds.boxes && (
          <Popover align="end" className="w-[26rem]" trigger={<Button size="sm">Boxes · min score {view.minScore.toFixed(2)}{Object.keys(view.classScore).some((c) => fc.box_classes.includes(c)) ? " +" : ""}</Button>}>
            <BoxControls view={view} updateView={updateView} classes={fc.box_classes} />
          </Popover>
        )}
        </div>
      </Card>
      {fc && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1">Filter</span>
          {Object.entries(fc.facts).map(([k, vals]) => <FacetFilter key={k} label={k.replace(/_/g, " ")} values={vals} selected={list(f["fact." + k])} onChange={(v) => setFilter("fact." + k, v.join(","))} />)}
          {fc.class_true.length > 0 && <FacetFilter label="true class" values={fc.class_true} selected={list(f.class_true)} onChange={(v) => setFilter("class_true", v.join(","))} />}
          {fc.class_pred.length > 0 && <FacetFilter label="predicted class" values={fc.class_pred} selected={list(f.class_pred)} onChange={(v) => setFilter("class_pred", v.join(","))} />}
          {fc.kinds.value && fc.value_range[0] != null && (
            <Popover className="w-64" trigger={<Chip active={!!(f.value_min || f.value_max)}>true value{f.value_min || f.value_max ? `: ${f.value_min || "…"} – ${f.value_max || "…"}` : ""}<ChevronDown className="h-3 w-3" /></Chip>}>
              <div className="grid grid-cols-2 gap-2"><label className="space-y-1"><span className="label">at least</span><Input type="number" step="any" value={f.value_min ?? ""} onChange={(e) => setFilter("value_min", e.target.value)} placeholder={fmt(fc.value_range[0])} className="h-8" /></label><label className="space-y-1"><span className="label">at most</span><Input type="number" step="any" value={f.value_max ?? ""} onChange={(e) => setFilter("value_max", e.target.value)} placeholder={fmt(fc.value_range[1])} className="h-8" /></label></div>
            </Popover>
          )}
          {fc.kinds.layers && <Chip active={f.layered === "1"} onClick={() => setFilter("layered", f.layered === "1" ? "" : "1")}>has overlays</Chip>}
          {Object.keys(f).length > 0 && <button className="ml-1 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => { setF({}); setPage(0); }}><X className="h-3 w-3" /> Clear all</button>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {fc && OUTCOMES.filter((o) => fc.outcome[o]).map((o) => <Chip key={o} active={outs.includes(o)} onClick={() => setFilter("outcome", (outs.includes(o) ? outs.filter((x) => x !== o) : [...outs, o]).join(","))}><span className={cn("h-1.5 w-1.5 rounded-full", o === "correct" ? "bg-success" : o === "unscored" ? "bg-muted-foreground" : "bg-danger")} />{OUTCOME_LABEL[o]}<b>{fc.outcome[o].toLocaleString()}</b></Chip>)}
      </div>
      {classes.length > 1 && (
        <details className="group">
          <summary className="cursor-pointer text-[12.5px] text-muted-foreground hover:text-foreground">Confusion matrix at this checkpoint · click a cell to filter</summary>
          <Card className="mt-2 inline-block overflow-x-auto p-3"><table className="font-mono text-[11.5px]"><thead><tr><th />{classes.map((c) => <th key={c} className="max-h-32 px-1.5 pb-1 text-left align-bottom font-medium text-muted-foreground [writing-mode:vertical-rl] [transform:rotate(180deg)]">{c}</th>)}</tr></thead>
            <tbody>{classes.map((t) => <tr key={t}><th className="pr-2 text-left font-medium text-muted-foreground">{t}</th>{classes.map((p) => { const n = cell(t, p); return <td key={p} className={cn("border px-1.5 py-0.5 text-right", n && "cursor-pointer hover:outline hover:outline-2 hover:outline-primary", t === p && n && "bg-success-soft")} onClick={() => n && setF({ class_true: t, class_pred: p })}>{n || ""}</td>; })}</tr>)}</tbody></table></Card>
        </details>
      )}
      <div className="text-[12.5px] text-muted-foreground">{rows.data ? `${rows.data.total.toLocaleString()} matching sample${rows.data.total === 1 ? "" : "s"}` : "Loading…"}</div>
      {rows.data && (rows.data.rows.length ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {rows.data.rows.map((x, i) => (
            <button key={x.item} onClick={() => setOpen(i)} className="card overflow-hidden text-left transition-colors hover:border-primary/60 focus-ring">
              <Thumb row={x} view={view} kinds={kinds} />
              <div className="space-y-0.5 px-2.5 py-2 text-[11.5px] leading-snug">
                <div className="truncate font-medium">{Object.values(x.facts).slice(0, 2).join(" · ") || x.sample.slice(0, 18)}</div>
                <div className="flex items-center gap-1 truncate text-muted-foreground">{x.truth.class ? <span className="truncate">{x.truth.class} → <span className={cn(x.outcome === "correct" ? "text-success" : "text-danger")}>{x.pred.class || OUTCOME_LABEL[x.outcome]}</span></span> : <Badge tone={outcomeTone(x.outcome)} dot>{x.metrics.tp != null ? `${x.metrics.tp} tp · ${x.metrics.fp} fp · ${x.metrics.fn} fn` : OUTCOME_LABEL[x.outcome]}</Badge>}</div>
                <div className="truncate font-mono text-muted-foreground">{x.truth.value != null && `${fmt(x.truth.value)}→${fmt(x.pred.value)}`}{x.error != null ? ` · err ${fmt(x.error)}` : x.pred.score != null ? ` · ${fmt(x.pred.score)}` : ""}</div>
              </div>
            </button>
          ))}
        </div>
      ) : <Empty title="No samples match these filters" />)}
      <Pager page={page} total={rows.data?.total ?? 0} size={PAGE} onPage={setPage} />
      {open != null && rows.data && <SampleDialog run={run} set={set} step={curStep!} rows={rows.data.rows} index={open} view={view} updateView={updateView} onClose={() => setOpen(null)} onIndex={setOpen} project={hub.project} />}
    </div>
  );
}

// -------------------------------------------------------------- one sample across checkpoints
function SampleDialog({ run, set, step, rows, index, view, updateView, onClose, onIndex, project }: { run: Run; set: string; step: number; rows: SampleRow[]; index: number; view: View; updateView: (v: Partial<View>) => void; onClose: () => void; onIndex: (i: number) => void; project: string }) {
  const navigate = useNavigate();
  const row = rows[index];
  const detail = useQuery({ queryKey: ["sample", run.slug, set, row.sample], queryFn: () => get<SampleDetail>(`/api/runs/${encodeURIComponent(run.slug)}/eval/sample`, { set, sample: row.sample }) });
  const [sel, setSel] = React.useState(0);
  const [sbs, setSbs] = React.useState(false);
  const cv = React.useRef<HTMLCanvasElement>(null);
  const d = detail.data;
  React.useEffect(() => { if (d) setSel(Math.max(0, d.steps.findIndex((s) => s.step === step))); }, [d, step]);
  const s = d?.steps[sel], truth = { ...(d?.truth ?? {}), ...(s?.truth ?? {}) }, pred = s?.pred ?? {};
  const layers = { ...(d?.static_layers ?? {}), ...(s?.layers ?? {}) }, keys = layerKeys(layers), kinds = d?.layer_kinds ?? {};
  const visual = !!(layers.image || keys.length || truth.boxes || pred.boxes), textual = truth.text != null || pred.text != null;
  const size = 480;
  React.useEffect(() => { const c = cv.current; if (!c || !d) return; const ctx = c.getContext("2d", { willReadFrequently: true })!;
    if (sbs) { paint(ctx, 0, size, size, layers, keys.filter((k) => k.endsWith("_gt")), kinds, truth, pred, view, { gt: true, pred: false }); paint(ctx, size, size, size, layers, keys.filter((k) => !k.endsWith("_gt")), kinds, truth, pred, view, { gt: false, pred: true }); }
    else paint(ctx, 0, size, size, layers, keys, kinds, truth, pred, view);
  });
  React.useEffect(() => { const onKey = (e: KeyboardEvent) => { if ((e.target as HTMLElement).tagName === "INPUT" || !d) return; if (e.key === "ArrowRight") setSel((x) => Math.min(d.steps.length - 1, x + 1)); if (e.key === "ArrowLeft") setSel((x) => Math.max(0, x - 1)); }; document.addEventListener("keydown", onKey); return () => document.removeEventListener("keydown", onKey); }, [d]);
  const title = Object.values(d?.facts ?? row.facts).slice(0, 2).join(" · ") || row.sample;
  const comment = () => { sessionStorage.setItem("hub.anchor", `sample: ${title} ${row.sample} @ ${s ? stepLabel(s) : ""} (${set})`.slice(0, 200)); onClose(); navigate(`/p/${encodeURIComponent(project)}/runs/${run.slug}/discussion`); };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} wide title={<span className="flex items-center gap-3">{title}<span className="truncate font-mono text-[11.5px] font-normal text-muted-foreground">{row.sample}</span></span>}>
      {!d ? <p className="text-[13px] text-muted-foreground">Loading…</p> : (
        <div className="space-y-4">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,auto)_minmax(260px,1fr)]">
            <div className="space-y-2">
              {visual && <canvas ref={cv} width={sbs ? size * 2 : size} height={size} className="max-w-full rounded-md bg-muted" style={{ width: `min(100%, ${sbs ? size * 2 : size}px)` }} />}
              {sbs && <div className="flex justify-around text-[12px] text-muted-foreground"><span>ground truth</span><span>prediction</span></div>}
              {layers.audio && <audio controls src={`/blobs/${layers.audio}`} className="w-full" />}
              {textual && (truth.text != null && pred.text != null ? <div className="grid gap-3 md:grid-cols-2"><div className="rounded-md border bg-muted/40 p-3 text-[13px]"><div className="label mb-1">true</div><Diff a={truth.text ?? ""} b={pred.text ?? ""} mode="del" /></div><div className="rounded-md border bg-muted/40 p-3 text-[13px]"><div className="label mb-1">predicted</div><Diff a={truth.text ?? ""} b={pred.text ?? ""} mode="ins" /></div></div> : <div className="max-w-xl rounded-md border bg-muted/40 p-3 text-[13.5px] leading-relaxed">{truth.text ?? pred.text}</div>)}
            </div>
            <div className="space-y-4">
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-[12.5px]">
                {Object.entries(d.facts).map(([k, v]) => <React.Fragment key={k}><dt className="label pt-0.5">{k}</dt><dd className="break-all font-mono text-[12px]">{v}</dd></React.Fragment>)}
                {truth.class && <><dt className="label pt-0.5">true class</dt><dd className="font-mono text-[12px]">{truth.class}</dd></>}
                {truth.value != null && <><dt className="label pt-0.5">true value</dt><dd className="font-mono text-[12px]">{fmt(truth.value)}</dd></>}
                {s && <>
                  <dt className="col-span-2 mt-2 text-[13px] font-semibold">At {stepLabel(s)}</dt>
                  <dt className="label pt-0.5">outcome</dt><dd><Badge tone={outcomeTone(s.outcome)} dot>{OUTCOME_LABEL[s.outcome]}</Badge></dd>
                  {pred.class && <><dt className="label pt-0.5">predicted</dt><dd className="font-mono text-[12px]">{pred.class}</dd></>}
                  {pred.value != null && <><dt className="label pt-0.5">pred. value</dt><dd className="font-mono text-[12px]">{fmt(pred.value)}</dd></>}
                  {pred.score != null && <><dt className="label pt-0.5">score</dt><dd className="font-mono text-[12px]">{fmt(pred.score)}</dd></>}
                  {s.error != null && <><dt className="label pt-0.5">error</dt><dd className="font-mono text-[12px]">{fmt(s.error)}</dd></>}
                  {Object.entries(s.metrics).slice(0, 8).map(([k, v]) => <React.Fragment key={k}><dt className="label pt-0.5">{k}</dt><dd className="font-mono text-[12px]">{typeof v === "number" ? fmt(v) : JSON.stringify(v)}</dd></React.Fragment>)}
                </>}
              </dl>
              {visual && (keys.length > 0 || truth.boxes || pred.boxes) && (
                <div className="space-y-2 rounded-md border p-3">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">{keys.map((k) => <Checkbox key={k} checked={visible(k, view, kinds)} onChange={(v) => updateView({ show: { ...view.show, [k]: v } })} label={<span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm" style={{ background: swatch(layerColor(k, kinds)) }} />{layerName(k)}</span>} />)}</div>
                  {keys.length > 0 && <><label className="flex items-center gap-3 text-[12px]"><span className="w-16 text-muted-foreground">opacity</span><Slider value={view.op * 100} onChange={(v) => updateView({ op: v / 100 })} label="Opacity" /></label><label className="flex items-center gap-3 text-[12px]"><span className="w-16 text-muted-foreground">threshold</span><Slider value={view.th * 100} onChange={(v) => updateView({ th: v / 100 })} max={95} label="Threshold" /></label></>}
                  {(truth.boxes || pred.boxes) && <BoxControls view={view} updateView={updateView} classes={[...new Set((pred.boxes ?? []).map((b) => b[4]).filter((l): l is string => typeof l === "string"))].sort()} />}
                  <Checkbox checked={sbs} onChange={setSbs} label="ground truth and prediction side by side" />
                </div>
              )}
              <div className="flex gap-2"><Button size="sm" onClick={comment}>Comment on this sample</Button><Button size="sm" variant="ghost" disabled={index === 0} onClick={() => onIndex(index - 1)}><ChevronLeft className="h-4 w-4" /> prev</Button><Button size="sm" variant="ghost" disabled={index >= rows.length - 1} onClick={() => onIndex(index + 1)}>next <ChevronRight className="h-4 w-4" /></Button></div>
            </div>
          </div>
          <div>
            <div className="text-[12.5px]"><b>Checkpoint {sel + 1} of {d.steps.length}</b> <span className="text-muted-foreground">· ← → to step · dots mark checkpoints with overlays</span></div>
            <div className="mt-2 flex gap-1">{d.steps.map((x, j) => <button key={x.step} onClick={() => setSel(j)} title={`${stepLabel(x)}: ${x.pred.class || OUTCOME_LABEL[x.outcome]}`} className={cn("relative h-3 flex-1 rounded-sm", x.outcome === "correct" ? "bg-success" : x.outcome === "unscored" ? "bg-muted" : "bg-danger", j === sel && "ring-2 ring-primary ring-offset-1 ring-offset-card", Object.keys(x.layers).length > 0 && "after:absolute after:-top-1.5 after:left-1/2 after:h-1 after:w-1 after:-translate-x-1/2 after:rounded-full after:bg-foreground")} aria-label={stepLabel(x)} />)}</div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function Diff({ a, b, mode }: { a: string; b: string; mode: "del" | "ins" }) {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/), n = A.length, m = B.length;
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: React.ReactNode[] = []; let i = 0, j = 0;
  while (i < n && j < m) { if (A[i] === B[j]) { out.push(A[i]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) { if (mode === "del") out.push(<span key={`d${i}`} className="rounded bg-danger-soft text-danger line-through">{A[i]}</span>); i++; } else { if (mode === "ins") out.push(<span key={`i${j}`} className="rounded bg-success-soft text-success">{B[j]}</span>); j++; } }
  if (mode === "del") while (i < n) out.push(<span key={`d${i}`} className="rounded bg-danger-soft text-danger line-through">{A[i++]}</span>); else while (j < m) out.push(<span key={`i${j}`} className="rounded bg-success-soft text-success">{B[j++]}</span>);
  return <span className="whitespace-pre-wrap">{out}</span>;
}
