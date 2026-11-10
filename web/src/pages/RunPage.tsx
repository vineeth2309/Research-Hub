import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Download, GitCompare, MessageSquare, Pin, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Chart } from "@/components/Chart";
import { CommentThread } from "@/components/CommentThread";
import { Checkbox, Segmented, Slider } from "@/components/ui/controls";
import { Expandable, Facts, Pager, Table, Td, Th } from "@/components/ui/data";
import { DeleteDialog } from "@/components/ui/form";
import { toast } from "@/components/ui/overlays";
import { Badge, Button, Card, CardHeader, Empty, Input, Section, Stat, Tag, Who, statusTone, verdictTone } from "@/components/ui/primitives";
import { api, get, refHref, type Artifact, type Metrics, type ModelGraphData, type Run } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, cn, duration, fmt, hashColor, pref, setPref, when } from "@/lib/utils";
import { Plots } from "./Plots";
import { Samples } from "./Samples";

const TABS = ["overview", "charts", "plots", "model", "samples", "visuals", "files", "discussion"] as const;
const ModelGraph = React.lazy(() => import("@/components/ModelGraph"));
const TAB_LABEL: Partial<Record<(typeof TABS)[number], string>> = { charts: "Metrics" };
const AUX = (k: string) => /(^|\/)(lr|grad_norm|elapsed_seconds|validation_seconds|preview_export_seconds|count|.*_count|epoch|batch|has_.*|.*_parameters|.*_bytes)$/.test(k);

export default function RunPage() {
  const hub = useHub();
  const navigate = useNavigate();
  const { slug = "", tab = "overview" } = useParams();
  const qc = useQueryClient();
  const [deleting, setDeleting] = React.useState(false);
  const run = useQuery({ queryKey: ["run", slug], queryFn: () => get<Run>(`/api/runs/${encodeURIComponent(slug)}`) });
  const metrics = useQuery({ queryKey: ["metrics", slug], queryFn: () => get<Metrics>(`/api/runs/${encodeURIComponent(slug)}/metrics`) });
  const parent = useQuery({ queryKey: ["metrics", run.data?.parent], enabled: !!run.data?.parent, queryFn: () => get<Metrics>(`/api/runs/${encodeURIComponent(run.data!.parent!)}/metrics`).catch(() => ({})) });
  if (run.error) return <Empty title="Run not found">{(run.error as Error).message}</Empty>;
  if (!run.data) return <p className="text-[13px] text-muted-foreground">Loading…</p>;
  const r = run.data, m = metrics.data ?? {}, pm = parent.data ?? {};
  const imgs = r.artifacts.filter((a) => a.mime.startsWith("image/") && a.mime !== "image/svg+xml");
  const files = r.artifacts.filter((a) => !imgs.includes(a));
  const nSamples = r.eval_sets.reduce((n, s) => Math.max(n, ...s.steps.map((x) => x.samples)), 0);
  const openN = r.comments.filter((c) => c.status === "open" && !c.parent_id).length;
  const canDelete = hub.me.kind === "human" && (hub.canModerate || hub.me.name === r.owner); // agents abandon runs; people delete them
  const remove = async () => {
    await api("DELETE", `/api/runs/${encodeURIComponent(r.slug)}`, undefined, { confirm: r.slug });
    toast(`Deleted ${r.slug}`);
    navigate(hub.href("runs"));
    qc.removeQueries({ queryKey: ["run", r.slug] });
    qc.invalidateQueries({ queryKey: ["runs"] });
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const counts: Record<string, React.ReactNode> = { charts: r.metric_keys.length || null, plots: r.charts || null, samples: nSamples || null, visuals: imgs.length || null, files: files.length || null, discussion: openN ? `${openN} open` : r.comments.length || null };
  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-1 text-[12.5px] text-muted-foreground"><Link to={hub.href("runs")} className="hover:text-foreground">Runs</Link><ChevronRight className="h-3.5 w-3.5" /><span className="font-mono text-foreground">{r.slug}</span></nav>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <h1 className="text-[22px] font-semibold tracking-tight">{r.title}</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-muted-foreground">
            <Badge tone={statusTone(r.status)} dot>{r.status}{r.status === "running" && r.last_step != null ? ` · step ${r.last_step.toLocaleString()}` : ""}</Badge>
            {r.verdict && <Badge tone={verdictTone(r.verdict)}>{r.verdict}</Badge>}
            <Tag>{r.category}</Tag>
            {r.topics.map((t) => <Link key={t} to={hub.href(`research/${t}`)} className="mono rounded border px-1.5 hover:border-primary">{t}</Link>)}
            <Who name={r.owner} size={16} human={hub.people[r.owner]?.kind === "human"} />
            <span>{r.started ? `${when(r.started)} · ${duration(r.started, r.ended || undefined)}` : "not started"}</span>
            {r.parent && <span>parent <Link to={hub.href(`runs/${r.parent}`)} className="font-mono text-primary hover:underline">{r.parent}</Link></span>}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {r.parent && <Button size="sm" onClick={() => navigate(hub.href(`compare/${r.parent},${r.slug}`))}><GitCompare className="h-3.5 w-3.5" /> Compare with parent</Button>}
          <Button size="sm" onClick={() => navigate(hub.href(`runs/${r.slug}/discussion`))}><MessageSquare className="h-3.5 w-3.5" /> Comment</Button>
          {canDelete && <Button size="sm" variant="ghost" className="text-muted-foreground hover:text-danger" onClick={() => setDeleting(true)} aria-label="Delete run"><Trash2 className="h-3.5 w-3.5" /> Delete</Button>}
        </div>
      </div>
      <nav className="flex gap-1 overflow-x-auto border-b">
        {TABS.map((t) => <Link key={t} to={hub.href(`runs/${r.slug}/${t}`)} className={cn("-mb-px inline-flex h-10 items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 text-[13px] font-medium text-muted-foreground hover:text-foreground", tab === t && "border-primary text-foreground")}>{TAB_LABEL[t] ?? t[0].toUpperCase() + t.slice(1)}{counts[t] != null && <span className="rounded-full bg-muted px-1.5 font-mono text-[11px]">{counts[t]}</span>}</Link>)}
      </nav>
      <DeleteDialog open={deleting} onOpenChange={setDeleting} what="run" name={r.slug} onDelete={remove}>
        This removes <b className="font-semibold">{r.title}</b> with its metrics, plots, per-sample results, images, notes and comments.{r.children.length > 0 && ` ${r.children.length} run${r.children.length === 1 ? "" : "s"} that name it as parent will lose that link.`}
      </DeleteDialog>
      {tab === "charts" ? <Charts r={r} metrics={m} parent={pm} /> : tab === "plots" ? <Plots run={r} /> : tab === "model" ? <Model r={r} /> : tab === "samples" ? <Samples run={r} /> : tab === "visuals" ? <Visuals r={r} imgs={imgs} /> : tab === "files" ? <Files r={r} files={files} /> : tab === "discussion" ? <Card className="p-4"><CommentThread comments={r.comments} target={`run:${r.slug}`} owner={r.owner} initialAnchor={sessionStorage.getItem("hub.anchor") ?? undefined} /></Card> : <Overview r={r} metrics={m} parent={pm} />}
    </div>
  );
}

function Overview({ r, metrics, parent }: { r: Run; metrics: Metrics; parent: Metrics }) {
  const hub = useHub();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  const [cfg, setCfg] = React.useState<string | null>(null);
  const keys = Object.keys(metrics);
  const pinned = (r.pinned.length ? r.pinned : keys.filter((k) => k.startsWith("val/") && !AUX(k)).slice(0, 4)).filter((k) => metrics[k]);
  const canEdit = hub.canModerate || (hub.canWrite && hub.me.name === r.owner);
  const addNote = async (e: React.FormEvent) => { e.preventDefault(); if (!note.trim()) return; try { await api("POST", `/api/runs/${encodeURIComponent(r.slug)}/notes`, { body: note.trim() }); setNote(""); qc.invalidateQueries({ queryKey: ["run", r.slug] }); } catch (err) { toast((err as Error).message); } };
  const showCfg = async () => setCfg(cfg == null ? (await get<{ text: string }>(`/api/runs/${encodeURIComponent(r.slug)}/config`)).text || "(empty)" : null);
  const gh = /^https:\/\/github\.com\//.test(r.repo);
  const why: [string, string][] = [["Hypothesis", r.hypothesis], ["Why this run", r.rationale], ["Expected outcome", r.expected]].filter((x) => x[1]) as [string, string][];
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-6">
        {r.summary && <p className="max-w-[80ch] text-[13.5px]">{r.summary}</p>}
        {r.conclusion && (
          <Card className="border-success/40 bg-success-soft/30">
            <CardHeader title={<span className="text-success">Conclusion</span>} description={r.verdict ? `verdict: ${r.verdict}` : undefined} />
            <div className="p-4"><Expandable text={r.conclusion} project={hub.project} lines={10} /></div>
          </Card>
        )}
        {r.summary_metrics.length > 0 && (
          <Section title="Summary" hint={r.parent ? `Δ vs ${r.parent}` : undefined}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {r.summary_metrics.map((s) => { const d = s.parent_value != null ? s.value - s.parent_value : null; const good = d == null || s.direction === "none" ? null : s.direction === "max" ? d >= 0 : d <= 0;
                return <Stat key={s.key} label={s.key} value={fmt(s.value, 4)} delta={d != null ? `${d >= 0 ? "+" : "−"}${fmt(Math.abs(d))}${good === false ? " worse" : ""}` : undefined} tone={good == null ? "neutral" : good ? "good" : "bad"} />; })}
            </div>
          </Section>
        )}
        {pinned.length > 0 && (
          <Section title="Pinned charts" hint={<span>{r.parent ? "parent dashed · " : ""}<Link to={hub.href(`runs/${r.slug}/charts`)} className="text-primary hover:underline">all {keys.length} in Metrics</Link></span>}>
            <div className="grid gap-3 md:grid-cols-2">{pinned.map((k) => <Chart key={k} title={k} syncKey={"ov:" + r.slug} series={[{ name: r.slug, data: metrics[k], color: hashColor(r.owner) }, ...(parent[k] ? [{ name: "parent", data: parent[k], color: "#94a3b8", dashed: true }] : [])]} />)}</div>
          </Section>
        )}
        {why.length > 0 && (
          <Card className="divide-y">
            {why.map(([h, t]) => <div key={h} className="p-4"><div className="label mb-1.5">{h}</div><Expandable text={t} project={hub.project} /></div>)}
          </Card>
        )}
        <Section title="Notes" hint="dated log by the owner">
          {canEdit && r.status !== "abandoned" && <form onSubmit={addNote} className="flex gap-2"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed, what you did, what to remember" /><Button type="submit" size="md">Add note</Button></form>}
          {r.notes.length ? <Card className="divide-y">{r.notes.map((n) => <div key={n.id} className="grid gap-x-4 px-4 py-2.5 text-[13px] sm:grid-cols-[150px_minmax(0,1fr)]"><div className="font-mono text-[11.5px] text-muted-foreground">{when(n.created)}<br />{n.author}</div><div className="whitespace-pre-wrap">{n.body}</div></div>)}</Card> : <p className="text-[12.5px] text-muted-foreground">No notes yet. <code>hub run note</code> or <code>run.note()</code> puts status on this timeline instead of in comments.</p>}
        </Section>
      </div>
      <aside className="min-w-0 space-y-4">
        <Card>
          <CardHeader title="Provenance" />
          <div className="p-4">
            <Facts items={[
              ["Branch", r.branch ? <>{gh ? <a className="text-primary hover:underline" href={`${r.repo}/tree/${r.branch}`} target="_blank" rel="noopener">{r.branch}</a> : r.branch}{r.commit_sha ? <> @ {gh ? <a className="text-primary hover:underline" href={`${r.repo}/commit/${r.commit_sha}`} target="_blank" rel="noopener">{r.commit_sha.slice(0, 9)}</a> : r.commit_sha.slice(0, 9)}</> : null}</> : ""],
              ["Config", r.config_path || r.config_sha ? <>{r.config_path ? (gh && r.commit_sha ? <a className="text-primary hover:underline" href={`${r.repo}/blob/${r.commit_sha}/${r.config_path}`} target="_blank" rel="noopener">{r.config_path}</a> : r.config_path) : "inline"}{r.config_sha && <> · <button className="text-primary hover:underline" onClick={showCfg}>{cfg == null ? "view" : "hide"}</button></>}</> : ""],
              ["Dataset", r.dataset ? <>{r.dataset}{r.output_dataset && <><br />→ produces <b>{r.output_dataset}</b></>}</> : ""],
              ["App", r.app], ["Command", r.command],
              ["Created", when(r.created)],
            ]} />
            {cfg != null && <pre className="mt-3 max-h-[60vh] overflow-auto rounded-md bg-muted p-3 font-mono text-[11.5px] leading-relaxed">{cfg}</pre>}
          </div>
        </Card>
        {(r.parent || r.children.length > 0) && (
          <Card><CardHeader title="Lineage" /><div className="space-y-1 p-4 font-mono text-[12px]">
            {r.parent && <><Link to={hub.href(`runs/${r.parent}`)} className="block truncate rounded-md border px-2.5 py-1.5 hover:border-primary">{r.parent}</Link><div className="pl-3 text-muted-foreground">↓</div></>}
            <div className="truncate rounded-md bg-foreground px-2.5 py-1.5 text-background">{r.slug}</div>
            {r.children.map((c) => <React.Fragment key={c}><div className="pl-3 text-muted-foreground">↓</div><Link to={hub.href(`runs/${c}`)} className="block truncate rounded-md border px-2.5 py-1.5 hover:border-primary">{c}</Link></React.Fragment>)}
          </div></Card>
        )}
        {r.eval_sets.length > 0 && (
          <Card><CardHeader title="Eval sets" actions={<Link to={hub.href(`runs/${r.slug}/samples`)} className="text-[12.5px] font-medium text-primary hover:underline">Open</Link>} /><div className="divide-y">
            {r.eval_sets.map((s) => { const last = s.steps[s.steps.length - 1]; return <div key={s.set} className="px-4 py-2.5 text-[12.5px]"><div className="truncate font-mono">{s.set}</div><div className="text-muted-foreground">{s.steps.length} checkpoint{s.steps.length === 1 ? "" : "s"} · {last.samples.toLocaleString()} samples · {last.wrong} wrong at the last</div></div>; })}
          </div></Card>
        )}
        {r.links.length > 0 && (
          <Card><CardHeader title="Links" /><div className="flex flex-wrap gap-1.5 p-4">{r.links.map((l) => { const o = l.src === `run:${r.slug}` ? l.dst : l.src; return <Link key={o + l.relation} to={refHref(o, hub.project)} className="mono rounded border px-1.5 py-0.5 hover:border-primary">{l.relation} {o}</Link>; })}</div></Card>
        )}
      </aside>
    </div>
  );
}

function Charts({ r, metrics, parent }: { r: Run; metrics: Metrics; parent: Metrics }) {
  const hub = useHub();
  const qc = useQueryClient();
  const [q, setQ] = React.useState("");
  const [smooth, setSmooth] = React.useState<number>(() => pref("charts.smooth", 0));
  const [logy, setLogy] = React.useState(false);
  const [withParent, setWithParent] = React.useState(true);
  const [cols, setCols] = React.useState<2 | 3 | 4>(() => pref("charts.cols", 3));
  const [x, setX] = React.useState<"step" | "epoch">("step");
  const [open, setOpen] = React.useState<Record<string, boolean>>({});
  const keys = Object.keys(metrics).sort();
  const epochOf = metrics.epoch ? new Map(metrics.epoch.map(([s, e]) => [s, e])) : null;
  const groups: Record<string, string[]> = {};
  keys.forEach((k) => { const g = AUX(k) ? "system" : k.includes("/") ? k.slice(0, k.lastIndexOf("/") + 1) : "other"; (groups[g] ||= []).push(k); });
  const machine = (g: string) => g.startsWith("system/"); // sampled by hub.init(system=True): x is seconds, not steps
  const rank = (g: string) => (g.startsWith("val") ? 0 : machine(g) ? 3 : g === "system" ? 2 : 1);
  const names = Object.keys(groups).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const canPin = hub.canModerate || (hub.canWrite && hub.me.name === r.owner);
  const xm = (v: [number, number][]) => (x === "epoch" && epochOf ? v.map(([s, y]) => [epochOf.get(s) ?? nearest(s), y] as [number, number]).filter((d) => d[0] != null) : v);
  const nearest = (s: number) => { let best: number | null = null; for (const k of epochOf!.keys()) if (best == null || Math.abs(k - s) < Math.abs(best - s)) best = k; return best == null ? null : epochOf!.get(best)!; };
  const pin = async (k: string) => { const pinned = r.pinned.includes(k) ? r.pinned.filter((p) => p !== k) : [...r.pinned, k]; try { await api("PATCH", `/api/runs/${encodeURIComponent(r.slug)}`, { pinned }); qc.invalidateQueries({ queryKey: ["run", r.slug] }); toast(pinned.includes(k) ? "Pinned to overview" : "Unpinned"); } catch (e) { toast((e as Error).message); } };
  if (!keys.length) return <Empty title="No metrics logged">Use <code>run.log({"{...}"}, step=…)</code> or <code>hub run metric</code>.</Empty>;
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3 text-[12.5px]">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`filter ${keys.length} keys`} className="h-8 w-48" />
        <Segmented size="sm" value={x} onChange={setX} options={[{ value: "step", label: "step" }, { value: "epoch", label: "epoch", disabled: !epochOf }]} />
        <label className="flex items-center gap-2">smoothing <Slider value={smooth * 100} onChange={(v) => { setSmooth(v / 100); setPref("charts.smooth", v / 100); }} max={90} className="w-24" label="Smoothing" /><span className="w-8 font-mono text-muted-foreground">{smooth.toFixed(2)}</span></label>
        <Checkbox checked={logy} onChange={setLogy} label="log y" />
        {r.parent && <Checkbox checked={withParent} onChange={setWithParent} label="overlay parent" />}
        <div className="ml-auto flex items-center gap-2">
          <Segmented size="sm" value={String(cols) as "2" | "3" | "4"} onChange={(v) => { setCols(+v as 2 | 3 | 4); setPref("charts.cols", +v); }} options={[{ value: "2", label: "2" }, { value: "3", label: "3" }, { value: "4", label: "4" }]} />
          <a href={`/api/runs/${encodeURIComponent(r.slug)}/metrics`} download={`${r.slug}-metrics.json`}><Button size="sm"><Download className="h-3.5 w-3.5" /> JSON</Button></a>
        </div>
      </Card>
      {names.map((g) => {
        const ks = groups[g].filter((k) => !q || k.includes(q)); if (!ks.length) return null;
        const isOpen = open[g] ?? (g !== "system" && !machine(g));
        return (
          <section key={g} className="space-y-3">
            <button className="flex w-full items-center gap-2 rounded-md border bg-card px-3 py-2 text-left hover:bg-muted/50" onClick={() => setOpen({ ...open, [g]: !isOpen })}>
              <ChevronRight className={cn("h-4 w-4 text-muted-foreground transition-transform", isOpen && "rotate-90")} /><span className="font-mono text-[12.5px] font-semibold">{g}</span><span className="text-[12px] text-muted-foreground">{ks.length} metric{ks.length === 1 ? "" : "s"}{!isOpen && " · " + ks.slice(0, 4).map((k) => `${k.slice(g === "other" || g === "system" ? 0 : g.length)} ${fmt(metrics[k][metrics[k].length - 1][1])}`).join(", ")}</span>
            </button>
            {isOpen && <div className={cn("grid gap-3", cols === 2 ? "md:grid-cols-2" : cols === 3 ? "md:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2 xl:grid-cols-4")}>
              {ks.map((k) => <Chart key={k + x} title={k} smoothing={smooth} logy={logy} xLabel={machine(g) ? "seconds" : x} syncKey={"ch:" + r.slug + (machine(g) ? "sys" : x)} series={[{ name: r.slug, data: machine(g) ? metrics[k] : xm(metrics[k]), color: hashColor(r.owner) }, ...(withParent && parent[k] && !machine(g) ? [{ name: "parent", data: xm(parent[k]), color: "#94a3b8", dashed: true }] : [])]}
                headerRight={canPin ? <button className={cn("rounded p-0.5 hover:text-foreground", r.pinned.includes(k) ? "text-primary" : "text-muted-foreground")} onClick={() => pin(k)} title={r.pinned.includes(k) ? "Unpin from overview" : "Pin to overview"} aria-label="Pin"><Pin className="h-3.5 w-3.5" /></button> : undefined} />)}
            </div>}
          </section>
        );
      })}
    </div>
  );
}

function Model({ r }: { r: Run }) {
  const [name, setName] = React.useState(r.model_graphs[0]?.name ?? "");
  const graph = useQuery({ queryKey: ["model-graph", r.slug, name], enabled: !!name, queryFn: () => get<ModelGraphData>(`/api/runs/${encodeURIComponent(r.slug)}/model-graph`, { name }) });
  if (!r.model_graphs.length) return <Empty title="No model graph logged">For a PyTorch model, call <code>run.watch(model)</code> once before training. The layers, their shapes, how they connect and where each loss comes from are captured from the first training step. The Ultralytics, Hugging Face and Lightning integrations do this for you.</Empty>;
  return (
    <div className="space-y-3">
      {r.model_graphs.length > 1 && <Segmented size="sm" value={name} onChange={setName} options={r.model_graphs.map((g) => ({ value: g.name, label: g.name }))} />}
      {graph.data ? <React.Suspense fallback={<p className="text-[13px] text-muted-foreground">Loading…</p>}><ModelGraph key={graph.data.name} graph={graph.data} /></React.Suspense> : <p className="text-[13px] text-muted-foreground">{graph.error ? (graph.error as Error).message : "Loading…"}</p>}
    </div>
  );
}

const ckKey = (a: Artifact) => (a.step == null ? "none" : String(a.step));
function Visuals({ r, imgs }: { r: Run; imgs: Artifact[] }) {
  const [page, setPage] = React.useState(0);
  const keys = [...new Set(imgs.map(ckKey))].sort((x, y) => (x === "none" ? 1 : y === "none" ? -1 : +x - +y));
  const numeric = keys.filter((k) => k !== "none");
  const [i, setI] = React.useState(() => (numeric.length ? keys.indexOf(numeric[numeric.length - 1]) : 0));
  if (!imgs.length) return <Empty title="No images logged">Use <code>run.log_images(...)</code> with step, epoch, sample and role, or let <code>hub run sync</code> send them.</Empty>;
  const epochOf: Record<string, number> = {}; imgs.forEach((a) => { if (a.epoch != null && epochOf[ckKey(a)] == null) epochOf[ckKey(a)] = a.epoch; });
  const label = (k: string) => (k === "none" ? "no step recorded" : `${epochOf[k] != null ? `epoch ${epochOf[k]} · ` : ""}step ${(+k).toLocaleString()}`);
  const k = keys[Math.min(i, keys.length - 1)], order = (key: string) => (key === "none" ? Infinity : +key), sel = order(k);
  const seen: Record<string, Set<string>> = {}; imgs.forEach((a) => { if (a.sample) (seen[a.sample] ||= new Set()).add(ckKey(a)); });
  const hasRoles = imgs.some((a) => a.role);
  const trackedIds = [...new Set(imgs.filter((a) => a.sample && (hasRoles ? a.role === "tracked" : seen[a.sample].size > 1)).map((a) => a.sample))];
  const tracked = trackedIds.map((id) => { const hist = imgs.filter((a) => a.sample === id && order(ckKey(a)) <= sel).sort((x, y) => order(ckKey(y)) - order(ckKey(x)) || y.id - x.id); return hist[0] ? { a: hist[0], older: ckKey(hist[0]) !== k } : null; }).filter(Boolean) as { a: Artifact; older: boolean }[];
  const here = imgs.filter((a) => ckKey(a) === k && !trackedIds.includes(a.sample));
  const card = (a: Artifact, older?: boolean) => (
    <figure key={a.id} className={cn("card overflow-hidden", older && "opacity-60")}>
      <a href={`/blobs/${a.blob_sha}`} target="_blank" rel="noopener"><img src={`/blobs/${a.blob_sha}`} alt={a.caption || a.name} loading="lazy" className="aspect-square w-full bg-muted object-contain" /></a>
      <figcaption className="px-2.5 py-2 text-[11.5px] leading-snug text-muted-foreground">{older && <span className="mr-1 rounded border px-1 font-mono text-[10px]">from {label(ckKey(a))}</span>}{a.caption || a.name}</figcaption>
    </figure>
  );
  return (
    <div className="space-y-5">
      {keys.length > 1 && (
        <Card className="flex flex-wrap items-center gap-3 px-4 py-3">
          <Button size="icon" variant="ghost" onClick={() => setI(Math.max(0, i - 1))} aria-label="Previous checkpoint">‹</Button>
          <Slider value={i} onChange={setI} max={keys.length - 1} className="w-64 flex-1" label="Checkpoint" />
          <Button size="icon" variant="ghost" onClick={() => setI(Math.min(keys.length - 1, i + 1))} aria-label="Next checkpoint">›</Button>
          <span className="text-[13px]"><b>{label(k)}</b> <span className="text-muted-foreground">· checkpoint {i + 1} of {keys.length}</span></span>
          <button className="text-[12.5px] text-primary hover:underline" onClick={() => setI(keys.indexOf(numeric[numeric.length - 1]))}>latest</button>
        </Card>
      )}
      {tracked.length > 0 && <Section title="Tracked samples" hint="the same examples at every checkpoint; faded = latest earlier image"><div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{tracked.map((t) => card(t.a, t.older))}</div></Section>}
      {here.length > 0 && <Section title="At this checkpoint" hint={`${here.length} image${here.length === 1 ? "" : "s"}`}><div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">{here.slice(page * 12, page * 12 + 12).map((a) => card(a))}</div><Pager page={page} total={here.length} size={12} onPage={setPage} /></Section>}
    </div>
  );
}

function Files({ files }: { r: Run; files: Artifact[] }) {
  const [page, setPage] = React.useState(0);
  const rows = files.slice().reverse();
  if (!rows.length) return <Empty title="No files">Upload logs, reports or data with <code>run.log_file(path)</code> or <code>hub run artifact --kind file</code>.</Empty>;
  return (
    <Card>
      <Table dense><thead><tr><Th>File</Th><Th>Note</Th><Th num>Step</Th><Th num>Added</Th></tr></thead>
        <tbody>{rows.slice(page * 20, page * 20 + 20).map((a) => <tr key={a.id}><Td mono><a href={`/blobs/${a.blob_sha}`} target="_blank" rel="noopener" className="text-primary hover:underline">{a.name}</a></Td><Td>{a.caption}</Td><Td num>{a.step ?? "—"}</Td><Td num className="text-muted-foreground">{ago(a.created)}</Td></tr>)}</tbody></Table>
      <Pager page={page} total={rows.length} size={20} onPage={setPage} className="border-t" />
    </Card>
  );
}
