// The app frame: project switcher, navigation, search and the account menu.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronsUpDown, FlaskConical, Home, Inbox, LifeBuoy, Lock, MessageSquare, Plus, Search, Settings, SquareStack, Users, Workflow } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Logo } from "@/pages/Auth";
import { api, get, refHref, type Handbook } from "@/lib/api";
import { useHub, useLiveRefresh } from "@/lib/state";
import { cn } from "@/lib/utils";
import { Switch } from "./ui/controls";
import { Field, FormError } from "./ui/form";
import { Avatar, Button, Input, Kbd, Tag, Textarea } from "./ui/primitives";
import { Dialog, Menu, Toaster, toast } from "./ui/overlays";

const NAV = [
  { to: "home", label: "Home", icon: Home },
  { to: "runs", label: "Runs", icon: SquareStack },
  { to: "research", label: "Research", icon: FlaskConical },
  { to: "designs", label: "Designs", icon: Workflow },
  { to: "messages", label: "Messages", icon: MessageSquare },
  { to: "feedback", label: "Feedback", icon: Inbox },
  { to: "handbook", label: "Handbook", icon: BookOpen },
  { to: "settings", label: "Members & settings", icon: Users },
];
const navClass = ({ isActive }: { isActive: boolean }) => cn("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground", isActive && "bg-accent text-accent-foreground hover:bg-accent");

export function Shell() {
  const hub = useHub();
  useLiveRefresh();
  const navigate = useNavigate();
  const [creating, setCreating] = React.useState(false);
  const todo = useQuery({
    queryKey: ["todo", hub.project, hub.me.name],
    enabled: !!hub.current,
    queryFn: async () => {
      const open = await get<{ total: number }>("/api/comments", { status: "open", from: "human", to: hub.me.kind === "human" ? "" : hub.me.name });
      const proposals = hub.canModerate ? (await get<Handbook>("/api/handbook").catch(() => null))?.proposals.filter((p) => p.status === "open").length ?? 0 : 0;
      return open.total + proposals;
    },
  });
  const toggleTheme = () => hub.setTheme(hub.theme === "dark" ? "light" : "dark");
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r bg-card/60 md:flex">
        <div className="px-3 pt-3">
          <Menu
            align="start"
            trigger={
              <button className="flex w-full items-center gap-2.5 rounded-md border bg-card px-2.5 py-2 text-left shadow-card hover:bg-muted focus-ring">
                {hub.current ? <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary text-[12px] font-bold text-primary-foreground">{hub.current.title.slice(0, 1).toUpperCase()}</span> : <Logo className="h-7 w-7 shrink-0" />}
                <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-semibold">{hub.current?.title ?? "Research Hub"}</span><span className="block truncate text-[11px] text-muted-foreground">{hub.current ? `${hub.current.runs} runs · ${hub.current.running} running` : "choose a project"}</span></span>
                <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
              </button>
            }
            items={[
              ...hub.projects.map((p) => ({ label: <span className="flex items-center gap-1.5">{p.title}{p.visibility === "private" && <Lock className="h-3 w-3 text-muted-foreground" />}</span>, hint: `${p.runs} runs · you are ${p.role === "owner" ? "an" : "a"} ${p.role}`, active: p.slug === hub.project, onSelect: () => navigate(`/p/${encodeURIComponent(p.slug)}/home`) })),
              { separator: true },
              { label: "All projects", onSelect: () => navigate("/") },
              ...(hub.me.kind === "human" ? [{ label: <span className="flex items-center gap-1.5"><Plus className="h-3.5 w-3.5" /> New project</span>, onSelect: () => setCreating(true) }] : []),
            ]}
          />
        </div>
        {hub.current && (
          <nav className="mt-3 flex flex-col gap-0.5 px-2">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={hub.href(to)} className={navClass}>
                <Icon className="h-4 w-4" />
                <span className="flex-1">{label}</span>
                {to === "feedback" && !!todo.data && <span className="rounded-full bg-human px-1.5 text-[11px] font-semibold text-white">{todo.data}</span>}
              </NavLink>
            ))}
          </nav>
        )}
        <div className="mt-auto border-t p-2">
          <NavLink to="/docs" className={navClass}><LifeBuoy className="h-4 w-4" />Docs</NavLink>
          {hub.me.admin && <NavLink to="/admin" className={navClass}><Settings className="h-4 w-4" />Site admin</NavLink>}
          <Menu
            align="start"
            trigger={<button className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted focus-ring"><Avatar name={hub.me.name} human={hub.me.kind === "human"} size={28} /><span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{hub.me.display || hub.me.name}</span><span className="block truncate text-[11px] text-muted-foreground">{hub.me.email ?? hub.me.kind}</span></span><ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground" /></button>}
            items={[
              { label: "Account, API keys and agents", onSelect: () => navigate("/account") },
              { label: hub.theme === "dark" ? "Light theme" : "Dark theme", onSelect: toggleTheme },
              { separator: true },
              { label: "Sign out", onSelect: () => void hub.signOut() },
            ]}
          />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur md:px-6">
          <nav className="flex min-w-0 shrink gap-1 overflow-x-auto md:hidden">
            {hub.current ? NAV.map(({ to, label }) => <NavLink key={to} to={hub.href(to)} className={({ isActive }) => cn("whitespace-nowrap rounded-md px-2 py-1 text-[12.5px] font-medium text-muted-foreground", isActive && "bg-accent text-accent-foreground")}>{label.split(" ")[0]}</NavLink>) : <Link to="/" className="flex items-center gap-2 text-[13px] font-semibold"><Logo className="h-6 w-6" />Research Hub</Link>}
          </nav>
          {hub.current && <SearchBox />}
          <div className="ml-auto flex items-center gap-2">
            {hub.current?.settings.strict && <Tag className="hidden md:inline-flex">research rules</Tag>}
            {hub.role === "viewer" && <Tag className="hidden md:inline-flex">read only</Tag>}
            <Link to="/docs" className="text-[12.5px] font-medium text-muted-foreground hover:text-foreground md:hidden">Docs</Link>
            <Link to="/account" className="md:hidden" aria-label="Account"><Avatar name={hub.me.name} human={hub.me.kind === "human"} size={28} /></Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">
          <Outlet />
        </main>
      </div>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
      <Toaster />
    </div>
  );
}

function SearchBox() {
  const hub = useHub();
  const [q, setQ] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLInputElement>(null);
  const results = useQuery({ queryKey: ["search", hub.project, q], enabled: q.trim().length >= 2, queryFn: () => get<{ ref: string; kind: string; title: string; snippet: string }[]>("/api/search", { q }) });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "/" && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) { e.preventDefault(); ref.current?.focus(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input ref={ref} value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} placeholder="Search runs, posts, messages" className="h-8 bg-muted/60 pl-8 pr-10" aria-label="Search" />
      <span className="absolute right-2 top-1/2 -translate-y-1/2"><Kbd>/</Kbd></span>
      {open && q.trim().length >= 2 && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-[60vh] overflow-auto rounded-lg border bg-popover p-1 shadow-pop">
          {(results.data ?? []).map((r) => (
            <Link key={r.ref} to={r.ref.startsWith("handbook") ? hub.href("handbook") : refHref(r.ref, hub.project)} className="block rounded-md px-2.5 py-2 hover:bg-muted" onClick={() => { setOpen(false); setQ(""); }}>
              <div className="flex items-center gap-2 text-[13px]"><Tag>{r.kind}</Tag><span className="truncate font-medium">{r.title}</span></div>
              <div className="truncate text-[12px] text-muted-foreground">{r.snippet}</div>
            </Link>
          ))}
          {results.data && !results.data.length && <div className="px-2.5 py-2 text-[12.5px] text-muted-foreground">No matches.</div>}
        </div>
      )}
    </div>
  );
}

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = React.useState({ title: "", slug: "", description: "", strict: false, internal: false });
  const [error, setError] = React.useState("");
  const slug = form.slug || form.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api("POST", "/api/projects", { slug, title: form.title.trim(), description: form.description.trim(), settings: { strict: form.strict }, visibility: form.internal ? "internal" : "private" });
      await qc.invalidateQueries({ queryKey: ["projects"] });
      onOpenChange(false);
      toast("Project created");
      navigate(`/p/${encodeURIComponent(slug)}/home`);
    } catch (err) { setError((err as Error).message); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New project" description="A project has its own runs, research notes, chat, handbook and members.">
      <form onSubmit={submit} className="space-y-4">
        <FormError>{error}</FormError>
        <Field label="Name"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Object detectors" required autoFocus /></Field>
        <Field label="Slug" hint="Used in links and as HUB_PROJECT. Cannot be changed later."><Input value={slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} pattern="[a-z0-9][a-z0-9._-]{0,99}" required className="font-mono" /></Field>
        <Field label="Description (optional)"><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="min-h-[56px]" /></Field>
        <div className="space-y-2.5 rounded-md border p-3">
          <Switch checked={form.strict} onChange={(v) => setForm({ ...form, strict: v })} label={<span><b className="font-medium">Research rules</b> <span className="text-muted-foreground">— agent runs must state a hypothesis, a parent run and git provenance</span></span>} />
          <Switch checked={form.internal} onChange={(v) => setForm({ ...form, internal: v })} label={<span><b className="font-medium">Visible to everyone signed in</b> <span className="text-muted-foreground">— otherwise members only</span></span>} />
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" variant="primary">Create project</Button></div>
      </form>
    </Dialog>
  );
}
