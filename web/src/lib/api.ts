// JSON client for the hub API. The browser session is an HttpOnly cookie; writes carry the session's CSRF token.
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5000, retry: 1, refetchOnWindowFocus: false } } });

let csrf = "";
let project: string | null = null;
export const setCsrf = (t: string) => {
  csrf = t;
};
export const setProject = (p: string | null) => {
  project = p;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export async function api<T = unknown>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET") headers["X-Hub-CSRF"] = csrf;
  if (project) headers["X-Hub-Project"] = project;
  let url = path;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v != null && v !== "") qs.set(k, String(v));
    const s = qs.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const r = await fetch(url, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({ error: r.statusText }));
  if (r.status === 401 && !path.startsWith("/api/auth/")) queryClient.setQueryData(["me"], null); // session ended: back to sign-in
  if (!r.ok) throw new ApiError(r.status, data.error || r.statusText);
  return data as T;
}
export const get = <T = unknown>(path: string, query?: Query) => api<T>("GET", path, undefined, query);

// ---------------------------------------------------------------- types
export type Role = "viewer" | "member" | "maintainer" | "owner";
export const ROLES: Role[] = ["viewer", "member", "maintainer", "owner"];
export interface Project { slug: string; title: string; description: string; visibility: "private" | "internal"; settings: { strict?: boolean; default_category?: string }; runs: number; running: number; members: number; last_event: string | null; role: Role }
export interface Member { name: string; kind: "agent" | "human"; display: string; model: string; focus: string; owner: string; status: string; last_seen: string; role: Role; running: number }
export interface Me { name: string; kind: "agent" | "human"; display: string; email: string | null; admin: boolean; csrf?: string }
export interface AuthState { setup: boolean; signup: "invite" | "approval" | "open"; site_name: string; version: string }
export interface ApiKey { id: number; label: string; prefix: string; created_by: string; created: string; last_used: string; expires: string; revoked: string }
export interface Agent { name: string; model: string; focus: string; owner: string; status: string; created: string; last_seen: string; projects: string[] }
export interface Invite { id: number; email: string; project: string; role: Role; created_by: string; created: string; expires: string; used_by: string }
export interface User { name: string; kind: "agent" | "human"; display: string; email: string | null; admin: number; status: "active" | "pending" | "disabled"; owner: string; model: string; created: string; last_seen: string; projects: number }
export interface AuditEntry { id: number; ts: string; actor: string; action: string; target: string; detail: string; ip: string }
export interface Category { slug: string; title: string; description: string; runs: number }
export interface Topic { slug: string; title: string; description: string; created_by: string; posts: number; runs: number }
export interface RunRow {
  slug: string; project: string; title: string; owner: string; category: string; status: string; verdict: string | null; summary: string;
  branch: string; commit_sha: string; parent: string | null; dataset: string;
  created: string; started: string; ended: string; updated: string; open_comments: number; last_step: number | null;
}
export interface TableRow { slug: string; title: string; owner: string; category: string; status: string; verdict: string | null; summary: string; parent: string | null; dataset: string; updated: string; created: string; values: Record<string, number> }
export interface Artifact { id: number; step: number | null; epoch: number | null; sample: string; role: string; kind: string; name: string; caption: string; blob_sha: string; mime: string; created: string }
export interface Comment { id: number; target: string; author: string; author_kind?: string; kind: string; anchor: string; body: string; status: string; resolution_ref: string; parent_id: number | null; created: string; updated: string; owner?: string; replies?: Comment[]; self_note?: boolean; project?: string }
export interface Note { id: number; author: string; body: string; created: string }
export interface EvalStep { step: number; epoch: number | null; samples: number; wrong: number; layered: number }
export interface EvalSet { set: string; steps: EvalStep[] }
export interface Run extends RunRow {
  app: string; hypothesis: string; rationale: string; expected: string; conclusion: string; repo: string; config_path: string; config_sha: string; command: string;
  output_dataset: string; pinned: string[]; topics: string[];
  summary_metrics: { key: string; value: number; direction: string; parent_value?: number | null }[]; metric_keys: string[]; charts: number; model_graphs: { name: string; n_nodes: number; params: number }[]; artifacts: Artifact[];
  notes: Note[]; children: string[]; links: { src: string; dst: string; relation: string }[]; eval_sets: EvalSet[]; comments: Comment[];
}
export type ChartKind = "line" | "area" | "scatter" | "bar" | "pie" | "histogram" | "box" | "violin" | "heatmap" | "table";
export interface ChartSpec { kind: ChartKind; title: string; data: { columns: Record<string, (number | string | boolean | null)[]> }; encoding: Record<string, string>; options: Record<string, unknown>; rows: number }
export interface ChartInfo { name: string; kind: ChartKind; title: string; rows: number; steps: number[] }
export interface ChartData extends ChartSpec { name: string; step: number | null; steps: number[]; history?: (ChartSpec & { step: number })[] }
export interface SharedChart { name: string; kind: ChartKind; title: string; runs: string[] }
export interface GraphNode { id: string; kind: "input" | "module" | "op" | "loss"; name: string; type: string; group?: string; detail?: string; params?: number; in_shapes?: (number[] | null)[]; out_shape?: number[] | null; act_mean?: number | null; act_std?: number | null; grad_norm?: number | null; loss?: string; value?: number | null; dtype?: string }
export interface ModelGraphData { name: string; model: string; params: number; trainable?: number; nodes: GraphNode[]; edges: { from: string; to: string; shape?: number[] | null }[]; blocks?: Record<string, string> }
export type DesignKind = "box" | "group" | "text";
export interface DesignNode { id: string; kind: DesignKind; label: string; detail?: string; color?: string; group?: string; x: number; y: number; w: number; h: number }
export interface DesignEdge { from: string; to: string; label?: string; dashed?: boolean }
export interface DesignGraph { nodes: DesignNode[]; edges: DesignEdge[] }
export interface DesignRow { slug: string; title: string; description: string; owner: string; rev: number; created: string; updated: string; author: string; note: string; n_nodes: number; open_proposals: number; open_comments: number }
export interface DesignProposal { id: number; base_rev: number; author: string; note: string; status: string; created: string; decided_by: string }
export interface Design {
  slug: string; project: string; title: string; description: string; owner: string; rev: number; head: number; author: string; note: string; saved: string; created: string; updated: string;
  graph: DesignGraph; history: { rev: number; author: string; note: string; n_nodes: number; created: string }[]; proposals: DesignProposal[]; comments: Comment[];
  runs: { slug: string; title: string; owner: string; status: string; dst: string }[];
}
export type Series = [number, number][];
export type Metrics = Record<string, Series>;
export interface Post { slug: string; project?: string; topic: string; owner: string; kind: string; basis: string; title: string; body: string; revision: number; created: string; updated: string; comment_count?: number; refs: string[]; referenced_by?: string[]; citations?: { title: string; url: string; venue: string }[]; comments?: Comment[] }
export interface Message { id: number; channel: string; parent_id: number | null; author: string; author_kind?: string; body: string; created: string }
export interface Channel { slug: string; title: string; messages: number; last: string | null }
export interface Event { id: number; ts: string; project: string; actor: string; kind: string; ref: string; summary: string }
export interface Handbook { project: string; rev: number; text: string; author: string; note: string; created: string; history: { rev: number; author: string; note: string; created: string }[]; proposals: { id: number; base_rev: number; author: string; note: string; status: string; created: string; decided_by: string }[] }
export interface Claim { resource: string; owner: string; note: string; created: string; expires: string }
export interface Side { class?: string; value?: number; score?: number; boxes?: (number | string)[][]; text?: string }
export interface SampleRow { item: number; sample: string; epoch: number | null; truth: Side; pred: Side; class_true: string; class_pred: string; value_true: number | null; value_pred: number | null; score: number | null; outcome: string; error: number | null; metrics: Record<string, number>; layers: Record<string, string>; facts: Record<string, string>; vs_class_pred?: string; vs_outcome?: string }
export interface Facets { set: string; step: number; outcome: Record<string, number>; confusion: [string, string, number][]; class_true: [string, number, number][]; class_pred: [string, number, number][]; value_range: [number | null, number | null]; kinds: { boxes: boolean; text: boolean; value: boolean; layers: boolean }; box_classes: string[]; layers: Record<string, "mask" | "heatmap">; facts: Record<string, [string, number, number][]> }
export interface Review { class: string; severity: number | null; category: string; difficulty: string; bad_image: boolean; comment: string; reviewer: string; created: string; confirmed: boolean }
export interface ReviewOptions { categories: string[]; difficulties: string[]; label_class_fact: string; label_severity_fact: string }
export interface ReviewSummary { options: ReviewOptions; total: number; reviewed: number; bad: number; by: Record<"class" | "category" | "difficulty" | "reviewer", [string, number][]>; against: { agrees: number; false_call: number; miss: number }[] }
export interface DatasetRun { slug: string; title: string; owner: string; category: string; status: string; verdict: string | null; step: number; logged: string }
export interface EvalSetInfo { set: string; samples: number; runs: DatasetRun[] }
/** One run's call on a sample: outcome, predicted class, the chosen number, score. null when the run did not log it. */
export type Call = [string, string, number | null, number | null] | null;
export interface DatasetRow { item: number; sample: string; truth: Record<string, unknown> & { class?: string }; facts: Record<string, string>; runs: number; scored: number; wrong: number; missed: number; false_alarm: number; disagree: number; value_mean: number | null; value_sd: number | null; score_mean: number | null; classes: [string, number][]; review: Review | null; image?: string | null; calls?: Call[] }
export interface DatasetPage { set: string; value: string; values: string[]; negatives: string[]; runs: { slug: string; step: number; logged: string }[]; total: number; rows: DatasetRow[] }
export interface DatasetSummary { set: string; value: string; values: string[]; samples: number; reviews: ReviewSummary; runs: { slug: string; step: number; logged: string }[]; total: number; scored: number; presets: Record<string, number>; wrong_hist: number[]; class_true: [string, number, number][]; class_pred: string[]; facts: Record<string, [string, number, number][]>; by: string | null; groups: [string, number, number][]; agreement: (number | null)[][] }
export interface SampleDetail { sample: string; layer_kinds: Record<string, "mask" | "heatmap">; facts: Record<string, string>; truth: Side; meta: Record<string, unknown>; static_layers: Record<string, string>; steps: { step: number; epoch: number | null; truth: Side; pred: Side; outcome: string; error: number | null; metrics: Record<string, number>; layers: Record<string, string> }[] }
export interface Compare { runs: { slug: string; title: string; owner: string; status: string; verdict: string | null; parent: string | null; dataset: string; branch: string; commit_sha: string; category: string }[]; summary: Record<string, Record<string, number>>; directions: Record<string, string>; curves: Record<string, Record<string, Series>>; config_diff: Record<string, unknown>[] }

export const refHref = (ref: string, project: string): string => {
  const i = ref.indexOf(":");
  const kind = ref.slice(0, i), key = ref.slice(i + 1);
  const base = `/p/${encodeURIComponent(project)}`;
  if (kind === "run") return `${base}/runs/${key}`;
  if (kind === "sample") return `${base}/runs/${key.split("/")[0]}/samples`;
  if (kind === "post") return `${base}/post/${key}`;
  if (kind === "design") return `${base}/designs/${key.split("@")[0]}`;
  if (kind === "topic") return `${base}/research/${key}`;
  if (kind === "comment") return `${base}/feedback`;
  if (kind === "message") return `${base}/messages`;
  return base;
};
