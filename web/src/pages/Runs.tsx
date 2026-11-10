import { useQuery } from "@tanstack/react-query";
import { Columns3, GitCompare, Search, X } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Checkbox, Chip, Segmented, Select } from "@/components/ui/controls";
import { Pager, Table, Td, Th } from "@/components/ui/data";
import { Popover } from "@/components/ui/overlays";
import { Badge, Button, Card, Empty, Input, Tag, Who, statusTone, verdictTone } from "@/components/ui/primitives";
import { get, type RunRow, type TableRow } from "@/lib/api";
import { useHub } from "@/lib/state";
import { ago, cn, fmt, pref, setPref, truncate } from "@/lib/utils";

const PAGE = 25;
const STATUSES = ["running", "planned", "finished", "failed", "abandoned"];
const LOWER_IS_BETTER = /loss|mae|error|fpr|false|miss|time|seconds|rate$/;

export default function Runs() {
  const hub = useHub();
  const navigate = useNavigate();
  const [mode, setMode] = React.useState<"table" | "list">(() => pref("runs.mode", "table"));
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [cols, setCols] = React.useState<string[]>(() => pref("runs.cols", []));
  const [sort, setSort] = React.useState<{ key: string; desc: boolean }>(() => pref("runs.sort", { key: "", desc: true }));
  const [page, setPage] = React.useState(0);
  const [sel, setSel] = React.useState<Set<string>>(new Set());
  const [colQ, setColQ] = React.useState("");
  React.useEffect(() => setPage(0), [q, status, category, mode]);
  const filters = { q: q.trim(), status, category };
  const list = useQuery({ queryKey: ["runs", hub.project, "list", filters, page], enabled: mode === "list", queryFn: () => get<{ runs: RunRow[]; total: number }>("/api/runs", { ...filters, limit: PAGE, offset: page * PAGE }) });
  const table = useQuery({ queryKey: ["runs", hub.project, "table", filters, cols, sort, page], enabled: mode === "table", queryFn: () => get<{ runs: TableRow[]; total: number; available: { key: string; n: number }[] }>("/api/runs/table", { ...filters, columns: cols.join(","), sort: sort.key, desc: sort.desc ? "1" : "0", limit: PAGE, offset: page * PAGE }) });
  const total = (mode === "table" ? table.data?.total : list.data?.total) ?? 0;
  const toggleCol = (k: string) => { const next = cols.includes(k) ? cols.filter((c) => c !== k) : [...cols, k].slice(0, 12); setCols(next); setPref("runs.cols", next); };
  const toggleSort = (key: string) => { const next = sort.key === key ? { key, desc: !sort.desc } : { key, desc: true }; setSort(next); setPref("runs.sort", next); };
  const best: Record<string, number> = {};
  for (const c of cols) { const vals = (table.data?.runs ?? []).map((r) => r.values[c]).filter((v) => v != null); if (vals.length) best[c] = LOWER_IS_BETTER.test(c) ? Math.min(...vals) : Math.max(...vals); }
  const active = [status && `status: ${status}`, category && `category: ${category}`].filter(Boolean) as string[];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold tracking-tight">Runs</h1>
        <span className="text-[13px] text-muted-foreground">{total.toLocaleString()}</span>
        <div className="ml-auto flex items-center gap-2">
          <Segmented value={mode} onChange={(m) => { setMode(m); setPref("runs.mode", m); }} options={[{ value: "table", label: "Table" }, { value: "list", label: "List" }]} />
          {mode === "table" && (
            <Popover align="end" className="w-96" trigger={<Button size="sm"><Columns3 className="h-3.5 w-3.5" /> Columns{cols.length ? ` · ${cols.length}` : ""}</Button>}>
              <Input value={colQ} onChange={(e) => setColQ(e.target.value)} placeholder={`Filter ${table.data?.available.length ?? 0} summary keys`} className="h-8" />
              <div className="mt-2 max-h-72 space-y-0.5 overflow-auto">
                {(table.data?.available ?? []).filter((k) => !colQ || k.key.includes(colQ)).slice(0, 150).map((k) => (
                  <Checkbox key={k.key} checked={cols.includes(k.key)} onChange={() => toggleCol(k.key)} className="w-full rounded px-1.5 py-1 hover:bg-muted" label={<span className="flex min-w-0 flex-1 items-center justify-between gap-2"><span className="truncate font-mono text-[12px]">{k.key}</span><span className="text-[11px] text-muted-foreground">{k.n}</span></span>} />
                ))}
              </div>
              {cols.length > 0 && <button className="mt-2 text-[12.5px] text-primary hover:underline" onClick={() => { setCols([]); setPref("runs.cols", []); }}>Clear columns</button>}
            </Popover>
          )}
          <Button size="sm" variant="primary" disabled={sel.size < 2} onClick={() => navigate(hub.href(`compare/${[...sel].join(",")}`))}><GitCompare className="h-3.5 w-3.5" /> Compare{sel.size ? ` ${sel.size}` : ""}</Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name or summary" className="h-8 pl-8" /></div>
        <Select value={category} onChange={setCategory} size="sm" className="w-48" placeholder="All categories" options={[{ value: "", label: "All categories" }, ...hub.cats.map((c) => ({ value: c.slug, label: c.title, hint: String(c.runs) }))]} />
        <div className="flex flex-wrap gap-1.5">{STATUSES.map((s) => <Chip key={s} active={status === s} onClick={() => setStatus(status === s ? "" : s)}>{s}</Chip>)}</div>
        {active.length > 0 && <button className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => { setStatus(""); setCategory(""); setQ(""); }}><X className="h-3.5 w-3.5" /> clear</button>}
      </div>

      <Card>
        {mode === "table" ? (
          <>
            <Table>
              <thead><tr>
                <Th className="w-8"><Checkbox checked={!!table.data?.runs.length && table.data.runs.every((r) => sel.has(r.slug))} onChange={(v) => setSel(new Set(v ? table.data!.runs.map((r) => r.slug) : []))} /></Th>
                <Th sort={sort.key === "slug" ? (sort.desc ? "desc" : "asc") : null} onSort={() => toggleSort("slug")}>Run</Th>
                <Th sort={sort.key === "status" ? (sort.desc ? "desc" : "asc") : null} onSort={() => toggleSort("status")}>Status</Th>
                <Th sort={sort.key === "owner" ? (sort.desc ? "desc" : "asc") : null} onSort={() => toggleSort("owner")}>Owner</Th>
                {cols.map((c) => <Th key={c} num sort={sort.key === c ? (sort.desc ? "desc" : "asc") : null} onSort={() => toggleSort(c)}><span title={c}>{c.replace(/^val\//, "")}</span></Th>)}
                <Th>Verdict</Th>
                <Th num sort={sort.key === "updated" ? (sort.desc ? "desc" : "asc") : null} onSort={() => toggleSort("updated")}>Updated</Th>
              </tr></thead>
              <tbody>
                {(table.data?.runs ?? []).map((r) => (
                  <tr key={r.slug} className={cn("hover:bg-muted/40", sel.has(r.slug) && "bg-accent/40")}>
                    <Td><Checkbox checked={sel.has(r.slug)} onChange={(v) => setSel((s) => { const n = new Set(s); v ? n.add(r.slug) : n.delete(r.slug); return n; })} /></Td>
                    <Td><Link to={hub.href(`runs/${r.slug}`)} className="font-mono text-[12.5px] font-medium hover:text-primary">{r.slug}</Link><div className="max-w-[40ch] truncate text-[12px] text-muted-foreground">{r.title !== r.slug ? r.title : r.summary}</div></Td>
                    <Td><Badge tone={statusTone(r.status)} dot>{r.status}</Badge></Td>
                    <Td><Who name={r.owner} size={16} /></Td>
                    {cols.map((c) => { const v = r.values[c]; return <Td key={c} num className={cn(v != null && v === best[c] && "bg-success-soft font-semibold text-success")}>{v == null ? <span className="text-muted-foreground">—</span> : fmt(v, 4)}</Td>; })}
                    <Td>{r.verdict && <Badge tone={verdictTone(r.verdict)}>{r.verdict}</Badge>}</Td>
                    <Td num className="text-muted-foreground">{ago(r.updated)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {table.data && !table.data.runs.length && <Empty title="No runs match" className="m-4" />}
            {!cols.length && table.data?.runs.length ? <p className="border-t px-4 py-2 text-[12px] text-muted-foreground">Add summary-metric columns with <b>Columns</b>; the best value in each column is highlighted, and tick runs to compare them.</p> : null}
          </>
        ) : (
          <ul className="divide-y">
            {(list.data?.runs ?? []).map((r) => (
              <li key={r.slug}>
                <Link to={hub.href(`runs/${r.slug}`)} className="block px-4 py-3 hover:bg-muted/40">
                  <div className="flex items-center justify-between gap-3"><span className="truncate font-mono text-[13px] font-medium">{r.slug}</span><Badge tone={statusTone(r.status)} dot>{r.status}</Badge></div>
                  <div className="mt-0.5 line-clamp-2 text-[12.5px] text-muted-foreground">{r.title !== r.slug ? r.title : r.summary}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground"><Who name={r.owner} size={14} /><Tag>{r.category}</Tag>{r.verdict && <Badge tone={verdictTone(r.verdict)}>{r.verdict}</Badge>}{r.dataset && <span className="font-mono">{truncate(r.dataset.split(",")[0], 36)}</span>}{r.open_comments > 0 && <Badge tone="human">{r.open_comments} open</Badge>}<span className="ml-auto">{r.last_step != null ? `step ${r.last_step.toLocaleString()} · ` : ""}{ago(r.updated)}</span></div>
                </Link>
              </li>
            ))}
            {list.data && !list.data.runs.length && <li><Empty title="No runs match" className="m-4" /></li>}
          </ul>
        )}
        <Pager page={page} total={total} size={PAGE} onPage={setPage} className="border-t" />
      </Card>
    </div>
  );
}
