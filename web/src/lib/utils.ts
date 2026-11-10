import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const PALETTE = ["#4f46e5", "#ea580c", "#0f766e", "#a21caf", "#b45309", "#0e7490", "#4d7c0f", "#be123c", "#1d4ed8", "#9333ea"];

export function hashColor(name: string): string {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function fmt(v: number | null | undefined, digits = 3): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 100) return v.toFixed(1);
  if (v === 0) return "0";
  return Number(v.toPrecision(digits)).toString();
}

export function ago(ts: string | null | undefined): string {
  if (!ts) return "";
  const d = (Date.now() - new Date(ts).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  if (d < 86400 * 14) return `${Math.round(d / 86400)}d ago`;
  return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function when(ts: string | null | undefined): string {
  return ts ? new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
}

export function duration(start?: string, end?: string): string {
  if (!start) return "";
  const h = ((end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()) / 3600000;
  return h >= 48 ? `${Math.round(h / 24)}d` : h >= 1 ? `${h.toFixed(1)}h` : `${Math.round(h * 60)}m`;
}

export const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

export function pref<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem("hub." + key);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
export function setPref(key: string, value: unknown) {
  try {
    localStorage.setItem("hub." + key, JSON.stringify(value));
  } catch {
    /* private mode */
  }
}
