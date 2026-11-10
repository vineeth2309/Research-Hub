// Shared app state: who is signed in, which project is open, and the members and categories of that project.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { ApiError, ROLES, api, get, queryClient, setCsrf, setProject, type Category, type Me, type Member, type Project, type Role } from "./api";
import { setPref } from "./utils";

interface Hub {
  me: Me;
  project: string;
  projects: Project[];
  current: Project | undefined;
  role: Role | undefined;
  /** member or above: may create runs, posts, comments and messages */
  canWrite: boolean;
  /** maintainer or owner: may edit the handbook, manage members and correct other people's work */
  canModerate: boolean;
  people: Record<string, Member>;
  cats: Category[];
  signOut: () => Promise<void>;
  theme: "light" | "dark";
  setTheme: (t: "light" | "dark") => void;
  href: (path: string) => string;
}
const Ctx = React.createContext<Hub | null>(null);
export const useHub = () => {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useHub outside provider");
  return v;
};

/** The signed-in account, or null. Also remembers the session's CSRF token for writes. */
export function useSession() {
  return useQuery({
    queryKey: ["me"],
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      try {
        const me = await get<Me>("/api/whoami");
        setCsrf(me.csrf ?? "");
        return me;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
  });
}

export function useTheme() {
  const [theme, setThemeState] = React.useState<"light" | "dark">(() => (document.documentElement.classList.contains("dark") ? "dark" : "light"));
  const setTheme = (t: "light" | "dark") => {
    setThemeState(t);
    document.documentElement.classList.toggle("dark", t === "dark");
    try { localStorage.setItem("hub.theme", t); } catch { /* private mode */ }
  };
  return [theme, setTheme] as const;
}

export function HubProvider({ children }: { children: React.ReactNode }) {
  const { project = "" } = useParams();
  const location = useLocation();
  const qc = useQueryClient();
  const session = useSession();
  const me = session.data;
  setProject(project || null);
  const [theme, setTheme] = useTheme();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => get<Project[]>("/api/projects"), refetchInterval: 30000, enabled: !!me });
  const current = projects.data?.find((p) => p.slug === project);
  const members = useQuery({ queryKey: ["members", project], queryFn: () => get<Member[]>("/api/members"), enabled: !!current, refetchInterval: 30000 });
  const cats = useQuery({ queryKey: ["categories", project], queryFn: () => get<Category[]>("/api/categories"), enabled: !!current });
  React.useEffect(() => {
    if (current) setPref("project", project);
  }, [current, project]);

  const value = React.useMemo<Hub | null>(() => {
    if (!me) return null;
    const rank = current ? ROLES.indexOf(current.role) : -1;
    return {
      me, project, projects: projects.data ?? [], current, role: current?.role, canWrite: rank >= 1, canModerate: rank >= 2,
      people: Object.fromEntries((members.data ?? []).map((p) => [p.name, p])), cats: cats.data ?? [],
      async signOut() {
        await api("POST", "/api/auth/logout").catch(() => undefined);
        qc.clear();
        queryClient.setQueryData(["me"], null);
      },
      theme, setTheme,
      href: (path) => `/p/${encodeURIComponent(project)}/${path}`,
    };
  }, [me, project, projects.data, current, members.data, cats.data, theme, qc]);

  if (session.isLoading) return <Splash />;
  if (!value) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (project && projects.data && !current) return <Navigate to="/" replace />; // no such project, or no access to it
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function Splash() {
  return <div className="grid min-h-screen place-items-center"><div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-primary" /></div>;
}

/** Re-fetch everything when the hub records new events in this project (lightweight polling). */
export function useLiveRefresh() {
  const qc = useQueryClient();
  const { current } = useHub();
  const slug = current?.slug;
  const last = React.useRef(0);
  React.useEffect(() => {
    if (!slug) return;
    last.current = 0;
    const tick = async () => {
      try {
        const ev = await get<{ id: number }[]>("/api/events", { since: last.current, limit: 1 });
        if (ev.length && last.current && ev[0].id !== last.current) qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
        if (ev.length) last.current = ev[0].id;
      } catch { /* offline */ }
    };
    tick();
    const t = setInterval(tick, 10000);
    return () => clearInterval(t);
  }, [slug, qc]);
}
