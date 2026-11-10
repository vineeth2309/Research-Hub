// Form pieces shared by sign-in and the settings pages.
import { Check, Copy } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Dialog, toast } from "./overlays";
import { Button, Input } from "./primitives";

export function Field({ label, hint, children, className }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="block text-[12.5px] font-medium">{label}</span>
      {children}
      {hint && <span className="block text-[12px] leading-snug text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function FormError({ children }: { children?: React.ReactNode }) {
  return children ? <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{children}</div> : null;
}

/** A secret or link shown once, with a copy button. */
export function CopyBox({ value, label, multiline }: { value: string; label?: string; multiline?: boolean }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast("Copy failed; select the text and copy it by hand");
    }
  };
  return (
    <div className="space-y-1.5">
      {label && <div className="text-[12.5px] font-medium">{label}</div>}
      <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-2">
        <pre className={cn("min-w-0 flex-1 select-all overflow-x-auto px-1 py-1 font-mono text-[12px] leading-relaxed", !multiline && "whitespace-nowrap")}>{value}</pre>
        <Button type="button" size="sm" onClick={copy} aria-label="Copy">{copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy"}</Button>
      </div>
    </div>
  );
}

/** A destructive action that asks once more before running. */
export function ConfirmButton({ children, confirm, onConfirm, className }: { children: React.ReactNode; confirm: string; onConfirm: () => void; className?: string }) {
  const [armed, setArmed] = React.useState(false);
  React.useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return armed
    ? <Button size="sm" variant="danger" className={className} onClick={() => { setArmed(false); onConfirm(); }}>{confirm}</Button>
    : <Button size="sm" variant="ghost" className={cn("text-muted-foreground hover:text-danger", className)} onClick={() => setArmed(true)}>{children}</Button>;
}

export function PageHeader({ title, description, actions }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Permanent deletion: explains what goes, and stays disabled until the thing's name is typed back. */
export function DeleteDialog({ open, onOpenChange, what, name, children, onDelete }: { open: boolean; onOpenChange: (o: boolean) => void; what: string; name: string; children: React.ReactNode; onDelete: () => Promise<void> }) {
  const [typed, setTyped] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { if (open) { setTyped(""); setError(""); } }, [open]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { await onDelete(); onOpenChange(false); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={`Delete this ${what}?`}>
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-md border border-danger/40 bg-danger-soft/50 p-3 text-[13px]">{children} <b className="font-semibold">This cannot be undone.</b></div>
        <FormError>{error}</FormError>
        <Field label={<>Type <span className="select-all font-mono text-foreground">{name}</span> to confirm</>}>
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus autoComplete="off" spellCheck={false} className="font-mono" aria-label={`Type ${name} to confirm`} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" variant="danger" disabled={typed !== name || busy}>Delete {what}</Button>
        </div>
      </form>
    </Dialog>
  );
}
