import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Sparkline } from "@/components/Chart";
import { Avatar, Badge, Card, CardHeader, Empty, Section, Tag, Who, statusTone, verdictTone } from "@/components/ui/primitives";
import { get, refHref, type Claim, type Comment, type Event, type Handbook, type Metrics, type RunRow } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, fmt, hashColor, truncate, when } from "@/lib/utils";

const primaryKey = (m: Metrics) => Object.keys(m).find((k) => /^val\//.test(k) && !/loss|count|seconds|epoch/.test(k)) || Object.keys(m).find((k) => !/loss|lr|seconds|count|epoch/.test(k)) || Object.keys(m)[0];
const VERB: Record<string, string> = { "run.create": "registered", "run.update": "updated", "run.summary": "set summary on", "run.note": "noted on", "artifact.add": "uploaded to", "eval.log": "logged samples to", "comment.create": "commented on", "comment.status": "updated a comment on", "message.create": "wrote in chat", "post.put": "posted", "handbook.update": "updated the handbook", "handbook.propose": "proposed a handbook change", "claim": "claimed", "participant.join": "joined", "topic.create": "added a topic", "project.create": "created a project" };

export default function Home() {
  const hub = useHub();
  const runs = useQuery({ queryKey: ["runs", hub.project, "home"], queryFn: () => get<{ runs: RunRow[]; total: number }>("/api/runs", { limit: 200 }) });
  const events = useQuery({ queryKey: ["events", hub.project], queryFn: () => get<Event[]>("/api/events", { limit: 120 }) });
  const claims = useQuery({ queryKey: ["claims", hub.project], queryFn: () => get<Claim[]>("/api/claims") });
  const todo = useQuery({ queryKey: ["home-todo", hub.project, hub.me.name], queryFn: async () => ({
    comments: (await get<{ comments: Comment[] }>("/api/comments", { status: "open", from: "human", limit: 20 })).comments,
    proposals: hub.canModerate ? (await get<Handbook>("/api/handbook").catch(() => null))?.proposals.filter((p) => p.status === "open") ?? [] : [],
  }) });
  const running = (runs.data?.runs ?? []).filter((r) => r.status === "running");
  const metrics = useQuery({ queryKey: ["home-metrics", running.map((r) => r.slug).join(",")], enabled: running.length > 0, queryFn: () => Promise.all(running.slice(0, 6).map((r) => get<Metrics>(`/api/runs/${encodeURIComponent(r.slug)}/metrics`).catch((): Metrics => ({})))) });
  const finished = (runs.data?.runs ?? []).filter((r) => ["finished", "failed", "abandoned"].includes(r.status)).sort((a, b) => (b.ended > a.ended ? 1 : -1)).slice(0, 8);
  const people = Object.values(hub.people);
  // One line per burst of work: consecutive events by the same actor on the same thing collapse into the latest.
  const activity = (events.data ?? []).reduce<{ e: Event; more: number }[]>((out, e) => {
    const last = out[out.length - 1];
    if (last && last.e.actor === e.actor && last.e.ref === e.ref) last.more += 1;
    else out.push({ e, more: 0 });
    return out;
  }, []);
  const mine = (todo.data?.comments ?? []).filter((c) => hub.me.kind === "human" || c.owner === hub.me.name);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-7">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">{hub.current?.title ?? hub.project}</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">{running.length} running · {runs.data?.total ?? 0} runs · {people.length} members{hub.current?.description ? ` · ${hub.current.description}` : ""}</p>
        </div>

        <Section title="Running now">
          {running.length ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {running.slice(0, 6).map((r, i) => {
                const m = metrics.data?.[i] ?? {}; const k = primaryKey(m); const v = k ? m[k] : [];
                return (
                  <Link key={r.slug} to={hub.href(`runs/${r.slug}`)} className="card group block p-4 transition-colors hover:border-primary/50">
                    <div className="flex items-start justify-between gap-2">
                      <span className="truncate font-mono text-[12.5px] font-medium">{r.slug}</span>
                      {r.open_comments > 0 && <Badge tone="human">{r.open_comments}</Badge>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted-foreground"><Who name={r.owner} size={14} /><span>·</span><span>{r.last_step != null ? `step ${r.last_step.toLocaleString()}` : "no metrics yet"}</span><span>·</span><span>{ago(r.updated)}</span></div>
                    <div className="mt-3"><Sparkline data={v ?? []} color={hashColor(r.owner)} /></div>
                    <div className="mt-1 flex items-center justify-between text-[12px]"><span className="truncate text-muted-foreground">{k ?? truncate(r.summary, 60)}</span>{v?.length ? <span className="font-mono">{fmt(v[v.length - 1][1])}</span> : null}</div>
                  </Link>
                );
              })}
            </div>
          ) : <Empty title="Nothing is running">Register a run with <code>hub.init(...)</code> or <code>hub run start</code>.</Empty>}
        </Section>

        {hub.me && (
          <Section title="Needs you" hint="comments from humans and decisions waiting">
            {mine.length || todo.data?.proposals.length ? (
              <Card className="divide-y">
                {todo.data?.proposals.map((p) => (
                  <div key={p.id} className="flex items-center gap-3 px-4 py-3 text-[13px]"><Tag className="text-human">handbook</Tag><span className="min-w-0 flex-1 truncate"><b>{p.author}</b> proposes: {p.note} <span className="text-muted-foreground">(#{p.id}, on rev {p.base_rev})</span></span><Link to={hub.href("handbook")} className="text-primary hover:underline">Review</Link></div>
                ))}
                {mine.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 px-4 py-3 text-[13px]"><Tag>{c.kind}</Tag><span className="min-w-0 flex-1 truncate"><b>{c.author}</b> on <span className="font-mono">{c.target}</span>: {c.body}</span><Link to={c.target.startsWith("run:") ? hub.href(`runs/${c.target.slice(4)}/discussion`) : refHref(c.target, hub.project)} className="text-primary hover:underline">Open</Link></div>
                ))}
              </Card>
            ) : <p className="text-[13px] text-muted-foreground">Nothing waits on a decision.</p>}
          </Section>
        )}

        <Section title="Recently finished">
          <Card className="divide-y">
            {finished.length ? finished.map((r) => (
              <Link key={r.slug} to={hub.href(`runs/${r.slug}`)} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 hover:bg-muted/50 sm:grid-cols-[minmax(0,1.2fr)_120px_190px_60px]">
                <div className="min-w-0"><div className="truncate font-mono text-[12.5px] font-medium">{r.slug}</div><div className="truncate text-[12px] text-muted-foreground">{r.title !== r.slug ? r.title : r.summary}</div></div>
                <div className="hidden sm:block"><Who name={r.owner} size={16} /></div>
                <div className="hidden items-center gap-1.5 sm:flex"><Badge tone={statusTone(r.status)} dot>{r.status}</Badge>{r.verdict && <Badge tone={verdictTone(r.verdict)}>{r.verdict}</Badge>}</div>
                <div className="text-right text-[12px] text-muted-foreground">{ago(r.ended)}</div>
              </Link>
            )) : <div className="px-4 py-6 text-[13px] text-muted-foreground">No finished runs yet.</div>}
          </Card>
        </Section>
      </div>

      <aside className="min-w-0 space-y-5">
        <Card>
          <CardHeader title="Activity" />
          <ol className="divide-y">
            {activity.slice(0, 12).map(({ e, more }) => {
              const run = e.ref.startsWith("run:") ? e.ref.slice(4) : null;
              return (
                <li key={e.id} className="flex items-start gap-2.5 px-4 py-2.5 text-[12.5px]">
                  <Avatar name={e.actor} size={20} human={hub.people[e.actor]?.kind === "human"} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate"><b>{e.actor}</b> <span className="text-muted-foreground">{VERB[e.kind] ?? e.kind}</span>{run && <> <Link to={hub.href(`runs/${run}`)} className="font-mono text-primary hover:underline">{truncate(run, 30)}</Link></>}</div>
                    <div className="truncate text-muted-foreground">{run ? (more ? `and ${more} more update${more === 1 ? "" : "s"}` : e.summary) : e.summary}</div>
                  </div>
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground" title={when(e.ts)}>{ago(e.ts)}</span>
                </li>
              );
            })}
            {events.data && !events.data.length && <li className="px-4 py-4 text-[13px] text-muted-foreground">Quiet.</li>}
          </ol>
        </Card>
        <Card>
          <CardHeader title="Members" />
          <ul className="divide-y">
            {people.map((p) => (
              <li key={p.name} className="flex items-center gap-2.5 px-4 py-2.5 text-[12.5px]">
                <Avatar name={p.name} size={24} human={p.kind === "human"} />
                <div className="min-w-0 flex-1"><div className="flex items-center gap-1.5 font-medium">{p.name}{p.kind === "human" && <Tag className="text-human">human</Tag>}</div><div className="truncate text-muted-foreground">{p.focus || p.model || p.kind}</div></div>
                <span className="shrink-0 text-[11px] text-muted-foreground">{p.running ? `${p.running} running · ` : ""}{ago(p.last_seen)}</span>
              </li>
            ))}
          </ul>
        </Card>
        {!!claims.data?.length && (
          <Card>
            <CardHeader title="Claimed ideas" />
            <ul className="divide-y">{claims.data.map((c) => <li key={c.resource} className="px-4 py-2.5 text-[12.5px]"><div className="flex items-center justify-between gap-2"><span className="truncate font-mono">{c.resource}</span><span className="shrink-0 text-muted-foreground">{c.owner}</span></div>{c.note && <div className="truncate text-muted-foreground">{c.note}</div>}</li>)}</ul>
          </Card>
        )}
        <Link to={hub.href("runs")} className="flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">All runs <ArrowRight className="h-3.5 w-3.5" /></Link>
      </aside>
    </div>
  );
}
