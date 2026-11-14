// A person's review of one sample of an eval set: class, severity 0 to 10, category, difficulty, bad image, comment.
// A review is about the sample, not about a run, so it counts for every run on the set.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";
import { Checkbox, Select, Slider } from "@/components/ui/controls";
import { toast } from "@/components/ui/overlays";
import { Button, Textarea, type Tone } from "@/components/ui/primitives";
import { api, get, type Call, type DatasetPage, type DatasetRow, type Review, type ReviewOptions } from "@/lib/api";
import { ago, cn, fmt, when } from "@/lib/utils";

const UNSURE = "unsure"; // a category that leaves the sample out of scoring
const num = (v: unknown) => (typeof v === "number" ? v : v != null && v !== "" && !Number.isNaN(Number(v)) ? Number(v) : null);

/** The label a sample carries: the set's truth, or the facts the project names for it (for samples without truth). */
export function labelOf(row: DatasetRow, o: ReviewOptions): { class: string; severity: number | null; source: string } | null {
  const cls = row.truth.class ?? (o.label_class_fact ? row.facts[o.label_class_fact] : undefined);
  const severity = num(row.truth.severity) ?? num(row.truth.value) ?? (o.label_severity_fact ? num(row.facts[o.label_severity_fact]) : null);
  return cls || severity != null ? { class: cls ?? "", severity, source: row.truth.class ? "set label" : "project label" } : null;
}

/** How a run's call stands against a review: agrees, false call (rejects what was found fine), miss (passes a defect). */
export function againstReview(review: Review | null | undefined, call: Call, negatives: string[]): "agrees" | "false call" | "miss" | "" {
  if (!review || review.bad_image || !review.class || review.category === UNSURE || !call) return "";
  const fine = negatives.includes(review.class.toLowerCase()), passed = !!call[1] && negatives.includes(call[1].toLowerCase());
  return fine === passed ? "agrees" : fine ? "false call" : "miss";
}

export function reviewBadge(review: Review, o: ReviewOptions): { text: string; tone: Tone } {
  if (review.bad_image) return { text: "bad image", tone: "neutral" };
  const text = [review.class || review.category, review.severity != null ? fmt(review.severity, 2) : ""].filter(Boolean).join(" · ") || "commented";
  const i = o.categories.indexOf(review.category);
  return { text, tone: review.category === UNSURE ? "neutral" : i === 0 ? "danger" : i === 1 ? "warning" : "primary" };
}

type Form = { cls: string; severity: string; category: string; difficulty: string; bad: boolean; comment: string };
const toForm = (r: Review | null | undefined): Form => ({ cls: r?.class ?? "", severity: r?.severity != null ? String(r.severity) : "", category: r?.category ?? "", difficulty: r?.difficulty ?? "", bad: !!r?.bad_image, comment: r?.comment ?? "" });

function Choice({ values, value, offset, onChange, label }: { values: string[]; value: string; offset: number; onChange: (v: string) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${values.length}, minmax(0, 1fr))` }}>
      {values.map((v, i) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(value === v ? "" : v)}
          className={cn("rounded-md border px-1.5 py-1 text-center text-[12px] font-medium capitalize transition-colors focus-ring", value === v ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted")}>
          {v}<kbd className={cn("block font-mono text-[10px] font-normal normal-case", value === v ? "text-primary-foreground/80" : "text-muted-foreground")}>{offset + i + 1}</kbd>
        </button>
      ))}
    </div>
  );
}

export function ReviewPanel({ set, row, page, review, options, classes, onSaved, onMove, canNext, atStart }: {
  set: string; row: DatasetRow; page: DatasetPage; review: Review | null; options: ReviewOptions; classes: string[];
  onSaved: (r: Review | null) => void; onMove: (delta: number) => void; canNext: boolean; atStart: boolean;
}) {
  const qc = useQueryClient();
  const [form, setForm] = React.useState<Form>(() => toForm(review));
  const [saved, setSaved] = React.useState<Form>(() => toForm(review));
  const [current, setCurrent] = React.useState<Review | null>(review);
  const [busy, setBusy] = React.useState(false);
  const comment = React.useRef<HTMLTextAreaElement>(null);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const label = labelOf(row, options);
  const history = useQuery({ queryKey: ["review-history", set, row.sample], queryFn: () => get<{ reviews: Review[] }>("/api/eval-sets/reviews", { set, sample: row.sample, history: 1 }) });
  const set1 = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  const save = React.useCallback(async (f: Form, confirmed = false) => {
    setBusy(true);
    try {
      const calls = row.calls ?? [];
      const shown = { label: label && { class: label.class, severity: label.severity, source: label.source }, number: page.value,
        runs: page.runs.map((r, i) => calls[i] && { slug: r.slug, class: calls[i]![1], value: calls[i]![2] }).filter(Boolean).slice(0, 64) };
      const res = await api<{ review: Review | null }>("POST", "/api/eval-sets/review", { set, sample: row.sample, class: f.cls, severity: f.severity === "" ? null : Number(f.severity),
        category: f.category, difficulty: f.difficulty, bad_image: f.bad, comment: f.comment, confirmed, shown });
      setForm(toForm(res.review)); setSaved(toForm(res.review)); setCurrent(res.review); onSaved(res.review);
      qc.invalidateQueries({ queryKey: ["review-history", set, row.sample] });
      toast(res.review ? "Review saved" : "Review cleared");
      return true;
    } catch (e) { toast((e as Error).message); return false; } finally { setBusy(false); }
  }, [row, page, label, set, onSaved, qc]);

  const move = async (delta: number) => { if (!dirty || (await save(form))) onMove(delta); };
  const confirm = async () => {
    if (!label) return toast("This sample has no label to confirm");
    if (await save({ ...form, cls: label.class, severity: label.severity != null ? String(label.severity) : "" }, true) && canNext) onMove(1);
  };

  const all = [...options.categories, ...options.difficulties];
  const keyed = useLatest({ form, dirty, move, confirm, save });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = keyed.current, el = e.target as HTMLElement;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); void k.save(k.form); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "ArrowRight") void k.move(1);
      else if (e.key === "ArrowLeft") void k.move(-1);
      else if (e.key === "y") void k.confirm();
      else if (e.key === "s") void k.save(k.form);
      else if (e.key === "b") set1({ bad: !k.form.bad });
      else if (e.key === "c") { e.preventDefault(); comment.current?.focus(); }
      else if (/^[1-9]$/.test(e.key) && +e.key <= all.length) {
        const v = all[+e.key - 1], isCategory = +e.key <= options.categories.length, field = isCategory ? "category" : "difficulty";
        set1({ [field]: k.form[field] === v ? "" : v } as Partial<Form>);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [all.join("|"), options.categories.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const earlier = (history.data?.reviews ?? []).slice(0, -1).reverse().slice(0, 6);
  const classOptions = [{ value: "", label: "—" }, ...[...new Set([...classes, form.cls].filter(Boolean))].sort().map((c) => ({ value: c, label: c }))];
  return (
    <div className="space-y-3 rounded-md border border-primary/30 bg-accent/30 p-3">
      <div className="text-[13px] font-semibold">Your review <span className="font-normal text-muted-foreground">· kept with the sample, counts for every run</span></div>
      <div className="space-y-1"><div className="label">category</div><Choice label="Category" values={options.categories} value={form.category} offset={0} onChange={(v) => set1({ category: v })} /></div>
      <div className="space-y-1"><div className="label">difficulty</div><Choice label="Difficulty" values={options.difficulties} value={form.difficulty} offset={options.categories.length} onChange={(v) => set1({ difficulty: v })} /></div>
      <div className="grid grid-cols-[1fr_1fr] gap-3">
        <div className="space-y-1"><div className="label">class</div><Select size="sm" value={form.cls} onChange={(v) => set1({ cls: v })} options={classOptions} placeholder="—" /></div>
        <div className="space-y-1"><div className="label">severity 0 to 10</div>
          <div className="flex items-center gap-2"><input type="number" min={0} max={10} step={0.1} value={form.severity} onChange={(e) => set1({ severity: e.target.value })} aria-label="Severity" className="h-8 w-16 rounded-md border border-input bg-card px-2 text-[13px] focus-ring" />
            <Slider value={Number(form.severity || 0) * 10} onChange={(v) => set1({ severity: String(v / 10) })} max={100} label="Severity" /></div></div>
      </div>
      <Checkbox checked={form.bad} onChange={(v) => set1({ bad: v })} label={<span>Bad image <kbd className="font-mono text-[10px] text-muted-foreground">b</kbd> <span className="text-muted-foreground">· leave this sample out of scoring and training lists</span></span>} />
      <Textarea ref={comment} value={form.comment} onChange={(e) => set1({ comment: e.target.value })} placeholder="Comment (c)" rows={2} className="text-[12.5px]" />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={busy || !label} onClick={() => void confirm()} title={label ? `Save the label as your review (${label.class || "no class"}${label.severity != null ? `, severity ${label.severity}` : ""}) and go to the next sample` : "This sample has no label"}>Label is right <kbd className="ml-1 font-mono text-[10px] opacity-80">y</kbd></Button>
        <Button size="sm" disabled={busy || !dirty} onClick={() => void save(form)}>Save <kbd className="ml-1 font-mono text-[10px] text-muted-foreground">s</kbd></Button>
        {current && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save(toForm(null))}>Clear review</Button>}
        <span className="inline-flex"><Button size="icon" variant="ghost" disabled={busy || atStart} onClick={() => void move(-1)} aria-label="Previous sample"><ChevronLeft className="h-4 w-4" /></Button><Button size="icon" variant="ghost" disabled={busy || !canNext} onClick={() => void move(1)} aria-label="Next sample"><ChevronRight className="h-4 w-4" /></Button></span>
        <span className="ml-auto text-[11.5px] text-muted-foreground">{dirty ? "Not saved · ← → saves and moves on" : current ? `Saved · ${current.reviewer} · ${ago(current.created)}${current.confirmed ? " · label confirmed" : ""}` : "No review yet · ← → move"}</span>
      </div>
      {label && <div className="text-[11.5px] text-muted-foreground">{label.source}: <b className="font-medium text-foreground">{label.class || "no class"}</b>{label.severity != null && <>, severity <b className="font-medium text-foreground">{fmt(label.severity, 2)}</b></>}</div>}
      {earlier.length > 0 && (
        <div className="space-y-1 border-t pt-2 text-[11.5px] text-muted-foreground">
          <div className="label">earlier reviews</div>
          {earlier.map((r) => <div key={r.created} title={when(r.created)}><b className="font-medium text-foreground">{r.reviewer}</b> · {ago(r.created)} · {[r.class, r.severity != null ? `severity ${fmt(r.severity, 2)}` : "", r.category, r.difficulty, r.bad_image ? "bad image" : ""].filter(Boolean).join(", ") || "cleared"}{r.comment && <> · “{r.comment}”</>}</div>)}
        </div>
      )}
    </div>
  );
}

/** A ref that always holds the latest value, for handlers registered once. */
function useLatest<T>(value: T) {
  const ref = React.useRef(value);
  ref.current = value;
  return ref;
}
