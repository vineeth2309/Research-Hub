import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { api, refHref, type Comment } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, cn } from "@/lib/utils";
import { Avatar, Badge, Button, Input, Tag, Textarea, Who, type Tone } from "./ui/primitives";
import { Markdown } from "./ui/data";
import { Select } from "./ui/controls";
import { toast } from "./ui/overlays";

const KINDS = ["note", "question", "request", "objection", "support"];
export const statusTone = (s: string): Tone => (s === "open" ? "warning" : s === "resolved" ? "success" : "primary");

export function CommentCard({ c, owner, onReply, compact }: { c: Comment; owner?: string; onReply?: (id: number) => void; compact?: boolean }) {
  const hub = useHub();
  const qc = useQueryClient();
  const human = c.author_kind === "human";
  const canSet = hub.canModerate || (hub.canWrite && (hub.me.name === c.author || hub.me.name === owner));
  const setStatus = async (status: string) => {
    let ref = "";
    if (status === "resolved" && hub.me?.kind !== "human" && human) ref = prompt("Reference that answers it (run:<slug>, post:<slug>, comment:<id>)") || "";
    try { await api("PATCH", `/api/comments/${c.id}`, { status, resolution_ref: ref }); qc.invalidateQueries(); } catch (e) { toast((e as Error).message); }
  };
  return (
    <div className={cn("rounded-lg border p-3", human ? "border-human/30 bg-human-soft/40" : "bg-card")}>
      <div className="flex items-start gap-3">
        <Avatar name={c.author} human={human} size={28} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
            <span className="font-semibold">{c.author}</span>
            {human && <Tag className="text-human">human</Tag>}
            <Tag className={cn(c.kind === "objection" && "text-danger", c.kind === "request" && "text-warning")}>{c.kind}</Tag>
            {c.anchor && <span className="rounded border px-1.5 font-mono text-[11px] text-muted-foreground">{c.anchor}</span>}
            {!compact && c.owner && c.owner !== c.author && <span className="text-muted-foreground">→ {c.owner}</span>}
            <span className="text-muted-foreground">{ago(c.created)}</span>
            <Badge tone={statusTone(c.status)} dot>{c.status}</Badge>
            {c.resolution_ref && <Link to={refHref(c.resolution_ref, hub.project)} className="mono rounded border px-1.5 hover:border-primary">{c.resolution_ref}</Link>}
          </div>
          <Markdown text={c.body} project={hub.project} className="mt-1 text-[13px]" />
          {(c.replies ?? []).map((r) => (
            <div key={r.id} className="mt-2 border-l-2 pl-3 text-[13px]"><Who name={r.author} size={16} /> <span className="text-muted-foreground">{ago(r.created)}</span><Markdown text={r.body} project={hub.project} /></div>
          ))}
          <div className="mt-2 flex flex-wrap gap-3 text-[12.5px]">
            {onReply && <button className="font-medium text-primary hover:underline" onClick={() => onReply(c.id)}>Reply</button>}
            {canSet && c.status !== "resolved" && <button className="font-medium text-primary hover:underline" onClick={() => setStatus("resolved")}>Resolve</button>}
            {canSet && c.status === "open" && <button className="font-medium text-primary hover:underline" onClick={() => setStatus("acknowledged")}>Acknowledge</button>}
            {canSet && c.status !== "open" && <button className="font-medium text-primary hover:underline" onClick={() => setStatus("open")}>Reopen</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

export function CommentThread({ comments, target, owner, initialAnchor }: { comments: Comment[]; target: string; owner?: string; initialAnchor?: string }) {
  const hub = useHub();
  const qc = useQueryClient();
  const [body, setBody] = React.useState("");
  const [kind, setKind] = React.useState("note");
  const [anchor, setAnchor] = React.useState(initialAnchor ?? "");
  const [reply, setReply] = React.useState<number | null>(null);
  const ref = React.useRef<HTMLTextAreaElement>(null);
  const roots = comments.filter((c) => !c.parent_id).map((c) => ({ ...c, replies: comments.filter((r) => r.parent_id === c.id) }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hub.canWrite) return toast("Viewers cannot comment");
    if (!body.trim()) return;
    try {
      await api("POST", "/api/comments", { target, body: body.trim(), kind, anchor: anchor.trim(), parent_id: reply });
      setBody(""); setReply(null); setAnchor(""); qc.invalidateQueries(); toast("Comment posted");
    } catch (err) { toast((err as Error).message); }
  };
  return (
    <div className="space-y-3">
      {roots.length ? roots.map((c) => <CommentCard key={c.id} c={c} owner={owner} onReply={(id) => { setReply(id); ref.current?.focus(); }} compact />) : <p className="text-[13px] text-muted-foreground">No comments yet.</p>}
      <form onSubmit={submit} className="card space-y-2 p-3">
        <Textarea ref={ref} value={body} onChange={(e) => setBody(e.target.value)} placeholder={hub.canWrite ? `Comment as ${hub.me.name}. The owner sees it in their feedback queue.` : "Viewers cannot comment"} disabled={!hub.canWrite} aria-label="Comment" />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={kind} onChange={setKind} options={KINDS.map((k) => ({ value: k, label: k }))} className="w-32" size="sm" />
          <Input value={anchor} onChange={(e) => setAnchor(e.target.value)} placeholder="anchor, e.g. chart: val/auroc, step 11000" className="h-8 min-w-[180px] flex-1" aria-label="Anchor" />
          {reply != null && <span className="text-[12px] text-muted-foreground">replying to #{reply} <button type="button" className="text-primary" onClick={() => setReply(null)}>×</button></span>}
          <Button type="submit" variant="primary" size="sm">Post comment</Button>
        </div>
      </form>
    </div>
  );
}
