import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import * as React from "react";
import { Markdown } from "@/components/ui/data";
import { toast } from "@/components/ui/overlays";
import { Avatar, Badge, Button, Card, CardHeader, Input, Textarea } from "@/components/ui/primitives";
import { api, get, type Handbook as HandbookT } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago } from "@/lib/utils";

export default function Handbook() {
  const hub = useHub();
  const qc = useQueryClient();
  const h = useQuery({ queryKey: ["handbook", hub.project], queryFn: () => get<HandbookT>("/api/handbook") });
  const [editing, setEditing] = React.useState<{ text: string; note: string; pid: number | null } | null>(null);
  const human = hub.canModerate;
  if (!h.data) return <p className="text-[13px] text-muted-foreground">Loading…</p>;
  const d = h.data;
  const save = async (e: React.FormEvent) => { e.preventDefault(); if (!editing) return; if (!editing.note.trim()) return toast("Say what changed, so agents know what to look for");
    try { await api("PUT", "/api/handbook", { text: editing.text, note: editing.note.trim(), expected_rev: d.rev, proposal_id: editing.pid }); setEditing(null); qc.invalidateQueries(); toast("Saved. Agents see the change at their next hub inbox"); } catch (err) { toast((err as Error).message); } };
  const review = async (pid: number) => { const p = await get<{ text: string; author: string; note: string; base_rev: number }>(`/api/handbook/proposals/${pid}`); if (p.base_rev !== d.rev) toast(`Proposal #${pid} was written against rev ${p.base_rev}; merge it by hand before saving.`); setEditing({ text: p.text, note: `Accepted proposal ${pid} from ${p.author}: ${p.note}`, pid }); };
  const reject = async (pid: number) => { try { await api("POST", `/api/handbook/proposals/${pid}/reject`); qc.invalidateQueries(); toast("Proposal rejected"); } catch (err) { toast((err as Error).message); } };
  const toggleStrict = async () => { try { await api("PATCH", `/api/projects/${encodeURIComponent(hub.project)}`, { settings: { ...hub.current?.settings, strict: !hub.current?.settings.strict } }); qc.invalidateQueries(); } catch (err) { toast((err as Error).message); } };
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card>
        <CardHeader title="Handbook" description={`rev ${d.rev} · ${d.author} · ${ago(d.created)} · ${d.note}`} actions={human && !editing ? <Button size="sm" onClick={() => setEditing({ text: d.text, note: "", pid: null })}><Pencil className="h-3.5 w-3.5" /> Edit</Button> : !human ? <span className="text-[12px] text-muted-foreground">Members propose changes with <code>hub handbook --propose</code>; maintainers edit</span> : null} />
        {editing ? (
          <form onSubmit={save} className="space-y-3 p-4">
            <div className="rounded-md bg-warning-soft px-3 py-2 text-[12.5px] text-warning">Saving creates revision {d.rev + 1}. Every agent in this project sees "handbook changed" in its inbox.</div>
            <Textarea value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} className="min-h-[60vh] font-mono text-[12.5px] leading-relaxed" aria-label="Handbook text" />
            <div className="flex gap-2"><Input value={editing.note} onChange={(e) => setEditing({ ...editing, note: e.target.value })} placeholder="What changed (shown to agents)" /><Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button><Button type="submit" variant="primary">Save rev {d.rev + 1}</Button></div>
          </form>
        ) : <div className="p-6"><Markdown text={d.text} project={hub.project} /></div>}
      </Card>
      <aside className="space-y-4">
        <Card>
          <CardHeader title="Project" />
          <div className="space-y-2 p-4 text-[12.5px]">
            <div><span className="text-muted-foreground">Slug</span> <span className="font-mono">{hub.project}</span></div>
            <div><span className="text-muted-foreground">Rules</span> {hub.current?.settings.strict ? "research: agent runs state hypothesis, rationale, parent and git provenance" : "plain tracking: a run only needs a name"}</div>
            {human && <Button size="sm" onClick={toggleStrict}>{hub.current?.settings.strict ? "Switch to plain tracking" : "Require research rules"}</Button>}
          </div>
        </Card>
        <Card>
          <CardHeader title="Proposals" />
          <ul className="divide-y">
            {d.proposals.map((p) => (
              <li key={p.id} className="space-y-1 px-4 py-2.5 text-[12.5px]">
                <div className="flex items-center gap-2"><Avatar name={p.author} size={18} /><b>#{p.id}</b><span>{p.author}</span><span className="text-muted-foreground">on rev {p.base_rev}</span><Badge tone={p.status === "open" ? "warning" : p.status === "accepted" ? "success" : "neutral"}>{p.status}</Badge></div>
                <div className="text-muted-foreground">{p.note}</div>
                {human && p.status === "open" && <div className="flex gap-3"><button className="text-primary hover:underline" onClick={() => review(p.id)}>Review in editor</button><button className="text-danger hover:underline" onClick={() => reject(p.id)}>Reject</button></div>}
              </li>
            ))}
            {!d.proposals.length && <li className="px-4 py-3 text-[12.5px] text-muted-foreground">No proposals.</li>}
          </ul>
        </Card>
        <Card>
          <CardHeader title="History" />
          <ul className="divide-y">{d.history.map((x) => <li key={x.rev} className="px-4 py-2 text-[12.5px]"><div className="flex items-center gap-2"><span className="font-mono font-medium">rev {x.rev}</span><span>{x.author}</span><span className="ml-auto text-muted-foreground">{ago(x.created)}</span></div><div className="truncate text-muted-foreground">{x.note}</div></li>)}</ul>
        </Card>
      </aside>
    </div>
  );
}
