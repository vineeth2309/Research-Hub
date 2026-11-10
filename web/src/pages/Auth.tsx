// Sign in, sign up (with or without an invite), first-run setup and password reset.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Bot, ShieldCheck } from "lucide-react";
import * as React from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Field, FormError } from "@/components/ui/form";
import { Button, Input } from "@/components/ui/primitives";
import { api, get, setCsrf, type AuthState } from "@/lib/api";
import { Splash, useSession } from "@/lib/state";

type Mode = "login" | "signup" | "setup" | "reset";
const TITLES: Record<Mode, [string, string]> = {
  login: ["Sign in", "Welcome back."],
  signup: ["Create your account", "Join your team's hub."],
  setup: ["Set up this hub", "Create the first admin account."],
  reset: ["Choose a new password", "This link works once."],
};

export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path d="M8 21l5-7 4 4 7-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24" cy="9" r="2.2" fill="#fff" />
    </svg>
  );
}

export default function Auth({ mode }: { mode: Mode }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const session = useSession();
  const state = useQuery({ queryKey: ["auth-state"], queryFn: () => get<AuthState>("/api/auth/state") });
  const inviteToken = params.get("invite") ?? "";
  const invite = useQuery({ queryKey: ["invite", inviteToken], enabled: mode === "signup" && !!inviteToken, retry: false, queryFn: () => get<{ email: string; project: string; role: string }>("/api/auth/invite", { token: inviteToken }) });
  const [form, setForm] = React.useState({ name: "", display: "", email: "", password: "" });
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { if (invite.data?.email) setForm((f) => ({ ...f, email: invite.data.email })); }, [invite.data]);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const next = params.get("next") || "/";

  if (session.isLoading || state.isLoading) return <Splash />;
  if (session.data) return <Navigate to={next} replace />;
  if (state.data?.setup && mode !== "setup") return <Navigate to={`/setup${params.get("code") ? `?code=${params.get("code")}` : ""}`} replace />;
  if (!state.data?.setup && mode === "setup") return <Navigate to="/login" replace />;

  const finish = async (res: { csrf?: string }) => {
    setCsrf(res.csrf ?? "");
    await qc.invalidateQueries({ queryKey: ["me"] });
    navigate(next, { replace: true });
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await finish(await api("POST", "/api/auth/login", { email: form.email, password: form.password }));
      else if (mode === "setup") await finish(await api("POST", "/api/auth/setup", { ...form, code: params.get("code") ?? "" }));
      else if (mode === "signup") {
        const res = await api<{ status: string; csrf?: string }>("POST", "/api/auth/signup", { ...form, invite: inviteToken || undefined });
        if (res.status === "active") await finish(res);
        else setNotice("Your account is waiting for an admin's approval. You can sign in once it is approved.");
      } else {
        await api("POST", "/api/auth/reset", { token: params.get("token") ?? "", password: form.password });
        setNotice("Password changed. You can sign in now.");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const [title, subtitle] = TITLES[mode];
  const closed = mode === "signup" && state.data?.signup === "invite" && !inviteToken;
  const newAccount = mode === "signup" || mode === "setup";

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-[hsl(243_45%_14%)] p-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-[hsl(243_80%_60%)] opacity-30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-[hsl(190_80%_50%)] opacity-20 blur-3xl" />
        <div className="relative flex items-center gap-3 text-[15px] font-semibold"><Logo />{state.data?.site_name ?? "Research Hub"}</div>
        <div className="relative mt-auto max-w-md space-y-8">
          <h2 className="text-[30px] font-semibold leading-tight tracking-tight">Where people and AI agents run experiments together.</h2>
          <ul className="space-y-5 text-[14px] text-white/80">
            {([[Activity, "Track every run", "Metrics, configs, images, masks, boxes and text, sample by sample."], [Bot, "Agents are teammates", "Each agent has its own account, follows the project handbook and answers review comments."], [ShieldCheck, "You stay in charge", "Roles per project, scoped API keys, and an audit log of every change."]] as const).map(([Icon, head, body]) => (
              <li key={head} className="flex gap-3.5"><span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/10"><Icon className="h-4 w-4" /></span><span><span className="block font-medium text-white">{head}</span>{body}</span></li>
            ))}
          </ul>
        </div>
      </aside>
      <main className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-[380px]">
          <div className="mb-8 flex items-center gap-2.5 text-[14px] font-semibold lg:hidden"><Logo className="h-7 w-7" />{state.data?.site_name ?? "Research Hub"}</div>
          <h1 className="text-[24px] font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-[13.5px] text-muted-foreground">{invite.data?.project ? `You were invited to ${invite.data.project} as a ${invite.data.role}.` : subtitle}</p>
          {notice ? (
            <div className="mt-6 space-y-4"><div className="rounded-md border border-success/30 bg-success-soft px-3 py-2.5 text-[13px] text-success">{notice}</div><Link to="/login" className="text-[13px] font-medium text-primary hover:underline">Go to sign in</Link></div>
          ) : closed ? (
            <div className="mt-6 space-y-4 text-[13.5px]"><p>This hub is invitation-only. Ask an admin or a project maintainer for an invite link.</p><Link to="/login" className="font-medium text-primary hover:underline">Back to sign in</Link></div>
          ) : (
            <form onSubmit={submit} className="mt-7 space-y-4">
              <FormError>{error || (invite.error as Error | null)?.message}</FormError>
              {mode === "setup" && !params.get("code") && <FormError>Open the setup link printed in the terminal where the hub runs; it carries a one-time code.</FormError>}
              {newAccount && <Field label="Username" hint="Lowercase letters, digits, - or _. Shown next to everything you do."><Input value={form.name} onChange={set("name")} autoComplete="username" required pattern="[a-z0-9][a-z0-9_-]{0,39}" autoFocus placeholder="ada" /></Field>}
              {newAccount && <Field label="Full name (optional)"><Input value={form.display} onChange={set("display")} autoComplete="name" placeholder="Ada Lovelace" /></Field>}
              {mode !== "reset" && <Field label="Email"><Input type={mode === "login" ? "text" : "email"} value={form.email} onChange={set("email")} autoComplete="email" required autoFocus={mode === "login"} readOnly={!!invite.data?.email} placeholder="you@example.org" /></Field>}
              <Field label={mode === "reset" ? "New password" : "Password"} hint={mode !== "login" ? "At least 10 characters." : undefined}><Input type="password" value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "login" ? undefined : 10} autoFocus={mode === "reset"} /></Field>
              <Button type="submit" variant="primary" className="h-10 w-full" disabled={busy}>{busy ? "Working…" : mode === "login" ? "Sign in" : mode === "reset" ? "Set password" : "Create account"}</Button>
              {mode === "login" && <p className="text-[12.5px] text-muted-foreground">Forgot your password? An admin can send you a reset link.{state.data?.signup !== "invite" && <> New here? <Link to="/signup" className="font-medium text-primary hover:underline">Create an account</Link>.</>}</p>}
              {mode === "signup" && <p className="text-[12.5px] text-muted-foreground">Already have an account? <Link to="/login" className="font-medium text-primary hover:underline">Sign in</Link>.</p>}
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
