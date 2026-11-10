import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import { refHref } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "./primitives";

export function Pager({ page, total, size, onPage, className }: { page: number; total: number; size: number; onPage: (p: number) => void; className?: string }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages === 1 && page === 0) return null;
  const from = page * size + 1, to = Math.min(total, (page + 1) * size);
  return (
    <div className={cn("flex items-center justify-between gap-3 px-4 py-2.5 text-[12.5px] text-muted-foreground", className)}>
      <span>{total ? `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}` : "0"}</span>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="ghost" disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="px-1 font-mono">{page + 1} / {pages}</span>
        <Button size="icon" variant="ghost" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

/** Markdown with run:/post: references and @mentions turned into links. */
export function Markdown({ text, project, className, clamp }: { text: string; project: string; className?: string; clamp?: boolean }) {
  const prepared = React.useMemo(
    () => text.replace(/(^|[\s(])((?:run|post):[A-Za-z0-9._-]+)/g, (_m, p, r) => `${p}[${r}](#${refHref(r, project)})`),
    [text, project],
  );
  return (
    <div className={cn("prose-hub", clamp && "line-clamp-[12]", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        a: ({ href, children }) => href && href.startsWith("#/") ? <Link to={href.slice(1)} className="mono rounded border px-1 py-0.5 no-underline hover:border-primary">{children}</Link> : <a href={href} target="_blank" rel="noopener">{children}</a>,
      }}>{prepared}</ReactMarkdown>
    </div>
  );
}

/** Long prose collapsed to a few lines with a "Show more" control. */
export function Expandable({ text, project, lines = 6 }: { text: string; project: string; lines?: number }) {
  const [open, setOpen] = React.useState(false);
  const long = text.length > 420 || text.split("\n").length > lines;
  return (
    <div>
      <div className={cn("relative", !open && long && "max-h-[9.5rem] overflow-hidden")}>
        <Markdown text={text} project={project} />
        {!open && long && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-card to-transparent" />}
      </div>
      {long && <button type="button" className="mt-1 text-[12.5px] font-medium text-primary hover:underline" onClick={() => setOpen((o) => !o)}>{open ? "Show less" : "Show more"}</button>}
    </div>
  );
}

export function Table({ children, className, dense }: { children: React.ReactNode; className?: string; dense?: boolean }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className={cn("w-full border-collapse text-[13px] tabular-nums", dense && "text-[12.5px]")}>{children}</table>
    </div>
  );
}
export function Th({ children, className, num, sort, onSort }: { children?: React.ReactNode; className?: string; num?: boolean; sort?: "asc" | "desc" | null; onSort?: () => void }) {
  const inner = onSort ? <button type="button" onClick={onSort} className={cn("inline-flex items-center gap-1 hover:text-foreground", sort && "text-foreground")}>{children}{sort && <span className="text-[10px]">{sort === "desc" ? "▼" : "▲"}</span>}</button> : children;
  return <th className={cn("sticky top-0 z-[1] whitespace-nowrap border-b bg-muted/60 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[.06em] text-muted-foreground backdrop-blur", num && "text-right", className)}>{inner}</th>;
}
export function Td({ children, className, num, mono }: { children?: React.ReactNode; className?: string; num?: boolean; mono?: boolean }) {
  return <td className={cn("border-b px-3 py-2 align-top", num && "text-right", (num || mono) && "font-mono text-[12.5px]", className)}>{children}</td>;
}

export function Facts({ items, className }: { items: [React.ReactNode, React.ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[12.5px]", className)}>
      {items.filter(([, v]) => v !== "" && v != null).map(([k, v], i) => (
        <React.Fragment key={i}>
          <dt className="pt-px text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words font-mono text-[12px]">{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}
