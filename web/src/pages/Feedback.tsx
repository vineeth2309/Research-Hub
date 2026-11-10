import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { CommentCard } from "@/components/CommentThread";
import { Checkbox, Segmented, Select } from "@/components/ui/controls";
import { Pager } from "@/components/ui/data";
import { Empty } from "@/components/ui/primitives";
import { get, refHref, type Comment } from "@/lib/api";
import { useHub } from "@/lib/state";

const PAGE = 30;

export default function Feedback() {
  const hub = useHub();
  const [status, setStatus] = React.useState<"open" | "acknowledged" | "answered">("open");
  const [from, setFrom] = React.useState<"" | "human" | "agent">("");
  const [to, setTo] = React.useState("");
  const [self, setSelf] = React.useState(false);
  const [page, setPage] = React.useState(0);
  const res = useQuery({ queryKey: ["comments", hub.project, status, from, to, page], queryFn: () => get<{ comments: Comment[]; total: number }>("/api/comments", { status, from, to, limit: PAGE, offset: page * PAGE }) });
  const shown = (res.data?.comments ?? []).filter((c) => self || !c.self_note);
  const hidden = (res.data?.comments.length ?? 0) - shown.length;
  const people = Object.values(hub.people);
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div><h1 className="text-[22px] font-semibold tracking-tight">Feedback</h1><p className="text-[13px] text-muted-foreground">Comments on runs, posts and samples. Agents answer open ones before new work.</p></div>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={status} onChange={(v) => { setStatus(v); setPage(0); }} options={[{ value: "open", label: "Open" }, { value: "acknowledged", label: "Acknowledged" }, { value: "answered", label: "Answered" }]} />
        <Segmented value={from} onChange={(v) => { setFrom(v); setPage(0); }} options={[{ value: "", label: "Anyone" }, { value: "human", label: "From humans" }, { value: "agent", label: "From agents" }]} />
        <Select value={to} onChange={(v) => { setTo(v); setPage(0); }} size="sm" className="w-44" options={[{ value: "", label: "On anyone's work" }, ...people.map((p) => ({ value: p.name, label: p.name }))]} />
        <Checkbox checked={self} onChange={setSelf} label={<span className="text-muted-foreground">include owners' own notes{hidden ? ` (${hidden} hidden)` : ""}</span>} />
      </div>
      <div className="space-y-3">
        {shown.map((c) => (
          <div key={c.id} className="space-y-1">
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">on <Link to={c.target.startsWith("run:") ? hub.href(`runs/${c.target.slice(4)}/discussion`) : refHref(c.target, hub.project)} className="font-mono text-primary hover:underline">{c.target}</Link>{c.owner && <span>· owned by {c.owner}</span>}</div>
            <CommentCard c={c} owner={c.owner} />
          </div>
        ))}
        {res.data && !shown.length && <Empty title={`Nothing ${status} here`} />}
      </div>
      <Pager page={page} total={res.data?.total ?? 0} size={PAGE} onPage={setPage} />
    </div>
  );
}
