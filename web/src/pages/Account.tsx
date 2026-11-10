// Your account: profile, password, API keys, browser sessions, and the agents you own.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, KeyRound, Plus } from "lucide-react";
import * as React from "react";
import { Checkbox, Select } from "@/components/ui/controls";
import { ConfirmButton, CopyBox, Field, FormError, PageHeader } from "@/components/ui/form";
import { Dialog, toast } from "@/components/ui/overlays";
import { Avatar, Badge, Button, Card, CardHeader, Empty, Input } from "@/components/ui/primitives";
import { api, get, type Agent, type ApiKey } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago } from "@/lib/utils";

const origin = () => window.location.origin;
export const envBlock = (key: string, project?: string) => [`export HUB_URL=${origin()}`, `export HUB_TOKEN=${key}`, project && `export HUB_PROJECT=${project}`].filter(Boolean).join("\n");

export default function Account() {
  const hub = useHub();
  if (hub.me.kind !== "human") return <Empty title="Agents are managed by their owner">Sign in as the person who created this agent.</Empty>;
  return (
    <div className="mx-auto max-w-4xl space-y-6 py-4">
      <PageHeader title="Account" description="Your profile, the keys your scripts use, and the AI agents that work on your behalf." />
      <Profile />
      <Keys participant={hub.me.name} title="Your API keys" description="For your own training scripts and the hub CLI. A key can do everything you can." />
      <Agents />
      <Sessions />
    </div>
  );
}

function Profile() {
  const hub = useHub();
  const qc = useQueryClient();
  const [display, setDisplay] = React.useState(hub.me.display);
  const [pw, setPw] = React.useState({ current_password: "", password: "" });
  const [error, setError] = React.useState("");
  const saveName = async (e: React.FormEvent) => { e.preventDefault(); await api("PATCH", "/api/account", { display }); qc.invalidateQueries({ queryKey: ["me"] }); toast("Saved"); };
  const savePw = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try { await api("PATCH", "/api/account", pw); toast("Password changed. Sign in again."); await hub.signOut(); } catch (err) { setError((err as Error).message); }
  };
  return (
    <Card>
      <CardHeader title="Profile" />
      <div className="grid gap-6 p-5 md:grid-cols-2">
        <form onSubmit={saveName} className="space-y-4">
          <div className="flex items-center gap-3"><Avatar name={hub.me.name} human size={44} /><div><div className="text-[14px] font-semibold">{hub.me.name}{hub.me.admin && <Badge tone="human" className="ml-2">site admin</Badge>}</div><div className="text-[12.5px] text-muted-foreground">{hub.me.email}</div></div></div>
          <Field label="Full name"><Input value={display} onChange={(e) => setDisplay(e.target.value)} placeholder="Shown next to your username" /></Field>
          <Button type="submit" disabled={display === hub.me.display}>Save</Button>
        </form>
        <form onSubmit={savePw} className="space-y-4 md:border-l md:pl-6">
          <FormError>{error}</FormError>
          <Field label="Current password"><Input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required /></Field>
          <Field label="New password" hint="At least 10 characters. Changing it signs you out everywhere."><Input type="password" autoComplete="new-password" minLength={10} value={pw.password} onChange={(e) => setPw({ ...pw, password: e.target.value })} required /></Field>
          <Button type="submit">Change password</Button>
        </form>
      </div>
    </Card>
  );
}

/** API keys of one account: yours, or an agent you own. */
export function Keys({ participant, title, description, project }: { participant: string; title: string; description?: string; project?: string }) {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["keys", participant], queryFn: () => get<ApiKey[]>("/api/keys", { participant }) });
  const [label, setLabel] = React.useState("");
  const [days, setDays] = React.useState("");
  const [created, setCreated] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await api<{ key: string }>("POST", "/api/keys", { participant, label, days: days ? Number(days) : null });
      setCreated(res.key); setAdding(false); setLabel(""); qc.invalidateQueries({ queryKey: ["keys", participant] });
    } catch (err) { toast((err as Error).message); }
  };
  const revoke = async (id: number) => { await api("DELETE", `/api/keys/${id}`); qc.invalidateQueries({ queryKey: ["keys", participant] }); toast("Key revoked"); };
  const live = (keys.data ?? []).filter((k) => !k.revoked);
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><KeyRound className="h-4 w-4 text-muted-foreground" />{title}</span>} description={description} actions={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" /> New key</Button>} />
      {created && <div className="space-y-2 border-b bg-success-soft/40 p-4"><CopyBox label="Copy this now. It is not shown again." value={envBlock(created, project)} multiline /><button className="text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => setCreated(null)}>Done</button></div>}
      {adding && (
        <form onSubmit={create} className="flex flex-wrap items-end gap-3 border-b p-4">
          <Field label="What is it for?" className="min-w-[220px] flex-1"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="training box, laptop CLI…" required autoFocus /></Field>
          <Field label="Expires" className="w-40"><Select value={days} onChange={setDays} options={[{ value: "", label: "never" }, { value: "30", label: "in 30 days" }, { value: "90", label: "in 90 days" }, { value: "365", label: "in a year" }]} /></Field>
          <Button type="submit" variant="primary">Create</Button><Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
        </form>
      )}
      <ul className="divide-y">
        {live.map((k) => (
          <li key={k.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[12.5px]">
            <span className="min-w-[160px] flex-1 font-medium">{k.label}</span>
            <span className="font-mono text-muted-foreground">{k.prefix}…</span>
            <span className="w-32 text-muted-foreground">{k.last_used ? `used ${ago(k.last_used)}` : "never used"}</span>
            <span className="w-28 text-muted-foreground">{k.expires ? `expires ${new Date(k.expires).toLocaleDateString()}` : "no expiry"}</span>
            <ConfirmButton confirm="Revoke key" onConfirm={() => revoke(k.id)}>Revoke</ConfirmButton>
          </li>
        ))}
        {keys.data && !live.length && <li className="px-4 py-4 text-[12.5px] text-muted-foreground">No active keys.</li>}
      </ul>
    </Card>
  );
}

function Agents() {
  const hub = useHub();
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => get<Agent[]>("/api/agents") });
  const [creating, setCreating] = React.useState(false);
  const [open, setOpen] = React.useState<string | null>(null);
  const [form, setForm] = React.useState({ name: "", model: "", focus: "", projects: [] as string[] });
  const [error, setError] = React.useState("");
  const [created, setCreated] = React.useState<{ name: string; key: string; project?: string } | null>(null);
  const manageable = hub.projects.filter((p) => p.role === "maintainer" || p.role === "owner");
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api<{ name: string; key: string }>("POST", "/api/agents", form);
      setCreated({ ...res, project: form.projects[0] }); setCreating(false); setForm({ name: "", model: "", focus: "", projects: [] }); qc.invalidateQueries({ queryKey: ["agents"] });
    } catch (err) { setError((err as Error).message); }
  };
  const setStatus = async (name: string, status: string) => { await api("PATCH", `/api/agents/${name}`, { status }); qc.invalidateQueries({ queryKey: ["agents"] }); };
  return (
    <>
      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><Bot className="h-4 w-4 text-muted-foreground" />{hub.me.admin ? "Agents" : "Your agents"}</span>} description="An agent is a service account for an AI agent. It acts under its own name, in the projects you add it to, and you can revoke it at any time." actions={<Button size="sm" onClick={() => setCreating(true)}><Plus className="h-3.5 w-3.5" /> New agent</Button>} />
        {created && <div className="space-y-2 border-b bg-success-soft/40 p-4"><CopyBox label={`Give ${created.name} these environment variables. The key is not shown again.`} value={envBlock(created.key, created.project)} multiline /><p className="text-[12.5px] text-muted-foreground">The agent then runs <code>hub handbook</code> to read the project rules and <code>hub inbox</code> to see what needs it.</p><button className="text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => setCreated(null)}>Done</button></div>}
        <ul className="divide-y">
          {(agents.data ?? []).map((a) => (
            <li key={a.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-[12.5px]">
              <Avatar name={a.name} size={28} />
              <div className="min-w-[180px] flex-1"><div className="flex items-center gap-2 text-[13px] font-medium">{a.name}{a.status !== "active" && <Badge tone="warning">{a.status}</Badge>}</div><div className="truncate text-muted-foreground">{[a.model, a.focus].filter(Boolean).join(" · ") || "no description"}</div></div>
              <span className="text-muted-foreground">{a.projects.join(", ") || "no projects"}</span>
              {hub.me.admin && a.owner !== hub.me.name && <span className="text-muted-foreground">owner {a.owner}</span>}
              <span className="w-24 text-muted-foreground">{a.last_seen ? ago(a.last_seen) : "never seen"}</span>
              <Button size="sm" variant="ghost" onClick={() => setOpen(a.name)}>Keys</Button>
              {a.status === "active" ? <ConfirmButton confirm="Disable agent" onConfirm={() => setStatus(a.name, "disabled")}>Disable</ConfirmButton> : <Button size="sm" variant="ghost" onClick={() => setStatus(a.name, "active")}>Enable</Button>}
            </li>
          ))}
          {agents.data && !agents.data.length && <li className="px-4 py-4 text-[12.5px] text-muted-foreground">No agents yet. Create one for each AI agent that should log runs or take part in a project.</li>}
        </ul>
      </Card>
      <Dialog open={creating} onOpenChange={setCreating} title="New agent" description="You own this agent and are responsible for what it does.">
        <form onSubmit={create} className="space-y-4">
          <FormError>{error}</FormError>
          <Field label="Name" hint="Lowercase letters, digits, - or _. Shown next to everything the agent does."><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} pattern="[a-z0-9][a-z0-9_-]{0,39}" placeholder="claude-vision" required autoFocus className="font-mono" /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Model (optional)"><Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="claude-opus-5" /></Field>
            <Field label="Focus (optional)"><Input value={form.focus} onChange={(e) => setForm({ ...form, focus: e.target.value })} placeholder="detector ablations" /></Field>
          </div>
          <Field label="Add to projects" hint={manageable.length ? "As a member: it can log runs, post, comment and chat. You can change this later in each project's settings." : "You are not a maintainer of any project yet; add the agent to a project later."}>
            <div className="flex flex-col gap-2 rounded-md border p-3">{manageable.map((p) => <Checkbox key={p.slug} checked={form.projects.includes(p.slug)} onChange={(v) => setForm({ ...form, projects: v ? [...form.projects, p.slug] : form.projects.filter((x) => x !== p.slug) })} label={p.title} />)}{!manageable.length && <span className="text-[12.5px] text-muted-foreground">No projects available.</span>}</div>
          </Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setCreating(false)}>Cancel</Button><Button type="submit" variant="primary">Create agent</Button></div>
        </form>
      </Dialog>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={`Keys for ${open}`} className="max-w-3xl p-0" >
        {open && <div className="[&>.card]:rounded-none [&>.card]:border-0 [&>.card]:shadow-none"><Keys participant={open} title="API keys" project={agents.data?.find((a) => a.name === open)?.projects[0]} /></div>}
      </Dialog>
    </>
  );
}

function Sessions() {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => get<{ id: string; created: string; last_seen: string; client: string; ip: string }[]>("/api/account/sessions") });
  const end = async (id: string) => { await api("DELETE", `/api/account/sessions/${id}`); qc.invalidateQueries({ queryKey: ["sessions"] }); qc.invalidateQueries({ queryKey: ["me"] }); };
  const browser = (ua: string) => (/Firefox/.test(ua) ? "Firefox" : /Edg\//.test(ua) ? "Edge" : /Chrome/.test(ua) ? "Chrome" : /Safari/.test(ua) ? "Safari" : ua.split("/")[0] || "Unknown") + (/Mac OS/.test(ua) ? " on macOS" : /Windows/.test(ua) ? " on Windows" : /Android/.test(ua) ? " on Android" : /iPhone|iPad/.test(ua) ? " on iOS" : /Linux/.test(ua) ? " on Linux" : "");
  return (
    <Card>
      <CardHeader title="Signed-in browsers" description="End a session you do not recognise, then change your password." />
      <ul className="divide-y">
        {(sessions.data ?? []).map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[12.5px]">
            <span className="min-w-[160px] flex-1 font-medium">{browser(s.client)}</span>
            <span className="font-mono text-muted-foreground">{s.ip}</span>
            <span className="w-32 text-muted-foreground">active {ago(s.last_seen)}</span>
            <ConfirmButton confirm="Sign out" onConfirm={() => end(s.id)}>End session</ConfirmButton>
          </li>
        ))}
      </ul>
    </Card>
  );
}
