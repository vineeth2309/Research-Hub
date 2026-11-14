// One eval set across runs: a tile per sample with every chosen run's call, and where the runs agree or split.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, Download, X } from "lucide-react";
import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Checkbox, Chip, FacetFilter, Select, Slider, Switch } from "@/components/ui/controls";
import { Pager } from "@/components/ui/data";
import { PageHeader } from "@/components/ui/form";
import { Dialog, Popover, toast } from "@/components/ui/overlays";
import { Badge, Button, Card, Empty, Input, OUTCOME_LABEL, Spinner, statusTone, verdictTone, type Tone } from "@/components/ui/primitives";
import { get, type Call, type DatasetPage, type DatasetRow, type DatasetRun, type DatasetSummary, type EvalSetInfo, type SampleDetail } from "@/lib/api";
import { useHub } from "@/lib/state";
import { cn, fmt, hashColor, pref, setPref } from "@/lib/utils";
import { defaultView, layerColor, layerKeys, layerName, paint, swatch, visible, type View } from "./Samples";

const PAGE = 48;
const list = (v?: string) => (v ? v.split(",") : []);
const PRESETS: [string, string][] = [["most_wrong", "Most runs wrong"], ["all_wrong", "Every run wrong"], ["split", "Runs split"], ["all_right", "Every run right"], ["one_wrong", "One run wrong"], ["one_right", "One run right"]];
/** Runs named <arm>-s<seed>… are seeds of one arm; any other run is its own arm. */
const armOf = (slug: string) => { const m = /^(.*?)-s(\d+)(?:-.*)?$/.exec(slug); return m ? { arm: m[1], seed: +m[2] } : { arm: slug, seed: 0 }; };
const byArm = (a: string, b: string) => { const x = armOf(a), y = armOf(b); return x.arm.localeCompare(y.arm) || x.seed - y.seed || a.localeCompare(b); };
const cellClass = (outcome: string) => (outcome === "correct" ? "bg-success" : outcome === "false_alarm" ? "bg-warning" : "bg-danger");
const pct = (v: number) => `${(v * 100).toFixed(v > 0.995 && v < 1 ? 2 : 1)}%`;

/** What the runs made of one sample, in a few words. */
function verdict(x: DatasetRow): { tone: Tone; text: string } {
  if (!x.scored) { const top = x.classes[0]; return { tone: "neutral", text: top ? `${top[0]} from ${top[1]} of ${x.runs}` : `${x.runs} runs` }; }
  if (!x.wrong) return { tone: "success", text: `all ${x.scored} right` };
  if (x.missed === x.wrong) return { tone: "danger", text: `missed ${x.wrong} of ${x.scored}` };
  if (x.false_alarm === x.wrong) return { tone: "warning", text: `false alarm ${x.wrong} of ${x.scored}` };
  return { tone: "danger", text: `wrong ${x.wrong} of ${x.scored}` };
}

/** One cell per run. With truth the colour is the outcome; without it, the predicted class. */
function Strip({ calls, slugs, grouped, scored }: { calls: Call[]; slugs: string[]; grouped: boolean; scored: boolean }) {
  return (
    <div className="flex h-3.5 gap-px">
      {calls.map((c, i) => (
        <span key={slugs[i]} title={`${slugs[i]}: ${c ? `${c[1] || OUTCOME_LABEL[c[0]] || c[0]}${c[0] !== "unscored" ? ` (${OUTCOME_LABEL[c[0]] ?? c[0]})` : ""}` : "not logged"}`}
          className={cn("min-w-0 flex-1 rounded-[2px]", !c ? "bg-muted" : scored ? cellClass(c[0]) : "", grouped && i > 0 && armOf(slugs[i]).arm !== armOf(slugs[i - 1]).arm && "ml-[3px]")}
          style={c && !scored ? { background: hashColor(c[1] || "none") } : undefined} />
      ))}
    </div>
  );
}

function RunPicker({ runs, picked, onPick, project }: { runs: DatasetRun[]; picked: string[]; onPick: (slugs: string[]) => void; project: string }) {
  const [q, setQ] = React.useState("");
  const [owner, setOwner] = React.useState("");
  const [verdictOf, setVerdictOf] = React.useState("");
  const [name, setName] = React.useState("");
  const [saved, setSaved] = React.useState<Record<string, string[]>>(() => pref(`datasets.selections.${project}`, {}));
  const store = (next: Record<string, string[]>) => { setSaved(next); setPref(`datasets.selections.${project}`, next); };
  const shown = runs.filter((r) => (!q || r.slug.includes(q.toLowerCase()) || r.title.toLowerCase().includes(q.toLowerCase())) && (!owner || r.owner === owner) && (!verdictOf || (r.verdict ?? "none") === verdictOf));
  const options = (values: string[], any: string) => [{ value: "", label: any }, ...[...new Set(values)].sort().map((v) => ({ value: v, label: v }))];
  const known = new Set(runs.map((r) => r.slug));
  return (
    <Popover className="w-[34rem]" trigger={<Button size="sm">Runs · {picked.length} of {runs.length}<ChevronDown className="h-3.5 w-3.5" /></Button>}>
      <div className="space-y-2.5">
        <div className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a run" className="h-8 flex-1" />
          <Select size="sm" value={owner} onChange={setOwner} options={options(runs.map((r) => r.owner), "Any owner")} className="w-36" />
          <Select size="sm" value={verdictOf} onChange={setVerdictOf} options={options(runs.map((r) => r.verdict ?? "none"), "Any verdict")} className="w-32" />
        </div>
        <div className="flex items-center gap-2 text-[12px]">
          <Button size="sm" variant="ghost" onClick={() => onPick([...new Set([...picked, ...shown.map((r) => r.slug)])])}>Add the {shown.length} shown</Button>
          <Button size="sm" variant="ghost" onClick={() => onPick(shown.map((r) => r.slug))}>Only these</Button>
          <Button size="sm" variant="ghost" onClick={() => onPick(picked.filter((s) => !shown.some((r) => r.slug === s)))}>Remove shown</Button>
        </div>
        <div className="max-h-72 space-y-0.5 overflow-y-auto border-y py-1.5">
          {shown.map((r) => (
            <div key={r.slug} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-muted">
              <Checkbox checked={picked.includes(r.slug)} onChange={(v) => onPick(v ? [...picked, r.slug] : picked.filter((s) => s !== r.slug))} label={<span className="font-mono text-[12px]">{r.slug}</span>} className="min-w-0 flex-1" />
              <span className="shrink-0 text-[11.5px] text-muted-foreground">{r.owner}</span>
              <Badge tone={r.verdict ? verdictTone(r.verdict) : statusTone(r.status)}>{r.verdict ?? r.status}</Badge>
            </div>
          ))}
          {!shown.length && <div className="px-1 py-2 text-[12.5px] text-muted-foreground">No run matches.</div>}
        </div>
        <div className="space-y-1.5">
          <div className="label">Saved selections · kept in this browser</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(saved).map(([n, slugs]) => (
              <span key={n} className="inline-flex h-7 items-center rounded-full border bg-card text-[12px] font-medium">
                <button className="rounded-l-full px-2.5 hover:text-primary" onClick={() => onPick(slugs.filter((s) => known.has(s)))}>{n} <span className="text-muted-foreground">{slugs.filter((s) => known.has(s)).length}</span></button>
                <button className="rounded-r-full pr-2 text-muted-foreground hover:text-foreground" aria-label={`Delete the selection ${n}`} onClick={() => { const next = { ...saved }; delete next[n]; store(next); }}><X className="h-3 w-3" /></button>
              </span>
            ))}
            {!Object.keys(saved).length && <span className="text-[12px] text-muted-foreground">None yet. Tick runs, name the selection and save it.</span>}
          </div>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!name.trim() || !picked.length) return; store({ ...saved, [name.trim()]: picked }); setName(""); }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name for the ticked runs" maxLength={40} className="h-8 flex-1" />
            <Button size="sm" type="submit" disabled={!name.trim() || !picked.length}>Save</Button>
          </form>
        </div>
      </div>
    </Popover>
  );
}

function Summary({ s, slugs, by, onBy }: { s: DatasetSummary; slugs: string[]; by: string; onBy: (k: string) => void }) {
  const n = slugs.length, peak = Math.max(1, ...s.wrong_hist.slice(1)), top = Math.max(1, ...s.groups.map((g) => g[2]));
  const low = Math.min(1, ...s.agreement.flat().filter((v): v is number => v != null));
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card className="p-3.5">
        <div className="text-[13px] font-semibold">Samples by number of runs that get them wrong</div>
        {s.scored ? <>
          <p className="mb-5 mt-0.5 text-[12px] text-muted-foreground">{s.scored.toLocaleString()} scored samples match the filters: {s.wrong_hist[0].toLocaleString()} are right in all {n} runs, {s.wrong_hist[n].toLocaleString()} are wrong in all {n}. The first bar is cut off.</p>
          <div className="flex h-24 items-end gap-0.5">
            {s.wrong_hist.map((c, k) => <div key={k} title={`${c.toLocaleString()} samples are wrong in ${k} of ${n} runs`} className={cn("relative min-h-px flex-1 rounded-t-sm", k ? "bg-danger/80" : "bg-success")} style={{ height: `${k ? (c / peak) * 100 : 100}%` }}>{c > 0 && (k === 0 || k === n) && <span className="absolute -top-4 left-1/2 -translate-x-1/2 text-[10.5px] text-muted-foreground">{c.toLocaleString()}</span>}</div>)}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted-foreground"><span>0 runs</span><span>{n} runs</span></div>
        </> : <p className="mt-0.5 text-[12px] text-muted-foreground">These samples have no truth, so no run can be wrong. Use the predicted-class filter to find the samples that many runs call the same way.</p>}
      </Card>
      <Card className="p-3.5">
        <div className="flex items-center justify-between gap-2"><div className="text-[13px] font-semibold">Where most runs are wrong</div>{Object.keys(s.facts).length > 0 && <Select size="sm" value={by} onChange={onBy} options={Object.keys(s.facts).map((k) => ({ value: k, label: `by ${k.replace(/_/g, " ")}` }))} className="w-40" />}</div>
        <p className="mb-2 mt-0.5 text-[12px] text-muted-foreground">Samples that more than half the runs get wrong, out of all that match the filters.</p>
        {s.groups.filter((g) => g[2]).slice(0, 7).map(([v, total, wrong]) => (
          <div key={v} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 py-0.5 text-[12px]"><span className="truncate font-mono text-[11.5px]" title={v}>{v}</span><span className="h-2 rounded-sm bg-primary/70" style={{ width: `${(wrong / top) * 100}%` }} /><span className="font-mono text-[11.5px] text-muted-foreground">{wrong} of {total.toLocaleString()}</span></div>
        ))}
        {!s.groups.some((g) => g[2]) && <div className="text-[12px] text-muted-foreground">None.</div>}
      </Card>
      <Card className="p-3.5">
        <div className="text-[13px] font-semibold">Run × run agreement</div>
        <p className="mb-2 mt-0.5 text-[12px] text-muted-foreground">{s.scored ? "Share of samples where two runs are both right or both wrong" : "Share of samples where two runs predict the same class"}: {pct(low)} to 100%. Hover a cell for the pair.</p>
        <div className="grid w-full max-w-[220px] gap-px" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {s.agreement.flatMap((row, a) => row.map((v, b) => <span key={`${a}-${b}`} title={`${slugs[a]} and ${slugs[b]}: ${v == null ? "no shared samples" : pct(v)}`} className="aspect-square rounded-[1px] bg-primary" style={{ opacity: v == null ? 0.04 : 0.1 + 0.9 * (low < 1 ? (v - low) / (1 - low) : 1) }} />))}
        </div>
      </Card>
    </div>
  );
}

export default function Datasets() {
  const hub = useHub();
  const [params, setParams] = useSearchParams();
  const sets = useQuery({ queryKey: ["eval-sets", hub.project], queryFn: () => get<EvalSetInfo[]>("/api/eval-sets") });
  const info = sets.data?.find((s) => s.set === params.get("set")) ?? sets.data?.[0];
  const set = info?.set ?? "";
  const [choice, setChoice] = React.useState<Record<string, string[]>>({});
  const [f, setF] = React.useState<Record<string, string>>({});
  const [sort, setSort] = React.useState("wrong");
  const [page, setPage] = React.useState(0);
  const [value, setValue] = React.useState("");
  const [by, setBy] = React.useState("");
  const [grouped, setGrouped] = React.useState(() => pref("datasets.grouped", true));
  const [panels, setPanels] = React.useState(() => pref("datasets.summary", true));
  const [open, setOpen] = React.useState<number | null>(null);
  const [view, setView] = React.useState<View>(() => ({ ...defaultView, ...pref("samples.view", {}) }));
  const updateView = (v: Partial<View>) => setView((old) => { const next = { ...old, ...v }; setPref("samples.view", next); return next; });
  const slugs = React.useMemo(() => {
    const all = info?.runs ?? [], finished = all.filter((r) => r.status === "finished");
    return (choice[set] ?? (finished.length ? finished : all).map((r) => r.slug)).filter((s) => all.some((r) => r.slug === s)).sort(byArm);
  }, [info, choice, set]);
  const query = { set, runs: slugs.join(","), value, ...f };
  const ready = !!set && slugs.length > 0;
  const summary = useQuery({ queryKey: ["dataset-summary", hub.project, query, by], enabled: ready, placeholderData: keepPreviousData, queryFn: () => get<DatasetSummary>("/api/eval-sets/summary", { ...query, by }) });
  const rows = useQuery({ queryKey: ["dataset-samples", hub.project, query, sort, page], enabled: ready, placeholderData: keepPreviousData, queryFn: () => get<DatasetPage>("/api/eval-sets/samples", { ...query, sort, limit: PAGE, offset: page * PAGE }) });
  const setFilter = (k: string, v: string) => { setF((o) => { const n = { ...o }; if (v) n[k] = v; else delete n[k]; return n; }); setPage(0); };
  const reset = () => { setF({}); setPage(0); setSort("wrong"); setValue(""); setBy(""); };
  if (!sets.data) return <div className="space-y-5"><PageHeader title="Datasets" />{sets.error ? <Empty title="The eval sets could not be loaded">{(sets.error as Error).message}. <button className="text-primary hover:underline" onClick={() => sets.refetch()}>Try again</button></Empty> : <div className="flex items-center gap-2 text-[13px] text-muted-foreground"><Spinner />Loading the eval sets…</div>}</div>;
  if (sets.data && !sets.data.length) return <div className="space-y-5"><PageHeader title="Datasets" /><Empty title="No eval samples logged yet">Once runs log per-sample results with <code>run.log_eval(rows, step=…, eval_set=…)</code>, each eval set appears here with every run's call on every sample.</Empty></div>;
  const sm = summary.data, pg = rows.data, scored = !!sm?.scored;
  const order = pg?.runs.map((r) => r.slug) ?? slugs;
  const exportCsv = async () => {
    try {
      const all = await get<DatasetPage>("/api/eval-sets/samples", { ...query, sort, compact: 1, limit: 200000 });
      const facts = [...new Set(all.rows.flatMap((r) => Object.keys(r.facts)))].sort();
      const cell = (v: unknown) => { const t = v == null ? "" : String(v); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
      const head = ["sample", "true_class", "runs", "scored", "wrong", "missed", "false_alarm", "disagreement", `${all.value || "value"}_mean`, `${all.value || "value"}_sd`, "score_mean", "top_class", "top_class_runs", ...facts];
      const lines = all.rows.map((r) => [r.sample, r.truth.class, r.runs, r.scored, r.wrong, r.missed, r.false_alarm, r.disagree, r.value_mean, r.value_sd, r.score_mean, r.classes[0]?.[0], r.classes[0]?.[1], ...facts.map((k) => r.facts[k])].map(cell).join(","));
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" }));
      a.download = `${set.replace(/[^A-Za-z0-9._-]+/g, "_")}.csv`; a.click(); URL.revokeObjectURL(a.href);
    } catch (e) { toast((e as Error).message); }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Datasets" description="One tile per sample of an eval set, with what every chosen run made of it. Each run is read at its last logged checkpoint." actions={<><Button size="sm" onClick={() => { setPanels(!panels); setPref("datasets.summary", !panels); }}>{panels ? "Hide summary" : "Show summary"}</Button><Button size="sm" disabled={!ready} onClick={exportCsv}><Download className="h-3.5 w-3.5" />Export CSV</Button></>} />
      <Card className="flex flex-wrap items-center gap-2 px-3 py-2.5">
        <Select size="sm" value={set} onChange={(v) => { setParams({ set: v }); reset(); }} options={(sets.data ?? []).map((s) => ({ value: s.set, label: s.set, hint: `${s.runs.length} runs · ${s.samples.toLocaleString()}` }))} className="w-80 font-mono text-[12.5px]" />
        {info && <RunPicker runs={info.runs} picked={slugs} onPick={(v) => { setChoice((c) => ({ ...c, [set]: v })); setPage(0); }} project={hub.project} />}
        <Switch checked={grouped} onChange={(v) => { setGrouped(v); setPref("datasets.grouped", v); }} label="Group seeds" />
        <Input value={f.q ?? ""} onChange={(e) => setFilter("q", e.target.value)} placeholder="sample id or any fact" className="h-8 w-52" />
        <div className="ml-auto flex items-center gap-2">
          {(pg?.values.length ?? 0) > 1 && <Select size="sm" value={pg!.value} onChange={(v) => { setValue(v); setPage(0); }} options={pg!.values.map((v) => ({ value: v, label: `Number: ${v}` }))} className="w-44" />}
          <Select size="sm" value={sort} onChange={(v) => { setSort(v); setPage(0); }} options={[...(scored ? [{ value: "wrong", label: "Most runs wrong" }] : []), { value: "disagree", label: "Most disagreement" }, ...(pg?.value ? [{ value: "value", label: `Highest mean ${pg.value}` }, { value: "spread", label: `Widest spread of ${pg.value}` }] : []), { value: "score", label: "Highest mean score" }, ...(f.pred_class ? [{ value: "pred", label: `Most runs predicting ${f.pred_class}` }] : []), { value: "sample", label: "Sample order" }]} className="w-56" />
        </div>
      </Card>
      {!slugs.length && <Empty title="No run chosen">Tick at least one run to see its calls.</Empty>}
      {sm && scored && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1 w-10">Show</span>
          <Chip active={!f.preset} onClick={() => setFilter("preset", "")}>All <b>{sm.total.toLocaleString()}</b></Chip>
          {PRESETS.map(([k, label]) => <Chip key={k} active={f.preset === k} onClick={() => { setFilter("preset", f.preset === k ? "" : k); if (k === "all_right" && f.preset !== k) setSort("score"); }}>{label} <b>{sm.presets[k].toLocaleString()}</b></Chip>)}
          {(f.preset === "one_wrong" || f.preset === "one_right") && <Select size="sm" value={f.run ?? ""} onChange={(v) => setFilter("run", v)} options={[{ value: "", label: "whichever run it is" }, ...slugs.map((s) => ({ value: s, label: s }))]} className="w-72 font-mono text-[12px]" />}
        </div>
      )}
      {sm && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1 w-10">Filter</span>
          {sm.class_true.length > 0 && <FacetFilter label="true class" values={sm.class_true} selected={list(f.class_true)} onChange={(v) => setFilter("class_true", v.join(","))} />}
          {Object.entries(sm.facts).map(([k, vals]) => <FacetFilter key={k} label={k.replace(/_/g, " ")} values={vals} selected={list(f["fact." + k])} onChange={(v) => setFilter("fact." + k, v.join(","))} />)}
          {sm.class_pred.length > 0 && (
            <Popover className="w-80" trigger={<Chip active={!!f.pred_class}>{f.pred_class ? `${f.pred_class}: ${f.pred_min || 0} to ${f.pred_max || slugs.length} runs` : "runs predicting a class"}<ChevronDown className="h-3 w-3" /></Chip>}>
              <div className="space-y-2">
                <p className="text-[12px] text-muted-foreground">Keep the samples that a number of runs predict as one class. It works without truth, for example "at most 3 runs say normal".</p>
                <Select size="sm" value={f.pred_class ?? ""} onChange={(v) => { setFilter("pred_class", v); if (!v) { setFilter("pred_min", ""); setFilter("pred_max", ""); if (sort === "pred") setSort("disagree"); } }} options={[{ value: "", label: "No class chosen" }, ...sm.class_pred.map((c) => ({ value: c, label: c }))]} />
                <div className="grid grid-cols-2 gap-2"><label className="space-y-1"><span className="label">at least, runs</span><Input type="number" min={0} max={slugs.length} disabled={!f.pred_class} value={f.pred_min ?? ""} onChange={(e) => setFilter("pred_min", e.target.value)} placeholder="0" className="h-8" /></label><label className="space-y-1"><span className="label">at most, runs</span><Input type="number" min={0} max={slugs.length} disabled={!f.pred_class} value={f.pred_max ?? ""} onChange={(e) => setFilter("pred_max", e.target.value)} placeholder={String(slugs.length)} className="h-8" /></label></div>
              </div>
            </Popover>
          )}
          {Object.keys(f).length > 0 && <button className="ml-1 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground" onClick={reset}><X className="h-3 w-3" /> Clear all</button>}
        </div>
      )}
      {sm && panels && <Summary s={sm} slugs={sm.runs.map((r) => r.slug)} by={sm.by ?? ""} onBy={setBy} />}
      {(summary.error || rows.error) && <Empty title="This view could not be loaded">{((summary.error || rows.error) as Error).message}</Empty>}
      {ready && !pg && !rows.error && <div className="flex items-center gap-2 text-[13px] text-muted-foreground"><Spinner />Reading {slugs.length} runs on {info?.samples.toLocaleString()} samples…</div>}
      {pg && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-muted-foreground">
          <span>{pg.total.toLocaleString()} matching sample{pg.total === 1 ? "" : "s"} · {slugs.length} run{slugs.length === 1 ? "" : "s"}</span>
          <span className="flex items-center gap-3">{scored ? <>{[["bg-success", "correct"], ["bg-danger", "missed or wrong"], ["bg-warning", "false alarm"]].map(([c, t]) => <span key={t} className="inline-flex items-center gap-1.5"><span className={cn("h-2.5 w-2.5 rounded-sm", c)} />{t}</span>)}</> : <span>colour is the predicted class</span>}<span>one cell per run</span></span>
        </div>
      )}
      {pg && (pg.rows.length ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {pg.rows.map((x, i) => { const v = verdict(x), extra = Object.entries(x.truth).find(([k, n]) => k !== "class" && typeof n === "number"); return (
            <button key={x.item} onClick={() => setOpen(i)} className="card overflow-hidden text-left transition-colors hover:border-primary/60 focus-ring">
              {x.image ? <img src={`/blobs/${x.image}`} alt="" loading="lazy" className="aspect-square w-full bg-muted object-cover" /> : <div className="grid aspect-square w-full place-content-center bg-muted text-[12px] text-muted-foreground">no image logged</div>}
              <div className="space-y-1.5 px-2.5 py-2 text-[11.5px] leading-snug">
                <div className="flex items-baseline justify-between gap-2"><span className="truncate text-[12.5px] font-semibold">{x.truth.class ?? "no truth"}</span><span className="max-w-[45%] shrink-0 truncate font-mono text-muted-foreground" title={x.sample}>{x.sample.split("/").pop()}</span></div>
                <Strip calls={x.calls ?? []} slugs={order} grouped={grouped} scored={x.scored > 0} />
                <div className="flex items-center justify-between gap-2"><Badge tone={v.tone}>{v.text}</Badge>{extra && <span className="truncate text-muted-foreground">{extra[0]} {fmt(extra[1] as number, 2)}</span>}</div>
                <div className="flex items-baseline justify-between gap-2 text-muted-foreground"><span className="truncate">{x.classes.slice(0, 2).map(([c, n]) => `${c} ${n}`).join(" · ") || "no class predicted"}</span>{x.value_mean != null && <span className="shrink-0 font-mono" title={`${pg.value}: mean ± spread across the runs`}>{fmt(x.value_mean, 2)} ± {fmt(x.value_sd, 2)}</span>}</div>
              </div>
            </button>
          ); })}
        </div>
      ) : <Empty title="No samples match these filters" />)}
      <Pager page={page} total={pg?.total ?? 0} size={PAGE} onPage={setPage} />
      {open != null && pg?.rows[open] && <SampleDialog set={set} page={pg} index={open} grouped={grouped} view={view} updateView={updateView} href={(slug) => hub.href(`runs/${slug}/samples`)} onClose={() => setOpen(null)} onIndex={setOpen} />}
    </div>
  );
}

function SampleDialog({ set, page, index, grouped, view, updateView, href, onClose, onIndex }: { set: string; page: DatasetPage; index: number; grouped: boolean; view: View; updateView: (v: Partial<View>) => void; href: (slug: string) => string; onClose: () => void; onIndex: (i: number) => void }) {
  const x = page.rows[index], calls = x.calls ?? [];
  const logged = page.runs.filter((_, i) => calls[i]);
  const [from, setFrom] = React.useState("");
  const run = logged.find((r) => r.slug === from) ?? logged[0];
  const detail = useQuery({ queryKey: ["sample", run?.slug, set, x.sample], enabled: !!run, queryFn: () => get<SampleDetail>(`/api/runs/${encodeURIComponent(run.slug)}/eval/sample`, { set, sample: x.sample }) });
  const cv = React.useRef<HTMLCanvasElement>(null);
  const d = detail.data, s = d?.steps.find((t) => t.step === run?.step) ?? d?.steps[d.steps.length - 1];
  const layers = { ...(d?.static_layers ?? {}), ...(s?.layers ?? {}) }, keys = layerKeys(layers), kinds = d?.layer_kinds ?? {};
  const truth = { ...(d?.truth ?? {}), ...(s?.truth ?? {}) }, pred = s?.pred ?? {};
  React.useEffect(() => { const c = cv.current; if (c && d) paint(c.getContext("2d", { willReadFrequently: true })!, 0, c.width, c.height, layers, keys, kinds, truth, pred, view); });
  const v = verdict(x), top = Math.max(0, ...calls.map((c) => Math.abs(c?.[2] ?? 0)));
  const arms = [...new Set(page.runs.map((r) => armOf(r.slug).arm))];
  const line = (r: { slug: string }, c: Call) => (
    <tr key={r.slug} className="border-b last:border-0">
      <td className="py-1 pr-3"><Link to={href(r.slug)} className="font-mono text-[11.5px] text-primary hover:underline">{r.slug}</Link></td>
      <td className="py-1 pr-3">{c ? c[1] || "—" : <span className="text-muted-foreground">not logged</span>}</td>
      <td className="py-1 pr-3 font-mono text-[11.5px]">{c?.[2] != null && <span className="inline-flex items-center gap-2"><span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"><span className="block h-full bg-primary/70" style={{ width: `${top ? (Math.abs(c[2]) / top) * 100 : 0}%` }} /></span>{fmt(c[2])}</span>}</td>
      <td className="py-1 pr-3 font-mono text-[11.5px]">{c?.[3] != null && fmt(c[3])}</td>
      <td className="py-1">{c && <span className="inline-flex items-center gap-1.5"><span className={cn("h-2 w-2 rounded-full", c[0] === "unscored" ? "bg-muted-foreground/50" : cellClass(c[0]))} />{OUTCOME_LABEL[c[0]] ?? c[0]}</span>}</td>
    </tr>
  );
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} wide title={<span className="flex items-center gap-3">{x.truth.class ?? "Sample"}<span className="truncate font-mono text-[11.5px] font-normal text-muted-foreground">{x.sample}</span></span>}>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div className="space-y-3">
          <canvas ref={cv} width={480} height={480} className="w-full rounded-md bg-muted" />
          {logged.length > 0 && <label className="flex items-center gap-2 text-[12px] text-muted-foreground"><span className="shrink-0">Overlays from</span><Select size="sm" value={run.slug} onChange={setFrom} options={logged.map((r) => ({ value: r.slug, label: r.slug }))} className="font-mono text-[12px]" /></label>}
          {keys.length > 0 && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex flex-wrap gap-x-4 gap-y-1">{keys.map((k) => <Checkbox key={k} checked={visible(k, view, kinds)} onChange={(on) => updateView({ show: { ...view.show, [k]: on } })} label={<span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm" style={{ background: swatch(layerColor(k, kinds)) }} />{layerName(k)}</span>} />)}</div>
              <label className="flex items-center gap-3 text-[12px]"><span className="w-16 text-muted-foreground">opacity</span><Slider value={view.op * 100} onChange={(n) => updateView({ op: n / 100 })} label="Opacity" /></label>
              <label className="flex items-center gap-3 text-[12px]"><span className="w-16 text-muted-foreground">threshold</span><Slider value={view.th * 100} onChange={(n) => updateView({ th: n / 100 })} max={95} label="Threshold" /></label>
            </div>
          )}
          <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-[12.5px]">
            {Object.entries(x.truth).filter(([, n]) => typeof n === "string" || typeof n === "number").map(([k, n]) => <React.Fragment key={k}><dt className="label pt-0.5">true {k}</dt><dd className="font-mono text-[12px]">{typeof n === "number" ? fmt(n) : String(n)}</dd></React.Fragment>)}
            {Object.entries(x.facts).map(([k, n]) => <React.Fragment key={k}><dt className="label pt-0.5">{k}</dt><dd className="break-all font-mono text-[12px]">{n}</dd></React.Fragment>)}
          </dl>
        </div>
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={v.tone}>{v.text}</Badge>
            {x.value_mean != null && <Badge>{page.value} {fmt(x.value_mean)} ± {fmt(x.value_sd)}</Badge>}
            <Badge>disagreement {pct(x.disagree)}</Badge>
            <Badge>{x.classes.slice(0, 3).map(([c, n]) => `${c} ${n}`).join(" · ") || "no class predicted"}</Badge>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-card"><tr className="border-b text-left">{["Run", "Predicted", page.value || "Number", "Score", "Outcome"].map((h) => <th key={h} className="label py-1.5 pr-3 font-semibold">{h}</th>)}</tr></thead>
              <tbody>
                {grouped ? arms.map((a) => { const mine = page.runs.map((r, i) => [r, calls[i]] as const).filter(([r]) => armOf(r.slug).arm === a); const right = mine.filter(([, c]) => c?.[0] === "correct").length; return (
                  <React.Fragment key={a}>
                    {mine.length > 1 && <tr className="bg-muted/60"><td colSpan={5} className="px-1.5 py-1 text-[12px] font-semibold">{a} <span className="font-normal text-muted-foreground">· {mine.length} seeds{x.scored ? ` · ${right} right` : ""}</span></td></tr>}
                    {mine.map(([r, c]) => line(r, c))}
                  </React.Fragment>
                ); }) : page.runs.map((r, i) => line(r, calls[i]))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2"><Button size="sm" variant="ghost" disabled={index === 0} onClick={() => onIndex(index - 1)}><ChevronLeft className="h-4 w-4" /> prev</Button><Button size="sm" variant="ghost" disabled={index >= page.rows.length - 1} onClick={() => onIndex(index + 1)}>next <ChevronRight className="h-4 w-4" /></Button></div>
        </div>
      </div>
    </Dialog>
  );
}
