// The signed-in landing page: every project you can open.
import { ArrowRight, Lock, Plus, Users } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { NewProjectDialog } from "@/components/Shell";
import { PageHeader } from "@/components/ui/form";
import { Badge, Button, Empty, Tag } from "@/components/ui/primitives";
import { useHub } from "@/lib/state";
import { ago } from "@/lib/utils";

export default function Projects() {
  const hub = useHub();
  const [creating, setCreating] = React.useState(false);
  const person = hub.me.kind === "human";
  return (
    <div className="mx-auto max-w-5xl space-y-6 py-4">
      <PageHeader title="Projects" description="Each project has its own runs, research notes, chat, handbook and members." actions={person && <Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New project</Button>} />
      {hub.projects.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {hub.projects.map((p) => (
            <Link key={p.slug} to={`/p/${encodeURIComponent(p.slug)}/home`} className="card group flex flex-col p-5 transition-all hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-pop focus-ring">
              <div className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-primary text-[15px] font-bold text-primary-foreground">{p.title.slice(0, 1).toUpperCase()}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 truncate text-[14.5px] font-semibold tracking-tight">{p.title}{p.visibility === "private" && <Lock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Private" />}</div>
                  <div className="truncate font-mono text-[11.5px] text-muted-foreground">{p.slug}</div>
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <p className="mt-3 line-clamp-2 min-h-[2.6em] text-[12.5px] text-muted-foreground">{p.description || "No description yet."}</p>
              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t pt-3 text-[12px] text-muted-foreground">
                <span><b className="font-mono font-medium text-foreground">{p.runs}</b> runs</span>
                {p.running > 0 && <Badge tone="primary" dot>{p.running} running</Badge>}
                <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5" />{p.members}</span>
                {p.settings.strict && <Tag>research rules</Tag>}
                <span className="ml-auto">{p.last_event ? ago(p.last_event) : "new"}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <Empty title={person ? "Create your first project" : "You are not in a project yet"} className="py-16">
          {person ? <>A project holds runs, research notes, chat and a handbook for the people and agents working on it.<div className="mt-4"><Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New project</Button></div></> : "Ask your owner to add this agent to a project."}
        </Empty>
      )}
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
