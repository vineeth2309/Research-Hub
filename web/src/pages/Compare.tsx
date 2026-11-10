import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Chart } from "@/components/Chart";
import { Checkbox, Slider } from "@/components/ui/controls";
import { Table, Td, Th } from "@/components/ui/data";
import { Badge, Button, Card, Empty, Input, Section, Who, statusTone } from "@/components/ui/primitives";
import { get, type Compare as CompareT, type SharedChart } from "@/lib/api";
import { useHub } from "@/lib/state";
import { PALETTE, cn, fmt } from "@/lib/utils";
import { ChartCard } from "./Plots";

export default function Compare() {
  const hub = useHub();
  const { slugs = "" } = useParams();
  const list = slugs.split(",").filter(Boolean);
  const [smooth, setSmooth] = React.useState(0);
  const [logy, setLogy] = React.useState(false);
  const [q, setQ] = React.useState("val/");
  const res = useQuery({ queryKey: ["compare", slugs], enabled: list.length > 1, queryFn: () => get<CompareT>("/api/compare", { runs: slugs }) });
  const plots = useQuery({ queryKey: ["compare-charts", slugs], enabled: list.length > 1, queryFn: () => get<SharedChart[]>("/api/compare/charts", { runs: slugs }) });
  if (list.length < 2) return <Empty title="Pick two or more runs to compare">Tick runs in the <Link to={hub.href("runs")} className="text-primary">runs table</Link>.</Empty>;
  if (!res.data) return <p className="text-[13px] text-muted-foreground">Loading…</p>;
  const d = res.data;
  const color = Object.fromEntries(list.map((s, i) => [s, PALETTE[i % PALETTE.length]]));
  const keys = [...new Set(Object.values(d.summary).flatMap(Object.keys))].sort();
  const bestOf = (k: string) => { const vals = list.map((s) => d.summary[s]?.[k]).filter((v) => v != null) as number[]; if (!vals.length) return null; const dir = d.directions[k] || "max"; return dir === "min" ? Math.min(...vals) : dir === "none" ? null : Math.max(...vals); };
  const curveKeys = Object.keys(d.curves).filter((k) => !q || k.includes(q)).sort();
  const short = (s: string) => (s.length > 26 ? s.slice(0, 24) + "…" : s);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-semibold tracking-tight">Compare {list.length} runs</h1>
        <Link to={hub.href("runs")} className="ml-auto"><Button size="sm">Back to runs</Button></Link>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-[13px]">
        {d.runs.map((r) => <span key={r.slug} className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: color[r.slug] }} /><Link to={hub.href(`runs/${r.slug}`)} className="font-mono hover:text-primary">{r.slug}</Link><Badge tone={statusTone(r.status)} dot>{r.status}</Badge><Who name={r.owner} size={14} /></span>)}
      </div>
      <Section title="Summary" hint="best value per metric highlighted">
        <Card><Table dense><thead><tr><Th>metric</Th>{list.map((s) => <Th key={s} num><span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: color[s] }} />{short(s)}</span></Th>)}</tr></thead>
          <tbody>{keys.map((k) => { const best = bestOf(k); return <tr key={k}><Td mono>{k}</Td>{list.map((s) => { const v = d.summary[s]?.[k]; return <Td key={s} num className={cn(v != null && v === best && "bg-success-soft font-semibold text-success")}>{v == null ? <span className="text-muted-foreground">—</span> : fmt(v, 4)}</Td>; })}</tr>; })}
            {!keys.length && <tr><Td className="text-muted-foreground">No summary metrics on these runs.</Td></tr>}</tbody></Table></Card>
      </Section>
      <Section title="Config differences" hint={`${d.config_diff.length} key${d.config_diff.length === 1 ? "" : "s"} differ`}>
        {d.config_diff.length ? (
          <Card><Table dense><thead><tr><Th>key</Th>{list.map((s) => <Th key={s}>{short(s)}</Th>)}</tr></thead>
            <tbody>{d.config_diff.map((row) => <tr key={String(row.key)}><Td mono>{String(row.key)}</Td>{list.map((s) => <Td key={s} mono>{row[s] == null ? <span className="text-muted-foreground">—</span> : typeof row[s] === "object" ? JSON.stringify(row[s]) : String(row[s])}</Td>)}</tr>)}</tbody></Table></Card>
        ) : <p className="text-[13px] text-muted-foreground">The config snapshots are identical, or missing.</p>}
      </Section>
      <Section title="Curves" hint={`${Object.keys(d.curves).length} metrics in common`} actions={
        <div className="flex flex-wrap items-center gap-4 text-[12.5px]">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter keys" className="h-8 w-40" />
          <label className="flex items-center gap-2">smooth <Slider value={smooth * 100} onChange={(v) => setSmooth(v / 100)} max={90} className="w-24" label="Smoothing" /></label>
          <Checkbox checked={logy} onChange={setLogy} label="log y" />
        </div>}>
        {curveKeys.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{curveKeys.map((k) => <Chart key={k} title={k} smoothing={smooth} logy={logy} syncKey="cmp" series={list.filter((s) => d.curves[k][s]).map((s) => ({ name: s, data: d.curves[k][s], color: color[s] }))} />)}</div> : <p className="text-[13px] text-muted-foreground">No shared curves match.</p>}
      </Section>
      {(plots.data ?? []).length > 0 && (
        <Section title="Plots" hint="logged under the same name by two or more of these runs, each at its latest step">
          <div className="space-y-5">
            {plots.data!.map((p) => (
              <div key={p.name} className="space-y-2">
                <div className="font-mono text-[12.5px] font-semibold">{p.name}</div>
                <div className={cn("grid gap-3", p.runs.length > 2 ? "md:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-2")}>
                  {p.runs.map((s) => <ChartCard key={s} slug={s} info={p} label={<span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: color[s] }} />{s}</span>} />)}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
