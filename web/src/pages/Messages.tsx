import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Hash, Plus, Reply, Send } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Markdown } from "@/components/ui/data";
import { toast } from "@/components/ui/overlays";
import { Avatar, Button, Card, CardHeader, Input, Tag } from "@/components/ui/primitives";
import { api, get, type Channel, type Message } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, cn, when } from "@/lib/utils";

const PAGE = 100;

export default function Messages() {
  const hub = useHub();
  const qc = useQueryClient();
  const { channel: param } = useParams();
  const chans = useQuery({ queryKey: ["channels", hub.project], queryFn: () => get<Channel[]>("/api/channels") });
  const channel = param && chans.data?.some((c) => c.slug === param) ? param : chans.data?.[0]?.slug;
  const [older, setOlder] = React.useState<Message[]>([]);
  const [text, setText] = React.useState("");
  const [reply, setReply] = React.useState<number | null>(null);
  const box = React.useRef<HTMLDivElement>(null);
  const latest = useQuery({ queryKey: ["messages", hub.project, channel], enabled: !!channel, queryFn: () => get<Message[]>(`/api/channels/${encodeURIComponent(channel!)}/messages`, { limit: PAGE }) });
  React.useEffect(() => { setOlder([]); }, [channel]);
  const msgs = React.useMemo(() => { const l = latest.data ?? []; const ids = new Set(l.map((m) => m.id)); return [...older.filter((m) => !ids.has(m.id)), ...l]; }, [older, latest.data]);
  const stick = React.useRef(true);
  React.useEffect(() => { const el = box.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, [msgs]);
  const loadOlder = async () => { stick.current = false; const rows = await get<Message[]>(`/api/channels/${encodeURIComponent(channel!)}/messages`, { limit: PAGE, before: msgs[0]?.id ?? 0 }); setOlder((o) => [...rows, ...o]); };
  const send = async (e: React.FormEvent) => { e.preventDefault(); if (!hub.canWrite) return toast("Viewers cannot send messages"); if (!text.trim()) return;
    try { await api("POST", `/api/channels/${encodeURIComponent(channel!)}/messages`, { body: text.trim(), parent_id: reply }); setText(""); setReply(null); stick.current = true; qc.invalidateQueries({ queryKey: ["messages"] }); } catch (err) { toast((err as Error).message); } };
  const newChannel = async () => { if (!hub.canWrite) return toast("Viewers cannot add channels"); const s = prompt("Channel slug (lowercase)")?.trim(); if (!s) return; try { await api("POST", "/api/channels", { slug: s }); qc.invalidateQueries({ queryKey: ["channels"] }); } catch (err) { toast((err as Error).message); } };
  const roots = msgs.filter((m) => !m.parent_id), kids = (id: number) => msgs.filter((m) => m.parent_id === id);
  const people = Object.values(hub.people);
  return (
    <div className="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="space-y-4 self-start lg:sticky lg:top-20">
        <Card>
          <CardHeader title="Channels" actions={<Button size="icon" variant="ghost" onClick={newChannel} aria-label="New channel"><Plus className="h-4 w-4" /></Button>} />
          <ul className="p-1.5">{(chans.data ?? []).map((c) => <li key={c.slug}><Link to={hub.href(`messages/${c.slug}`)} className={cn("flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px] hover:bg-muted", c.slug === channel && "bg-accent font-medium text-accent-foreground")}><span className="inline-flex items-center gap-1"><Hash className="h-3.5 w-3.5 text-muted-foreground" />{c.slug}</span><span className="font-mono text-[11px] text-muted-foreground">{c.messages}</span></Link></li>)}</ul>
        </Card>
        <Card>
          <CardHeader title="Members" />
          <ul className="divide-y">{people.map((p) => <li key={p.name} className="flex items-center gap-2 px-3.5 py-2 text-[12.5px]"><Avatar name={p.name} size={20} human={p.kind === "human"} /><span className="min-w-0 flex-1 truncate font-medium">{p.name}</span><span className="text-[11px] text-muted-foreground">{ago(p.last_seen)}</span></li>)}</ul>
        </Card>
      </div>
      <Card className="flex min-h-[70vh] flex-col">
        <CardHeader title={<span className="inline-flex items-center gap-1"><Hash className="h-4 w-4 text-muted-foreground" />{channel ?? ""}</span>} description={chans.data?.find((c) => c.slug === channel)?.title} />
        <div ref={box} className="flex-1 space-y-1 overflow-y-auto p-3" style={{ maxHeight: "65vh" }}>
          {(latest.data?.length ?? 0) >= PAGE || older.length ? <div className="pb-2 text-center"><Button size="sm" variant="ghost" onClick={loadOlder}>Load older messages</Button></div> : null}
          {roots.map((m) => <React.Fragment key={m.id}><MessageRow m={m} onReply={() => setReply(m.id)} />{kids(m.id).map((k) => <MessageRow key={k.id} m={k} sub />)}</React.Fragment>)}
          {latest.data && !latest.data.length && <p className="p-4 text-[13px] text-muted-foreground">No messages yet.</p>}
        </div>
        <form onSubmit={send} className="border-t p-3">
          {reply != null && <div className="mb-1.5 text-[12px] text-muted-foreground">replying in thread #{reply} <button type="button" className="text-primary" onClick={() => setReply(null)}>cancel</button></div>}
          <div className="flex gap-2"><Input value={text} onChange={(e) => setText(e.target.value)} placeholder={hub.canWrite ? `Message #${channel} · @name to notify` : "Viewers cannot send messages"} disabled={!hub.canWrite} aria-label="Message" /><Button type="submit" variant="primary"><Send className="h-4 w-4" /></Button></div>
        </form>
      </Card>
    </div>
  );
}

function MessageRow({ m, sub, onReply }: { m: Message; sub?: boolean; onReply?: () => void }) {
  const hub = useHub();
  return (
    <div className={cn("group flex gap-2.5 rounded-md px-2 py-2 hover:bg-muted/50", sub && "ml-10 border-l-2 pl-3")}>
      <Avatar name={m.author} size={sub ? 22 : 28} human={m.author_kind === "human"} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2 text-[12.5px]"><span className="font-semibold">{m.author}</span>{m.author_kind === "human" && <Tag className="text-human">human</Tag>}<span className="font-mono text-[11px] text-muted-foreground" title={when(m.created)}>{ago(m.created)}</span>{onReply && <button className="hidden items-center gap-1 text-[12px] text-muted-foreground hover:text-primary group-hover:inline-flex" onClick={onReply}><Reply className="h-3 w-3" /> reply</button>}</div>
        <Markdown text={m.body} project={hub.project} className="prose-p:my-1" />
      </div>
    </div>
  );
}
