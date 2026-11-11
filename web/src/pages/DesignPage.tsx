// One design: the board, its revisions, the proposals agents made, the runs built from it and the discussion.
// A person edits a draft with undo and saves it as the next revision; a proposal is shown as changes to accept.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Pencil, Redo2, Trash2, Undo2, WandSparkles } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CommentThread } from "@/components/CommentThread";
import { DesignCanvas } from "@/components/DesignCanvas";
import { Switch } from "@/components/ui/controls";
import { DeleteDialog, Field, FormError, PageHeader } from "@/components/ui/form";
import { Dialog, Tooltip, toast } from "@/components/ui/overlays";
import { Avatar, Badge, Button, Card, CardHeader, Input, Textarea, statusTone } from "@/components/ui/primitives";
import { api, get, type Design, type DesignEdge, type DesignGraph, type DesignNode, type DesignProposal } from "@/lib/api";
import { COLORS, diffDesign, edgeKey } from "@/lib/design";
import { useHub } from "@/lib/state";
import { ago, cn } from "@/lib/utils";

interface Draft { graph: DesignGraph; past: DesignGraph[]; future: DesignGraph[]; note: string; proposal: number | null; fit: number }
type Proposal = DesignProposal & { design: string; graph: DesignGraph };
const name = (n: DesignNode) => n.label.split("\n")[0] || n.id;

export default function DesignPage() {
  const hub = useHub();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { design: slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const path = `/api/designs/${encodeURIComponent(slug)}`;
  const [view, setView] = React.useState<{ rev: number | null; proposal: number | null }>({ rev: null, proposal: null });
  const [changes, setChanges] = React.useState(false);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [sel, setSel] = React.useState<string | null>(null);
  const [anchor, setAnchor] = React.useState("");
  const [dialog, setDialog] = React.useState<"delete" | "details" | null>(null);

  const head = useQuery({ queryKey: ["design", slug], queryFn: () => get<Design>(path) });
  const old = useQuery({ queryKey: ["design", slug, view.rev], enabled: view.rev != null, queryFn: () => get<Design>(path, { rev: view.rev }) });
  const d = head.data;
  const shown = view.rev != null ? old.data : d;
  const rev = view.rev ?? d?.head ?? 1;
  const before = useQuery({ queryKey: ["design", slug, rev - 1], enabled: changes && !draft && view.proposal == null && rev > 1, queryFn: () => get<Design>(path, { rev: rev - 1 }) });
  const proposal = useQuery({ queryKey: ["design-proposal", view.proposal], enabled: view.proposal != null, queryFn: () => get<Proposal>(`/api/design-proposals/${view.proposal}`) });

  const board = React.useMemo(() => {
    if (draft) return { graph: draft.graph, marks: undefined };
    if (view.proposal != null) return d && proposal.data ? diffDesign(d.graph, proposal.data.graph) : null;
    if (!shown) return null;
    return changes && before.data ? diffDesign(before.data.graph, shown.graph) : { graph: shown.graph, marks: undefined };
  }, [draft, view.proposal, d, proposal.data, shown, changes, before.data]);

  const edit = React.useCallback((graph: DesignGraph, note = "", from: number | null = null) => { setDraft({ graph, past: [], future: [], note, proposal: from, fit: 0 }); setSel(null); }, []);
  const change = React.useCallback((graph: DesignGraph) => setDraft((x) => x && { ...x, graph, past: [...x.past.slice(-99), x.graph], future: [] }), []);
  const undo = React.useCallback(() => setDraft((x) => (x?.past.length ? { ...x, graph: x.past[x.past.length - 1], past: x.past.slice(0, -1), future: [x.graph, ...x.future] } : x)), []);
  const redo = React.useCallback(() => setDraft((x) => (x?.future.length ? { ...x, graph: x.future[0], past: [...x.past, x.graph], future: x.future.slice(1) } : x)), []);
  const editing = !!draft, dirty = !!draft?.past.length;

  React.useEffect(() => { // a new design opens ready to draw
    if (d && params.get("edit") && !editing) { edit(d.graph); setParams({}, { replace: true }); }
  }, [d, params, editing, edit, setParams]);
  React.useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || (e.target as HTMLElement).closest("input, textarea")) return;
      e.preventDefault();
      (e.shiftKey ? redo : undo)();
    };
    const onLeave = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    document.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onLeave);
    return () => { document.removeEventListener("keydown", onKey); window.removeEventListener("beforeunload", onLeave); };
  }, [editing, dirty, undo, redo]);

  if (head.error) return <p className="text-[13px] text-muted-foreground">{(head.error as Error).message}</p>;
  if (!d || !board) return <p className="text-[13px] text-muted-foreground">Loading…</p>;

  const human = hub.me.kind === "human", canDraw = hub.canWrite && human;
  const latest = () => { setView({ rev: null, proposal: null }); setSel(null); };
  const done = (message: string) => { setDraft(null); latest(); void qc.invalidateQueries(); toast(message); };
  const fail = (err: unknown) => toast((err as Error).message);
  const tidy = async () => {
    try {
      const graph = await api<DesignGraph>("POST", "/api/designs/layout", { graph: draft!.graph });
      setDraft((x) => x && { ...x, graph, past: [...x.past, x.graph], future: [], fit: x.fit + 1 });
    } catch (err) { fail(err); }
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft!.note.trim()) return toast("Say what changed, so agents know what to look for");
    try {
      await api("PUT", path, { graph: draft!.graph, note: draft!.note.trim(), expected_rev: d.head, proposal_id: draft!.proposal });
      done(`Saved as rev ${d.head + 1}. Agents see it at their next hub inbox`);
    } catch (err) { fail(err); }
  };
  const acceptNote = (p: Proposal) => `Accepted proposal ${p.id} from ${p.author}: ${p.note}`.slice(0, 300);
  const accept = async (p: Proposal) => {
    try { await api("PUT", path, { graph: p.graph, note: acceptNote(p), expected_rev: d.head, proposal_id: p.id }); done(`Proposal ${p.id} is now rev ${d.head + 1}`); } catch (err) { fail(err); }
  };
  const reject = async (p: Proposal) => {
    try { await api("POST", `/api/design-proposals/${p.id}/reject`); done(`Proposal ${p.id} rejected`); } catch (err) { fail(err); }
  };
  const remove = async () => { await api("DELETE", path, undefined, { confirm: d.slug }); await qc.invalidateQueries(); navigate(hub.href("designs")); };

  const graph = board.graph;
  const node = sel && !sel.startsWith("edge:") ? graph.nodes.find((n) => n.id === sel) : undefined;
  const edge = sel?.startsWith("edge:") ? graph.edges.find((e) => `edge:${edgeKey(e)}` === sel) : undefined;
  const setNode = (next: DesignNode) => change({ nodes: graph.nodes.map((n) => (n.id === next.id ? next : n)), edges: graph.edges });
  const setEdge = (next: DesignEdge) => { change({ nodes: graph.nodes, edges: graph.edges.map((e) => (e === edge ? next : e)) }); setSel(`edge:${edgeKey(next)}`); };
  const discuss = (about: string) => { setAnchor(about); document.getElementById("design-discussion")?.scrollIntoView({ behavior: "smooth" }); };
  const p = view.proposal != null ? proposal.data : undefined;
  const fitKey = `${slug}:${draft ? `draft${draft.fit}` : p ? `p${p.id}` : `r${rev}`}`;

  return (
    <div className="space-y-4">
      <div className="text-[12.5px] text-muted-foreground"><Link to={hub.href("designs")} className="hover:text-foreground">Designs</Link> / <span className="font-mono">{d.slug}</span></div>
      <PageHeader
        title={d.title}
        description={d.description || undefined}
        actions={!editing && canDraw && (
          <>
            {(hub.canModerate || hub.me.name === d.owner) && <Button variant="ghost" className="text-muted-foreground hover:text-danger" onClick={() => setDialog("delete")}><Trash2 className="h-4 w-4" /> Delete</Button>}
            <Button onClick={() => setDialog("details")}>Rename</Button>
            <Button variant="primary" onClick={() => { latest(); edit(d.graph); }}><Pencil className="h-4 w-4" /> Edit</Button>
          </>
        )}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden">
          <div className="flex min-h-[52px] flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2 text-[12.5px]">
            {draft ? (
              <form onSubmit={save} className="flex w-full flex-wrap items-center gap-2">
                <span className="font-medium">{draft.proposal ? `Editing proposal ${draft.proposal}` : "Editing"} → rev {d.head + 1}</span>
                <Input value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder="What changed (shown to agents)" className="h-8 min-w-[200px] flex-1" aria-label="What changed" />
                <Button type="button" size="sm" variant="ghost" onClick={() => { if (!dirty || confirm("Discard your changes to this design?")) { setDraft(null); setSel(null); } }}>Cancel</Button>
                <Button type="submit" size="sm" variant="primary">Save rev {d.head + 1}</Button>
              </form>
            ) : p ? (
              <>
                <Avatar name={p.author} human={hub.people[p.author]?.kind === "human"} size={20} />
                <span className="min-w-0 flex-1"><b className="font-semibold">Proposal {p.id}</b> by {p.author}, drawn on rev {p.base_rev}: {p.note}</span>
                {p.base_rev !== d.head && p.status === "open" && <Badge tone="warning">the design has moved to rev {d.head}</Badge>}
                {p.status !== "open" ? <Badge tone={p.status === "accepted" ? "success" : "neutral"}>{p.status} by {p.decided_by}</Badge> : canDraw && (
                  <>
                    <Button size="sm" variant="ghost" className="text-danger" onClick={() => reject(p)}>Reject</Button>
                    <Button size="sm" onClick={() => edit(p.graph, acceptNote(p), p.id)}>Edit first</Button>
                    <Button size="sm" variant="primary" onClick={() => accept(p)}>Accept as rev {d.head + 1}</Button>
                  </>
                )}
                <Button size="sm" variant="ghost" onClick={latest}>Close</Button>
              </>
            ) : shown ? (
              <>
                <Avatar name={shown.author} human={hub.people[shown.author]?.kind === "human"} size={20} />
                <span className="min-w-0 flex-1 truncate"><b className="font-mono font-semibold">rev {shown.rev}</b>{shown.rev !== d.head && ` of ${d.head}`} · {shown.author} · {ago(shown.saved)} · {shown.note}</span>
                {rev > 1 && <Switch checked={changes} onChange={setChanges} label={`Changes since rev ${rev - 1}`} />}
                {shown.rev !== d.head && canDraw && <Button size="sm" onClick={() => { const from = shown; latest(); edit(from.graph, `Restore rev ${from.rev}`); }}>Restore</Button>}
                {shown.rev !== d.head && <Button size="sm" variant="ghost" onClick={latest}>Back to latest</Button>}
              </>
            ) : null}
          </div>
          <div className="h-[68vh] min-h-[440px]">
            <DesignCanvas
              graph={graph} marks={board.marks} editable={editing} selected={sel} onSelect={setSel} onChange={change} fitKey={fitKey} theme={hub.theme === "dark" ? "dark" : "light"}
              tools={<>
                <Tooltip content="Undo (Ctrl+Z)"><button type="button" className="dz-tool" onClick={undo} disabled={!draft?.past.length} aria-label="Undo"><Undo2 className="h-4 w-4" /></button></Tooltip>
                <Tooltip content="Redo (Ctrl+Shift+Z)"><button type="button" className="dz-tool" onClick={redo} disabled={!draft?.future.length} aria-label="Redo"><Redo2 className="h-4 w-4" /></button></Tooltip>
                <Tooltip content="Tidy: arrange everything from its connections"><button type="button" className="dz-tool" onClick={tidy} disabled={!graph.nodes.length} aria-label="Tidy layout"><WandSparkles className="h-4 w-4" /></button></Tooltip>
                <span className="dz-sep" />
              </>}
            />
          </div>
        </Card>
        <aside className="space-y-4">
          {node && (
            <Card>
              <CardHeader title={editing ? `Selected ${node.kind}` : name(node)} description={<span className="font-mono">{node.id}</span>} />
              {editing ? <NodeEditor key={node.id} node={node} onChange={setNode} /> : <NodeFacts node={node} graph={graph} onPick={setSel} onDiscuss={() => discuss(`node: ${node.id}`)} />}
            </Card>
          )}
          {edge && (
            <Card>
              <CardHeader title="Selected arrow" description={<span className="font-mono">{edge.from} → {edge.to}</span>} />
              {editing ? <EdgeEditor key={edgeKey(edge)} edge={edge} taken={graph.edges.some((e) => e.from === edge.to && e.to === edge.from)} onChange={setEdge} />
                : <div className="space-y-2 p-4 text-[12.5px]">{edge.label ? <p className="font-mono">{edge.label}</p> : <p className="text-muted-foreground">No label.</p>}<Button size="sm" onClick={() => discuss(`arrow: ${edgeKey(edge)}`)}>Comment on this arrow</Button></div>}
            </Card>
          )}
          {!editing && (
            <>
              <Card>
                <CardHeader title="Proposals" />
                <ul className="divide-y">
                  {d.proposals.map((x) => (
                    <li key={x.id}>
                      <button type="button" onClick={() => { setView({ rev: null, proposal: x.id }); setSel(null); }} className={cn("w-full space-y-1 px-4 py-2.5 text-left text-[12.5px] hover:bg-muted/60", view.proposal === x.id && "bg-accent/60")}>
                        <span className="flex items-center gap-2"><Avatar name={x.author} human={hub.people[x.author]?.kind === "human"} size={18} /><b>#{x.id}</b><span>{x.author}</span><span className="text-muted-foreground">on rev {x.base_rev}</span><Badge tone={x.status === "open" ? "warning" : x.status === "accepted" ? "success" : "neutral"}>{x.status}</Badge></span>
                        <span className="block text-muted-foreground">{x.note}</span>
                      </button>
                    </li>
                  ))}
                  {!d.proposals.length && <li className="px-4 py-3 text-[12.5px] text-muted-foreground">None. Agents propose with <code>hub design propose {d.slug} FILE --note "why"</code>.</li>}
                </ul>
              </Card>
              <Card>
                <CardHeader title="History" />
                <ul className="max-h-[300px] divide-y overflow-auto">
                  {d.history.map((x) => (
                    <li key={x.rev}>
                      <button type="button" onClick={() => { setView({ rev: x.rev === d.head ? null : x.rev, proposal: null }); setSel(null); }} className={cn("w-full px-4 py-2 text-left text-[12.5px] hover:bg-muted/60", !p && x.rev === rev && "bg-accent/60")}>
                        <span className="flex items-center gap-2"><span className="font-mono font-medium">rev {x.rev}</span><span>{x.author}</span><span className="ml-auto text-muted-foreground">{ago(x.created)}</span></span>
                        <span className="block truncate text-muted-foreground">{x.note}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
              {d.runs.length > 0 && (
                <Card>
                  <CardHeader title="Runs built from it" />
                  <ul className="divide-y">{d.runs.map((r) => <li key={r.slug} className="flex items-center gap-2 px-4 py-2 text-[12.5px]"><Link to={hub.href(`runs/${r.slug}`)} className="min-w-0 flex-1 truncate font-mono text-primary hover:underline">{r.slug}</Link>{r.dst.includes("@") && <span className="text-muted-foreground">rev {r.dst.split("@")[1]}</span>}<Badge tone={statusTone(r.status)}>{r.status}</Badge></li>)}</ul>
                </Card>
              )}
            </>
          )}
        </aside>
      </div>
      <Card id="design-discussion" className="space-y-3 p-4">
        <h2 className="text-[14px] font-semibold">Discussion</h2>
        <CommentThread key={anchor} comments={d.comments} target={`design:${d.slug}`} owner={d.owner} initialAnchor={anchor} />
      </Card>
      <DeleteDialog open={dialog === "delete"} onOpenChange={(o) => setDialog(o ? "delete" : null)} what="design" name={d.slug} onDelete={remove}>
        This removes <b className="font-semibold">{d.title}</b> with its {d.head} {d.head === 1 ? "revision" : "revisions"}, its proposals and its comments.
      </DeleteDialog>
      <Details open={dialog === "details"} onOpenChange={(o) => setDialog(o ? "details" : null)} design={d} />
    </div>
  );
}

function NodeEditor({ node, onChange }: { node: DesignNode; onChange: (n: DesignNode) => void }) {
  const [label, setLabel] = React.useState(node.label);
  const [detail, setDetail] = React.useState(node.detail ?? "");
  React.useEffect(() => { setLabel(node.label); setDetail(node.detail ?? ""); }, [node.label, node.detail]); // text typed on the board shows here too
  const put = (patch: Partial<DesignNode>) => {
    const next = { ...node, ...patch };
    if (!next.detail) delete next.detail;
    if (!next.color || next.color === "neutral") delete next.color;
    onChange(next);
  };
  return (
    <div className="space-y-3 p-4">
      <Field label="Text"><Textarea value={label} onChange={(e) => setLabel(e.target.value)} onBlur={() => { if (label.trim() !== node.label) put({ label: label.trim() }); }} className="min-h-[52px]" /></Field>
      {node.kind !== "group" && <Field label="Notes" hint="Shapes, settings, the reason for it. Agents read this."><Textarea value={detail} onChange={(e) => setDetail(e.target.value)} onBlur={() => { if (detail.trim() !== (node.detail ?? "")) put({ detail: detail.trim() }); }} className="min-h-[72px] font-mono text-[12px]" /></Field>}
      <Field label="Colour"><div className="flex gap-2">{COLORS.map((c) => <button key={c} type="button" title={c} aria-label={c} aria-pressed={(node.color ?? "neutral") === c} onClick={() => put({ color: c })} className={cn("dz-swatch focus-ring", `dz-c-${c}`, (node.color ?? "neutral") === c && "ring-2 ring-primary ring-offset-2 ring-offset-card")} />)}</div></Field>
    </div>
  );
}

function EdgeEditor({ edge, taken, onChange }: { edge: DesignEdge; taken: boolean; onChange: (e: DesignEdge) => void }) {
  const [label, setLabel] = React.useState(edge.label ?? "");
  const put = (patch: Partial<DesignEdge>) => {
    const next = { ...edge, ...patch };
    if (!next.label) delete next.label;
    if (!next.dashed) delete next.dashed;
    onChange(next);
  };
  return (
    <div className="space-y-3 p-4">
      <Field label="Label" hint="What flows along it, e.g. a tensor shape."><Input value={label} onChange={(e) => setLabel(e.target.value)} onBlur={() => { if (label.trim() !== (edge.label ?? "")) put({ label: label.trim() }); }} autoFocus className="font-mono text-[12.5px]" /></Field>
      <Switch checked={!!edge.dashed} onChange={(dashed) => put({ dashed })} label="Dashed, for a secondary path such as gradients" />
      <Button size="sm" disabled={taken} onClick={() => put({ from: edge.to, to: edge.from })}><ArrowLeftRight className="h-3.5 w-3.5" /> Reverse direction</Button>
    </div>
  );
}

function NodeFacts({ node, graph, onPick, onDiscuss }: { node: DesignNode; graph: DesignGraph; onPick: (id: string) => void; onDiscuss: () => void }) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const list = (title: string, edges: DesignEdge[], end: "from" | "to") => edges.length > 0 && (
    <div>
      <div className="label mb-1">{title}</div>
      <ul className="space-y-1">{edges.map((e) => <li key={edgeKey(e)}><button type="button" className="text-left text-primary hover:underline" onClick={() => onPick(e[end])}>{byId.has(e[end]) ? name(byId.get(e[end])!) : e[end]}</button>{e.label && <span className="ml-2 font-mono text-[11.5px] text-muted-foreground">{e.label}</span>}</li>)}</ul>
    </div>
  );
  return (
    <div className="space-y-3 p-4 text-[12.5px]">
      {node.detail && <p className="whitespace-pre-wrap font-mono text-[12px]">{node.detail}</p>}
      {node.group && byId.has(node.group) && <p className="text-muted-foreground">In group <button type="button" className="text-primary hover:underline" onClick={() => onPick(node.group!)}>{name(byId.get(node.group)!)}</button></p>}
      {list("Receives from", graph.edges.filter((e) => e.to === node.id), "from")}
      {list("Sends to", graph.edges.filter((e) => e.from === node.id), "to")}
      <Button size="sm" onClick={onDiscuss}>Comment on this</Button>
    </div>
  );
}

function Details({ open, onOpenChange, design }: { open: boolean; onOpenChange: (o: boolean) => void; design: Design }) {
  const qc = useQueryClient();
  const [form, setForm] = React.useState({ title: design.title, description: design.description });
  const [error, setError] = React.useState("");
  React.useEffect(() => { if (open) { setForm({ title: design.title, description: design.description }); setError(""); } }, [open, design.title, design.description]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api("PUT", `/api/designs/${encodeURIComponent(design.slug)}`, { title: form.title.trim(), description: form.description.trim() }); await qc.invalidateQueries(); onOpenChange(false); } catch (err) { setError((err as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Rename this design" description="The name agents use stays the same.">
      <form onSubmit={submit} className="space-y-4">
        <FormError>{error}</FormError>
        <Field label="Title"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required autoFocus /></Field>
        <Field label="What it is for"><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="min-h-[72px]" /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" variant="primary">Save</Button></div>
      </form>
    </Dialog>
  );
}
