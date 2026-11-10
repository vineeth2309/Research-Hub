// A project's members and roles, invite links, and its settings.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, UserPlus } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Select, Switch } from "@/components/ui/controls";
import { ConfirmButton, CopyBox, DeleteDialog, Field, FormError, PageHeader } from "@/components/ui/form";
import { toast } from "@/components/ui/overlays";
import { Avatar, Badge, Button, Card, CardHeader, Input, Tag, Textarea } from "@/components/ui/primitives";
import { ROLES, api, get, type Invite, type Role } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago } from "@/lib/utils";

const ROLE_HELP: Record<Role, string> = {
  viewer: "reads everything",
  member: "logs runs, posts, comments, chats",
  maintainer: "also edits the handbook, manages members, corrects any run",
  owner: "also changes visibility and other owners",
};
const inviteLink = (token: string) => `${window.location.origin}/#/signup?invite=${token}`;

export default function ProjectSettings() {
  const hub = useHub();
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader title="Members & settings" description={<>You are {hub.role === "owner" ? "an" : "a"} <b className="font-medium text-foreground">{hub.role}</b> of {hub.current?.title}: {hub.role && ROLE_HELP[hub.role]}.</>} />
      <Members />
      {hub.canModerate && <Invites />}
      <General />
      {hub.role === "owner" && hub.me.kind === "human" && <DangerZone />}
    </div>
  );
}

function Members() {
  const hub = useHub();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = React.useState("");
  const [role, setRole] = React.useState<Role>("member");
  const [error, setError] = React.useState("");
  const refresh = () => { qc.invalidateQueries({ queryKey: ["members"] }); qc.invalidateQueries({ queryKey: ["projects"] }); };
  const mine = ROLES.indexOf(hub.role ?? "viewer");
  const grantable = ROLES.filter((r) => ROLES.indexOf(r) <= mine);
  const set = async (who: string, r: string) => { try { await api("PUT", `/api/members/${who}`, { role: r }); refresh(); } catch (err) { toast((err as Error).message); } };
  const remove = async (who: string) => {
    try { await api("DELETE", `/api/members/${who}`); refresh(); if (who === hub.me.name && !hub.me.admin) navigate("/"); } catch (err) { toast((err as Error).message); }
  };
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try { await api("PUT", `/api/members/${name.trim()}`, { role }); setName(""); refresh(); toast("Added"); } catch (err) { setError((err as Error).message); }
  };
  const members = Object.values(hub.people).sort((a, b) => ROLES.indexOf(b.role) - ROLES.indexOf(a.role) || a.name.localeCompare(b.name));
  return (
    <Card>
      <CardHeader title={`Members · ${members.length}`} description="People and agents who can open this project." />
      <ul className="divide-y">
        {members.map((m) => {
          const editable = hub.canModerate && ROLES.indexOf(m.role) <= mine;
          const options = (m.kind === "agent" ? grantable.filter((r) => r === "viewer" || r === "member") : grantable).map((r) => ({ value: r, label: r, hint: ROLE_HELP[r] }));
          return (
            <li key={m.name} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3 text-[12.5px]">
              <Avatar name={m.name} human={m.kind === "human"} size={30} />
              <div className="min-w-[180px] flex-1">
                <div className="flex items-center gap-2 text-[13px] font-medium">{m.display || m.name}{m.kind === "agent" ? <Tag>agent</Tag> : <Tag className="text-human">person</Tag>}{m.status !== "active" && <Badge tone="warning">{m.status}</Badge>}{m.name === hub.me.name && <span className="font-normal text-muted-foreground">you</span>}</div>
                <div className="truncate text-muted-foreground">{m.kind === "agent" ? [`owned by ${m.owner}`, m.model, m.focus].filter(Boolean).join(" · ") : `@${m.name}`}</div>
              </div>
              <span className="w-24 text-muted-foreground">{m.last_seen ? ago(m.last_seen) : "never seen"}</span>
              {editable ? <Select size="sm" className="w-36" value={m.role} onChange={(r) => set(m.name, r)} options={options} /> : <span className="w-36 px-3 font-medium">{m.role}</span>}
              {editable || m.name === hub.me.name ? <ConfirmButton confirm={m.name === hub.me.name ? "Leave project" : "Remove"} onConfirm={() => remove(m.name)}>{m.name === hub.me.name ? "Leave" : "Remove"}</ConfirmButton> : <span className="w-[68px]" />}
            </li>
          );
        })}
      </ul>
      {hub.canModerate && (
        <form onSubmit={add} className="space-y-3 border-t bg-muted/30 p-4">
          <FormError>{error}</FormError>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Add someone who already has an account" className="min-w-[240px] flex-1"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="username or agent name" required className="font-mono" /></Field>
            <Field label="Role" className="w-40"><Select value={role} onChange={(r) => setRole(r as Role)} options={grantable.map((r) => ({ value: r, label: r, hint: ROLE_HELP[r] }))} /></Field>
            <Button type="submit"><UserPlus className="h-4 w-4" /> Add</Button>
          </div>
          <p className="text-[12px] text-muted-foreground">A person's username, or an agent's name. New agents are created under <Link to="/account" className="text-primary hover:underline">Account</Link>.</p>
        </form>
      )}
    </Card>
  );
}

function Invites() {
  const hub = useHub();
  const qc = useQueryClient();
  const invites = useQuery({ queryKey: ["invites", hub.project], queryFn: () => get<Invite[]>("/api/invites") });
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<Role>("member");
  const [link, setLink] = React.useState("");
  const mine = ROLES.indexOf(hub.role ?? "viewer");
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await api<{ token: string }>("POST", "/api/invites", { email: email.trim(), project: hub.project, role });
      setLink(inviteLink(res.token)); setEmail(""); qc.invalidateQueries({ queryKey: ["invites"] });
    } catch (err) { toast((err as Error).message); }
  };
  const revoke = async (id: number) => { await api("DELETE", `/api/invites/${id}`); qc.invalidateQueries({ queryKey: ["invites"] }); };
  const pending = (invites.data ?? []).filter((i) => !i.used_by && i.expires > new Date().toISOString());
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><Link2 className="h-4 w-4 text-muted-foreground" />Invite people</span>} description="Create a sign-up link that joins this project. Send it yourself: the hub does not send email." />
      <form onSubmit={create} className="flex flex-wrap items-end gap-3 p-4">
        <Field label="Email (optional: only this address can use the link)" className="min-w-[240px] flex-1"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="colleague@example.org" /></Field>
        <Field label="Role" className="w-40"><Select value={role} onChange={(r) => setRole(r as Role)} options={ROLES.filter((r) => ROLES.indexOf(r) <= mine && r !== "owner").map((r) => ({ value: r, label: r, hint: ROLE_HELP[r] }))} /></Field>
        <Button type="submit">Create link</Button>
      </form>
      {link && <div className="border-t bg-success-soft/40 p-4"><CopyBox label="Invite link, valid for 7 days and usable once. It is not shown again." value={link} /></div>}
      {pending.length > 0 && (
        <ul className="divide-y border-t">
          {pending.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[12.5px]">
              <span className="min-w-[180px] flex-1">{i.email || "anyone with the link"}</span>
              <span className="font-medium">{i.role}</span>
              <span className="text-muted-foreground">by {i.created_by} · expires {new Date(i.expires).toLocaleDateString()}</span>
              <ConfirmButton confirm="Revoke invite" onConfirm={() => revoke(i.id)}>Revoke</ConfirmButton>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function DangerZone() {
  const hub = useHub();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const p = hub.current!;
  const remove = async () => {
    await api("DELETE", `/api/projects/${encodeURIComponent(p.slug)}`, undefined, { confirm: p.slug });
    toast(`Deleted ${p.title}`);
    navigate("/");
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
  return (
    <Card className="border-danger/40">
      <CardHeader title={<span className="text-danger">Delete project</span>} description="Removes the project for every member. Only an owner can do this." actions={<Button variant="danger" size="sm" onClick={() => setOpen(true)}>Delete project…</Button>} />
      <DeleteDialog open={open} onOpenChange={setOpen} what="project" name={p.slug} onDelete={remove}>
        This removes <b className="font-semibold">{p.title}</b> and everything in it: {p.runs.toLocaleString()} run{p.runs === 1 ? "" : "s"} with their data, research notes, chat, the handbook, and the membership of {p.members} account{p.members === 1 ? "" : "s"}. The accounts themselves are kept.
      </DeleteDialog>
    </Card>
  );
}

function General() {
  const hub = useHub();
  const qc = useQueryClient();
  const p = hub.current!;
  const [title, setTitle] = React.useState(p.title);
  const [description, setDescription] = React.useState(p.description);
  const patch = async (data: Record<string, unknown>, done = "Saved") => {
    try { await api("PATCH", `/api/projects/${encodeURIComponent(p.slug)}`, data); qc.invalidateQueries({ queryKey: ["projects"] }); toast(done); } catch (err) { toast((err as Error).message); }
  };
  const ro = !hub.canModerate;
  return (
    <Card>
      <CardHeader title="Project" description={<>Slug <span className="font-mono text-foreground">{p.slug}</span> · scripts and agents select it with <code>HUB_PROJECT={p.slug}</code></>} />
      <div className="space-y-5 p-5">
        <form onSubmit={(e) => { e.preventDefault(); patch({ title, description }); }} className="space-y-4">
          <Field label="Name"><Input value={title} onChange={(e) => setTitle(e.target.value)} required disabled={ro} /></Field>
          <Field label="Description"><Textarea value={description} onChange={(e) => setDescription(e.target.value)} disabled={ro} className="min-h-[64px]" /></Field>
          {!ro && <Button type="submit" disabled={title === p.title && description === p.description}>Save</Button>}
        </form>
        <div className="space-y-3 border-t pt-5">
          <div className={ro ? "pointer-events-none opacity-60" : ""}><Switch checked={!!p.settings.strict} onChange={(v) => patch({ settings: { ...p.settings, strict: v } }, v ? "Research rules on" : "Research rules off")} label={<span><b className="font-medium">Research rules</b> <span className="text-muted-foreground">— every agent run states a summary, hypothesis, rationale, expected result, parent run, dataset and the git commit of its config. People can still log plain runs.</span></span>} /></div>
          <div className={hub.role !== "owner" ? "pointer-events-none opacity-60" : ""}><Switch checked={p.visibility === "internal"} onChange={(v) => patch({ visibility: v ? "internal" : "private" }, v ? "Visible to everyone signed in" : "Members only")} label={<span><b className="font-medium">Visible to everyone signed in</b> <span className="text-muted-foreground">— they can read but not write. Off: only members can see that this project exists. Only an owner changes this.</span></span>} /></div>
        </div>
      </div>
    </Card>
  );
}
