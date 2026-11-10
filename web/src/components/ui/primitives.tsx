import * as React from "react";
import { cn, hashColor } from "@/lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "link"; size?: "sm" | "md" | "icon" };
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "secondary", size = "md", ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors focus-ring disabled:pointer-events-none disabled:opacity-50",
      size === "sm" ? "h-8 px-2.5 text-[12.5px]" : size === "icon" ? "h-8 w-8" : "h-9 px-3.5 text-[13px]",
      variant === "primary" && "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm",
      variant === "secondary" && "border bg-card text-foreground hover:bg-muted shadow-sm",
      variant === "ghost" && "text-foreground hover:bg-muted",
      variant === "danger" && "bg-danger text-white hover:bg-danger/90",
      variant === "link" && "h-auto px-0 text-primary hover:underline",
      className,
    )}
    {...props}
  />
));
Button.displayName = "Button";

const TONES = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-accent text-accent-foreground",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  human: "bg-human-soft text-human",
} as const;
export type Tone = keyof typeof TONES;
export function Badge({ tone = "neutral", dot, className, children }: { tone?: Tone; dot?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11.5px] font-medium leading-5 whitespace-nowrap", TONES[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
export const statusTone = (s: string): Tone => (s === "running" ? "primary" : s === "finished" ? "success" : s === "failed" ? "danger" : "warning");
export const verdictTone = (v: string): Tone => (v === "supports" ? "success" : v === "refutes" ? "danger" : "warning");
export const outcomeTone = (o: string): Tone => (o === "correct" ? "success" : o === "unscored" ? "neutral" : "danger");
export const OUTCOME_LABEL: Record<string, string> = { missed: "missed", false_alarm: "false alarm", wrong_class: "wrong class", mismatch: "mismatch", correct: "correct", unscored: "unscored" };

export function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-md border bg-card px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground", className)}>{children}</span>;
}

export function Card({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props}>{children}</div>;
}
export function CardHeader({ title, description, actions, className }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3 sm:flex-nowrap", className)}>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold tracking-tight">{title}</div>
        {description && <div className="mt-0.5 text-[12.5px] text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
export function Section({ title, hint, actions, children, className }: { title: React.ReactNode; hint?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
          {hint && <span className="text-[12px] text-muted-foreground">{hint}</span>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn("h-9 w-full rounded-md border border-input bg-card px-3 text-[13px] placeholder:text-muted-foreground focus-ring", className)} {...props} />
));
Input.displayName = "Input";
export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn("min-h-[72px] w-full rounded-md border border-input bg-card px-3 py-2 text-[13px] placeholder:text-muted-foreground focus-ring", className)} {...props} />
));
Textarea.displayName = "Textarea";

export function Avatar({ name, size = 24, human }: { name: string; size?: number; human?: boolean }) {
  return (
    <span
      className="inline-grid shrink-0 place-items-center rounded-full font-semibold text-white"
      style={{ width: size, height: size, fontSize: size * 0.4, background: human ? "hsl(var(--human))" : hashColor(name) }}
      aria-hidden="true"
    >
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}
export function Who({ name, human, size = 18 }: { name: string; human?: boolean; size?: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      <Avatar name={name} size={size} human={human} />
      {name}
    </span>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border bg-muted px-1.5 font-mono text-[11px] text-muted-foreground">{children}</kbd>;
}
export function Empty({ title, children, className }: { title: string; children?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-dashed px-6 py-10 text-center", className)}>
      <div className="text-[13.5px] font-medium">{title}</div>
      {children && <div className="mt-1 text-[12.5px] text-muted-foreground">{children}</div>}
    </div>
  );
}
export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} style={style} />;
}
export function Spinner() {
  return <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-primary" />;
}
export function Stat({ label, value, delta, tone }: { label: string; value: React.ReactNode; delta?: React.ReactNode; tone?: "good" | "bad" | "neutral" }) {
  return (
    <div className="card min-w-0 px-4 py-3">
      <div className="truncate text-[12px] text-muted-foreground" title={label}>{label}</div>
      <div className="mt-0.5 font-mono text-[22px] font-medium tracking-tight">{value}</div>
      {delta && <div className={cn("font-mono text-[12px]", tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : "text-muted-foreground")}>{delta}</div>}
    </div>
  );
}
