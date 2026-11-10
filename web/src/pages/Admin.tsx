// Site administration: accounts, how people sign up, invites and the audit log.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Select, Tab, TabList, TabPanel, Tabs } from "@/components/ui/controls";
import { Pager, Table, Td, Th } from "@/components/ui/data";
import { ConfirmButton, CopyBox, Field, PageHeader } from "@/components/ui/form";
import { toast } from "@/components/ui/overlays";
import { Avatar, Badge, Button, Card, CardHeader, Empty, Input, Tag } from "@/components/ui/primitives";
import { api, get, type AuditEntry, type Invite, type User } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, when } from "@/lib/utils";

interface Settings { site_name: string; signup: string; create_projects: string }
const link = (path: string, token: string) => `${window.location.origin}/#/${path}=${token}`;

export default function Admin() {
  const hub = useHub();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => get<User[]>("/api/admin/users"), enabled: hub.me.admin });
  if (!hub.me.admin) return <Empty title="Site admins only">Ask an admin if you need an account approved or a password reset.</Empty>;
  const pending = (users.data ?? []).filter((u) => u.status === "pending").length;
  return (
    <div className="mx-auto max-w-5xl space-y-5 py-4">
      <PageHeader title="Site admin" description="Accounts on this hub, how new people join, and a record of security-relevant changes." />
      <Tabs defaultValue="users">
        <TabList><Tab value="users" count={pending || undefined}>Accounts</Tab><Tab value="access">Sign-up</Tab><Tab value="audit">Audit log</Tab></TabList>
        <TabPanel value="users" className="pt-5"><Users users={users.data ?? []} /></TabPanel>
        <TabPanel value="access" className="space-y-5 pt-5"><SignUp /><SiteInvites /></TabPanel>
        <TabPanel value="audit" className="pt-5"><Audit /></TabPanel>
      </Tabs>
    </div>
  );
}

function Users({ users }: { users: User[] }) {
  const hub = useHub();
  const qc = useQueryClient();
  const [q, setQ] = React.useState("");
  const [reset, setReset] = React.useState<{ name: string; url: string } | null>(null);
  const update = async (name: string, data: Record<string, unknown>) => { try { await api("PATCH", `/api/admin/users/${name}`, data); qc.invalidateQueries({ queryKey: ["admin-users"] }); } catch (err) { toast((err as Error).message); } };
  const resetLink = async (name: string) => { try { const r = await api<{ token: string }>("POST", `/api/admin/users/${name}/reset`); setReset({ name, url: link("reset?token", r.token) }); } catch (err) { toast((err as Error).message); } };
  const shown = users.filter((u) => !q || `${u.name} ${u.email ?? ""} ${u.display} ${u.owner}`.toLowerCase().includes(q.toLowerCase())).sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending"));
  return (
    <Card>
      <CardHeader title={`Accounts · ${users.length}`} actions={<Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name or email" className="h-8 w-60" aria-label="Filter accounts" />} />
      {reset && <div className="space-y-2 border-b bg-success-soft/40 p-4"><CopyBox label={`Send this link to ${reset.name}. It works once, for 24 hours.`} value={reset.url} /><button className="text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => setReset(null)}>Done</button></div>}
      <Table>
        <thead><tr><Th>Account</Th><Th>Status</Th><Th num>Projects</Th><Th>Last seen</Th><Th /></tr></thead>
        <tbody>
          {shown.map((u) => (
            <tr key={u.name} className="hover:bg-muted/40">
              <Td><div className="flex items-center gap-2.5"><Avatar name={u.name} human={u.kind === "human"} size={26} /><div className="min-w-0"><div className="flex items-center gap-1.5 font-medium">{u.display || u.name}{u.kind === "agent" && <Tag>agent</Tag>}{!!u.admin && <Badge tone="human">admin</Badge>}</div><div className="truncate text-[12px] text-muted-foreground">{u.kind === "agent" ? `owned by ${u.owner}${u.model ? ` · ${u.model}` : ""}` : `@${u.name} · ${u.email}`}</div></div></div></Td>
              <Td><Badge tone={u.status === "active" ? "success" : u.status === "pending" ? "warning" : "neutral"} dot>{u.status}</Badge></Td>
              <Td num>{u.projects}</Td>
              <Td className="whitespace-nowrap text-muted-foreground">{u.last_seen ? ago(u.last_seen) : "never"}</Td>
              <Td className="text-right">
                <div className="flex justify-end gap-1">
                  {u.status === "pending" && <Button size="sm" variant="primary" onClick={() => update(u.name, { status: "active" })}>Approve</Button>}
                  {u.status === "disabled" && <Button size="sm" onClick={() => update(u.name, { status: "active" })}>Enable</Button>}
                  {u.kind === "human" && u.status === "active" && <Button size="sm" variant="ghost" onClick={() => resetLink(u.name)}>Reset password</Button>}
                  {u.kind === "human" && u.status === "active" && u.name !== hub.me.name && <Button size="sm" variant="ghost" onClick={() => update(u.name, { admin: !u.admin })}>{u.admin ? "Remove admin" : "Make admin"}</Button>}
                  {u.status !== "disabled" && u.name !== hub.me.name && <ConfirmButton confirm="Disable account" onConfirm={() => update(u.name, { status: "disabled" })}>Disable</ConfirmButton>}
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

function SignUp() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: () => get<Settings>("/api/admin/settings") });
  const [name, setName] = React.useState<string | null>(null);
  const patch = async (data: Partial<Settings>) => { try { await api("PATCH", "/api/admin/settings", data); qc.invalidateQueries({ queryKey: ["admin-settings"] }); qc.invalidateQueries({ queryKey: ["auth-state"] }); toast("Saved"); } catch (err) { toast((err as Error).message); } };
  const s = settings.data;
  if (!s) return null;
  return (
    <Card>
      <CardHeader title="How people join" />
      <div className="grid gap-5 p-5 md:grid-cols-2">
        <Field label="New accounts" hint="Invite links always work, whichever option is chosen.">
          <Select value={s.signup} onChange={(v) => patch({ signup: v })} options={[{ value: "invite", label: "By invitation only" }, { value: "approval", label: "Anyone can ask; an admin approves" }, { value: "open", label: "Anyone can sign up" }]} />
        </Field>
        <Field label="Who can create projects">
          <Select value={s.create_projects} onChange={(v) => patch({ create_projects: v })} options={[{ value: "anyone", label: "Any signed-in person" }, { value: "admins", label: "Site admins only" }]} />
        </Field>
        <form onSubmit={(e) => { e.preventDefault(); if (name) patch({ site_name: name }); }} className="flex items-end gap-2 md:col-span-2">
          <Field label="Site name (shown on the sign-in page)" className="max-w-sm flex-1"><Input value={name ?? s.site_name} onChange={(e) => setName(e.target.value)} required /></Field>
          <Button type="submit" disabled={name == null || name === s.site_name}>Save</Button>
        </form>
      </div>
    </Card>
  );
}

function SiteInvites() {
  const qc = useQueryClient();
  const invites = useQuery({ queryKey: ["admin-invites"], queryFn: () => get<Invite[]>("/api/admin/invites") });
  const [email, setEmail] = React.useState("");
  const [url, setUrl] = React.useState("");
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try { const r = await api<{ token: string }>("POST", "/api/invites", { email: email.trim() }); setUrl(link("signup?invite", r.token)); setEmail(""); qc.invalidateQueries({ queryKey: ["admin-invites"] }); } catch (err) { toast((err as Error).message); }
  };
  const revoke = async (id: number) => { await api("DELETE", `/api/admin/invites/${id}`); qc.invalidateQueries({ queryKey: ["admin-invites"] }); };
  const now = new Date().toISOString();
  return (
    <Card>
      <CardHeader title="Invites" description="An invite made here creates an account without adding it to a project. Project maintainers invite people into their project from its settings." />
      <form onSubmit={create} className="flex flex-wrap items-end gap-3 p-4">
        <Field label="Email (optional: only this address can use the link)" className="min-w-[240px] flex-1"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="colleague@example.org" /></Field>
        <Button type="submit">Create link</Button>
      </form>
      {url && <div className="border-t bg-success-soft/40 p-4"><CopyBox label="Invite link, valid for 7 days and usable once. It is not shown again." value={url} /></div>}
      <ul className="divide-y border-t">
        {(invites.data ?? []).slice(0, 30).map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[12.5px]">
            <span className="min-w-[180px] flex-1">{i.email || "anyone with the link"}</span>
            <span className="text-muted-foreground">{i.project ? `${i.role} of ${i.project}` : "no project"} · by {i.created_by}</span>
            {i.used_by ? <Badge tone="success">used by {i.used_by}</Badge> : i.expires < now ? <Badge>expired</Badge> : <><Badge tone="warning">pending</Badge><ConfirmButton confirm="Revoke invite" onConfirm={() => revoke(i.id)}>Revoke</ConfirmButton></>}
          </li>
        ))}
        {invites.data && !invites.data.length && <li className="px-4 py-4 text-[12.5px] text-muted-foreground">No invites yet.</li>}
      </ul>
    </Card>
  );
}

function Audit() {
  const [page, setPage] = React.useState(0);
  const SIZE = 50;
  const log = useQuery({ queryKey: ["admin-audit", page], queryFn: () => get<{ total: number; entries: AuditEntry[] }>("/api/admin/audit", { limit: SIZE, offset: page * SIZE }) });
  return (
    <Card>
      <CardHeader title="Audit log" description="Sign-ins, failed sign-ins, keys, roles, invites and account changes. Newest first." />
      <Table dense>
        <thead><tr><Th>When</Th><Th>Who</Th><Th>Action</Th><Th>On</Th><Th>Detail</Th><Th>From</Th></tr></thead>
        <tbody>
          {(log.data?.entries ?? []).map((e) => (
            <tr key={e.id} className="hover:bg-muted/40">
              <Td className="whitespace-nowrap text-muted-foreground">{when(e.ts)}</Td>
              <Td className="font-medium">{e.actor || "—"}</Td>
              <Td><Badge tone={e.action.includes("failed") ? "danger" : /revoke|remove|disable|delete/.test(e.action) ? "warning" : "neutral"}>{e.action}</Badge></Td>
              <Td mono>{e.target}</Td>
              <Td className="max-w-[320px] truncate text-muted-foreground">{e.detail}</Td>
              <Td mono className="text-muted-foreground">{e.ip}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pager page={page} total={log.data?.total ?? 0} size={SIZE} onPage={setPage} />
    </Card>
  );
}
