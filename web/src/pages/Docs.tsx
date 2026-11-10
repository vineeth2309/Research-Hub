// The guides from docs/*.md, built into the dashboard: pick a guide and section, or filter every section by text.
// Commands show this hub's address and the reader's project instead of placeholders.
import { Check, Copy, Search } from "lucide-react";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import { Link, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { Chip } from "@/components/ui/controls";
import { Card, Empty, Input } from "@/components/ui/primitives";
import { useHub } from "@/lib/state";
import { cn, pref } from "@/lib/utils";

const FILES = import.meta.glob("../../../docs/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
// order of the guides, and who each is mainly for
const GUIDES: [slug: string, audience: string][] = [["getting-started", "Start here"], ["logging", "Tracking"], ["agents", "Agents"], ["deploy", "Admins"], ["security", "Admins"]];
const AUDIENCES = [...new Set(GUIDES.map((g) => g[1]))];

interface Section { id: string; title: string; body: string }
interface Guide { slug: string; title: string; audience: string; sections: Section[] }

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function parse(slug: string, audience: string, text: string): Guide {
  const guide: Guide = { slug, title: slug, audience, sections: [] };
  let current: Section = { id: "overview", title: "Overview", body: "" }, fenced = false;
  for (const line of text.split("\n")) {
    if (line.trimStart().startsWith("```")) fenced = !fenced;
    if (!fenced && line.startsWith("# ")) { guide.title = line.slice(2).trim(); continue; }
    if (!fenced && line.startsWith("## ")) {
      if (current.body.trim()) guide.sections.push(current);
      current = { id: slugify(line.slice(3)), title: line.slice(3).trim(), body: "" };
      continue;
    }
    current.body += line + "\n";
  }
  if (current.body.trim()) guide.sections.push(current);
  return guide;
}

export default function Docs() {
  const hub = useHub();
  const navigate = useNavigate();
  const { guide: guideSlug = GUIDES[0][0], section } = useParams();
  const [q, setQ] = React.useState("");
  const [audience, setAudience] = React.useState("");
  const remembered = pref<string>("project", "");
  const project = hub.projects.find((p) => p.slug === remembered)?.slug ?? hub.projects[0]?.slug;
  const guides = React.useMemo(() => {
    const personal = (text: string) => { // this hub's address and the reader's project in place of the examples'
      const withUrl = text.replaceAll("https://hub.example.org", window.location.origin).replaceAll("http://localhost:6230", window.location.origin);
      return project ? withUrl.replaceAll("my-project", project) : withUrl;
    };
    return GUIDES.map(([slug, who]) => parse(slug, who, personal(FILES[`../../../docs/${slug}.md`] ?? "")));
  }, [project]);
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = guides.filter((g) => !audience || g.audience === audience);
  const hits = terms.length ? shown.flatMap((g) => g.sections.filter((s) => terms.every((t) => `${g.title} ${s.title} ${s.body}`.toLowerCase().includes(t))).map((s) => ({ guide: g, section: s }))) : [];
  const active = shown.find((g) => g.slug === guideSlug) ?? shown[0];
  React.useEffect(() => {
    if (section) document.getElementById(`doc-${section}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo({ top: 0 });
  }, [section, guideSlug]);
  const open = (g: string, s?: string) => { setQ(""); navigate(`/docs/${g}${s ? `/${s}` : ""}`); };
  return (
    <div className="grid gap-6 py-2 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className="space-y-3 lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:self-start lg:overflow-y-auto lg:pr-1">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => { setQ(e.target.value); window.scrollTo({ top: 0 }); }} placeholder="Filter the docs" className="h-9 pl-8" aria-label="Filter the docs" />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Chip active={!audience} onClick={() => setAudience("")}>All</Chip>
          {AUDIENCES.map((a) => <Chip key={a} active={audience === a} onClick={() => setAudience(audience === a ? "" : a)}>{a}</Chip>)}
        </div>
        <nav className="space-y-1" aria-label="Guides">
          {shown.map((g) => {
            const here = !terms.length && g === active;
            return (
              <div key={g.slug}>
                <button onClick={() => open(g.slug)} className={cn("flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] font-medium hover:bg-muted focus-ring", here ? "bg-accent text-accent-foreground hover:bg-accent" : "text-foreground")}>
                  <span className="truncate">{g.title}</span>
                  <span className="shrink-0 text-[11px] font-normal text-muted-foreground">{terms.length ? hits.filter((h) => h.guide === g).length || "" : g.audience}</span>
                </button>
                {here && (
                  <ul className="mb-2 ml-2.5 mt-1 space-y-0.5 border-l pl-2">
                    {g.sections.map((s) => <li key={s.id}><button onClick={() => open(g.slug, s.id)} className={cn("block w-full truncate rounded px-2 py-1 text-left text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground focus-ring", section === s.id && "font-medium text-foreground")}>{s.title}</button></li>)}
                  </ul>
                )}
              </div>
            );
          })}
        </nav>
        <p className="border-t pt-3 text-[11.5px] leading-relaxed text-muted-foreground">Commands use this hub's address{project ? <> and your project <span className="font-mono text-foreground">{project}</span></> : ""}, so they can be copied as they are.</p>
      </aside>
      <div className="min-w-0 max-w-[860px] space-y-4">
        {terms.length ? (
          <>
            <p className="text-[13px] text-muted-foreground">{hits.length} section{hits.length === 1 ? "" : "s"} mention <b className="font-medium text-foreground">{q.trim()}</b>{audience && ` in ${audience}`}</p>
            {hits.map(({ guide, section: s }) => <SectionCard key={guide.slug + s.id} section={s} label={<button className="text-primary hover:underline" onClick={() => open(guide.slug, s.id)}>{guide.title}</button>} />)}
            {!hits.length && <Empty title="Nothing matches">Try a shorter word, or clear the audience filter.</Empty>}
          </>
        ) : active ? (
          <>
            <div><div className="label">{active.audience}</div><h1 className="mt-1 text-[24px] font-semibold tracking-tight">{active.title}</h1></div>
            {active.sections.map((s) => <SectionCard key={s.id} section={s} />)}
          </>
        ) : <Empty title="No guide for that audience" />}
      </div>
    </div>
  );
}

function SectionCard({ section, label }: { section: Section; label?: React.ReactNode }) {
  const plain = section.id === "overview" && !label;
  return (
    <Card id={`doc-${section.id}`} className={cn("scroll-mt-20 p-5", plain && "border-0 bg-transparent p-0 shadow-none")}>
      {!plain && <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-[16px] font-semibold tracking-tight">{section.title}</h2>{label && <span className="text-[12px]">{label}</span>}</div>}
      <div className="prose-hub">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          a: ({ href = "", children }) => {
            const guide = /(?:^|\/)([a-z-]+)\.md$/.exec(href)?.[1]; // links between the guides stay inside the app
            if (guide) return <Link to={`/docs/${guide}`}>{children}</Link>;
            return /^https?:/.test(href) ? <a href={href} target="_blank" rel="noopener">{children}</a> : <span>{children}</span>;
          },
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
        }}>{section.body}</ReactMarkdown>
      </div>
    </Card>
  );
}

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const ref = React.useRef<HTMLPreElement>(null);
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(ref.current?.innerText ?? ""); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard needs HTTPS or localhost */ }
  };
  return (
    <div className="group relative">
      <pre ref={ref}>{children}</pre>
      <button onClick={copy} className="absolute right-2 top-2 rounded-md border bg-card p-1.5 text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 focus-ring" aria-label="Copy">{copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}</button>
    </div>
  );
}
