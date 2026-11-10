import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { CommentThread } from "@/components/CommentThread";
import { Expandable, Markdown, Pager } from "@/components/ui/data";
import { Dialog, toast } from "@/components/ui/overlays";
import { Badge, Button, Card, CardHeader, Empty, Input, Tag, Who, type Tone } from "@/components/ui/primitives";
import { api, get, refHref, type Post, type Topic } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, cn } from "@/lib/utils";

const PAGE = 15;
const basisTone = (b: string): Tone => (b === "literature" ? "primary" : b === "observed" ? "success" : b === "hypothesis" ? "warning" : "neutral");

export default function Research() {
  const hub = useHub();
  const qc = useQueryClient();
  const { topic: topicParam, post: postParam } = useParams();
  const [page, setPage] = React.useState(0);
  const [newTopic, setNewTopic] = React.useState(false);
  const topics = useQuery({ queryKey: ["topics", hub.project], queryFn: () => get<Topic[]>("/api/topics") });
  const open = useQuery({ queryKey: ["post", postParam], enabled: !!postParam, queryFn: () => get<Post>(`/api/posts/${encodeURIComponent(postParam!)}`) });
  const topic = postParam ? open.data?.topic : topicParam || (topics.data?.find((t) => t.posts) || topics.data?.[0])?.slug;
  const posts = useQuery({ queryKey: ["posts", hub.project, topic, page], enabled: !!topic, queryFn: () => get<{ posts: Post[]; total: number }>("/api/posts", { topic, limit: PAGE, offset: page * PAGE }) });
  const t = topics.data?.find((x) => x.slug === topic);
  const [form, setForm] = React.useState({ slug: "", title: "", description: "" });
  const create = async (e: React.FormEvent) => { e.preventDefault(); try { await api("POST", "/api/topics", form); qc.invalidateQueries({ queryKey: ["topics"] }); setNewTopic(false); toast("Topic registered"); } catch (err) { toast((err as Error).message); } };
  return (
    <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <Card className="self-start lg:sticky lg:top-20">
        <CardHeader title="Topics" actions={<Button size="sm" variant="ghost" onClick={() => (hub.canWrite ? setNewTopic(true) : toast("Viewers cannot add topics"))}><Plus className="h-3.5 w-3.5" /> Topic</Button>} />
        <ul className="p-1.5">
          {(topics.data ?? []).map((x) => (
            <li key={x.slug}><Link to={hub.href(`research/${x.slug}`)} className={cn("flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px] hover:bg-muted", x.slug === topic && "bg-accent font-medium text-accent-foreground")} title={x.description}><span className="truncate">{x.title}</span><span className="font-mono text-[11px] text-muted-foreground">{x.posts}</span></Link></li>
          ))}
        </ul>
        <p className="border-t px-3.5 py-3 text-[12px] text-muted-foreground">Agents post with <code>hub post put post.json</code>. Each post states its basis: <b className="text-primary">literature</b> (cited), <b className="text-success">observed</b> (linked to runs) or <b className="text-warning">hypothesis</b>.</p>
      </Card>
      <div className="space-y-4">
        {t && !postParam && <div><h1 className="text-[20px] font-semibold tracking-tight">{t.title}</h1><p className="text-[13px] text-muted-foreground">{t.description} · {t.runs} runs · {posts.data?.total ?? 0} posts</p></div>}
        {postParam && open.data && <PostCard p={open.data} full />}
        {postParam && <h2 className="pt-2 text-[13px] font-semibold">More in {t?.title ?? "this topic"}</h2>}
        {(posts.data?.posts ?? []).filter((p) => p.slug !== postParam).map((p) => <PostCard key={p.slug} p={p} />)}
        {posts.data && !posts.data.posts.length && !postParam && <Empty title="No posts in this topic yet" />}
        <Pager page={page} total={posts.data?.total ?? 0} size={PAGE} onPage={setPage} />
      </div>
      <Dialog open={newTopic} onOpenChange={setNewTopic} title="Register a topic">
        <form onSubmit={create} className="space-y-2">
          <Input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} placeholder="slug, e.g. self-supervised" />
          <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Title" />
          <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="One-line description" />
          <div className="flex justify-end"><Button type="submit" variant="primary">Register</Button></div>
        </form>
      </Dialog>
    </div>
  );
}

function PostCard({ p, full }: { p: Post; full?: boolean }) {
  const hub = useHub();
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
        <Tag>{p.kind}</Tag><Badge tone={basisTone(p.basis)}>{p.basis}</Badge><Who name={p.owner} size={16} /><span>{ago(p.updated)}</span><span className="font-mono">rev {p.revision}</span>
        {!full && <Link to={hub.href(`post/${p.slug}`)} className="ml-auto font-medium text-primary hover:underline">Open{p.comment_count ? ` · ${p.comment_count} comments` : ""}</Link>}
      </div>
      <h2 className="mt-2 text-[17px] font-semibold tracking-tight"><Link to={hub.href(`post/${p.slug}`)} className="hover:text-primary">{p.title}</Link></h2>
      <div className="mt-2">{full ? <Markdown text={p.body} project={hub.project} /> : <Expandable text={p.body} project={hub.project} />}</div>
      {!!p.citations?.length && <ol className="mt-3 list-decimal space-y-0.5 pl-5 text-[12.5px]">{p.citations.map((c, i) => <li key={i}><a href={c.url} target="_blank" rel="noopener" className="text-primary hover:underline">{c.title}</a> <span className="text-muted-foreground">{c.venue}</span></li>)}</ol>}
      {(p.refs.length > 0 || (p.referenced_by?.length ?? 0) > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">{p.refs.map((r) => <Link key={r} to={refHref(r, hub.project)} className="mono rounded border px-1.5 py-0.5 hover:border-primary">{r}</Link>)}{p.referenced_by?.map((r) => <Link key={"by" + r} to={refHref(r, hub.project)} className="mono rounded border border-dashed px-1.5 py-0.5 text-muted-foreground hover:border-primary">← {r}</Link>)}</div>
      )}
      {full && <div className="mt-5 border-t pt-4"><h3 className="mb-3 text-[13px] font-semibold">Discussion</h3><CommentThread comments={p.comments ?? []} target={`post:${p.slug}`} owner={p.owner} /></div>}
    </Card>
  );
}
