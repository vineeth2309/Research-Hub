// The project's designs: architecture boards that people draw and agents propose changes to.
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Field, FormError, PageHeader } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlays";
import { Badge, Button, Card, Empty, Input, Textarea, Who } from "@/components/ui/primitives";
import { api, get, type DesignRow } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago } from "@/lib/utils";

export default function Designs() {
  const hub = useHub();
  const [creating, setCreating] = React.useState(false);
  const list = useQuery({ queryKey: ["designs", hub.project], queryFn: () => get<DesignRow[]>("/api/designs") });
  const canDraw = hub.canWrite && hub.me.kind === "human";
  return (
    <div className="space-y-5">
      <PageHeader
        title="Designs"
        description="Boards of boxes, groups and arrows for the architecture you want built. You draw and save revisions; agents read them, comment, and propose changes that you accept or reject."
        actions={canDraw && <Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New design</Button>}
      />
      {list.data && !list.data.length && (
        <Empty title="No designs yet">
          {canDraw ? "Start one with New design." : "A project member starts one."} An agent starts one with <code>hub design create &lt;name&gt; --file design.json</code>.
        </Empty>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(list.data ?? []).map((d) => (
          <Link key={d.slug} to={hub.href(`designs/${d.slug}`)} className="focus-ring rounded-lg">
            <Card className="flex h-full flex-col gap-2 p-4 transition-colors hover:border-primary/50">
              <div className="flex items-start justify-between gap-2">
                <h2 className="min-w-0 truncate text-[15px] font-semibold">{d.title}</h2>
                <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground">rev {d.rev}</span>
              </div>
              {d.description && <p className="line-clamp-2 text-[12.5px] text-muted-foreground">{d.description}</p>}
              <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-[12px] text-muted-foreground">
                <Who name={d.author} human={hub.people[d.author]?.kind === "human"} size={16} />
                <span>{ago(d.updated)}</span>
                <span>{d.n_nodes} {d.n_nodes === 1 ? "node" : "nodes"}</span>
                {d.open_proposals > 0 && <Badge tone="warning">{d.open_proposals} to review</Badge>}
                {d.open_comments > 0 && <Badge tone="primary">{d.open_comments} open</Badge>}
              </div>
            </Card>
          </Link>
        ))}
      </div>
      <NewDesign open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function NewDesign({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const hub = useHub();
  const navigate = useNavigate();
  const [form, setForm] = React.useState({ title: "", slug: "", description: "" });
  const [error, setError] = React.useState("");
  const slug = form.slug || form.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api("POST", "/api/designs", { slug, title: form.title.trim(), description: form.description.trim() });
      navigate(`${hub.href(`designs/${slug}`)}?edit=1`);
    } catch (err) { setError((err as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New design" description="An empty board. You draw on it next.">
      <form onSubmit={submit} className="space-y-4">
        <FormError>{error}</FormError>
        <Field label="Title"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Stage 1 architecture" required autoFocus /></Field>
        <Field label="Name" hint="Agents use it: hub design get <name>. Cannot be changed later."><Input value={slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} pattern="[a-z0-9][a-z0-9._-]{0,99}" required className="font-mono" /></Field>
        <Field label="What it is for (optional)"><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="min-h-[56px]" /></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" variant="primary">Create and draw</Button></div>
      </form>
    </Dialog>
  );
}
