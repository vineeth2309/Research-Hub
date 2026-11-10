import * as SelectPrimitive from "@radix-ui/react-select";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, ChevronDown, Search } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Select({ value, onChange, options, placeholder, className, size = "md" }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: React.ReactNode; hint?: string }[]; placeholder?: string; className?: string; size?: "sm" | "md";
}) {
  // Radix refuses an empty-string item value; map "" to a sentinel.
  const EMPTY = "__all__";
  return (
    <SelectPrimitive.Root value={value || EMPTY} onValueChange={(v) => onChange(v === EMPTY ? "" : v)}>
      <SelectPrimitive.Trigger className={cn("inline-flex w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-left text-[13px] focus-ring data-[placeholder]:text-muted-foreground", size === "sm" ? "h-8" : "h-9", className)}>
        <span className="truncate"><SelectPrimitive.Value placeholder={placeholder} /></span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={4} className="z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border bg-popover p-1 shadow-pop">
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item key={o.value || EMPTY} value={o.value || EMPTY} className="relative flex cursor-default select-none items-center gap-2 rounded-sm py-1.5 pl-7 pr-2 text-[13px] outline-none data-[highlighted]:bg-muted">
                <SelectPrimitive.ItemIndicator className="absolute left-2"><Check className="h-3.5 w-3.5" /></SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                {o.hint && <span className="ml-auto pl-3 font-mono text-[11px] text-muted-foreground">{o.hint}</span>}
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

export const Tabs = TabsPrimitive.Root;
export function TabList({ children, className }: { children: React.ReactNode; className?: string }) {
  return <TabsPrimitive.List className={cn("flex gap-1 overflow-x-auto border-b", className)}>{children}</TabsPrimitive.List>;
}
export function Tab({ value, children, count }: { value: string; children: React.ReactNode; count?: React.ReactNode }) {
  return (
    <TabsPrimitive.Trigger value={value} className="-mb-px inline-flex h-10 items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground focus-ring">
      {children}
      {count != null && count !== 0 && <span className="rounded-full bg-muted px-1.5 font-mono text-[11px] text-muted-foreground">{count}</span>}
    </TabsPrimitive.Trigger>
  );
}
export const TabPanel = TabsPrimitive.Content;

export function Checkbox({ checked, onChange, label, className }: { checked: boolean; onChange: (v: boolean) => void; label?: React.ReactNode; className?: string }) {
  return (
    <label className={cn("inline-flex cursor-pointer select-none items-center gap-2 text-[13px]", className)}>
      <CheckboxPrimitive.Root checked={checked} onCheckedChange={(v) => onChange(v === true)} className="grid h-4 w-4 place-items-center rounded border border-input bg-card data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground focus-ring">
        <CheckboxPrimitive.Indicator><Check className="h-3 w-3" /></CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      {label}
    </label>
  );
}

export function Slider({ value, onChange, min = 0, max = 100, step = 1, className, label }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; className?: string; label?: string }) {
  return (
    <SliderPrimitive.Root value={[value]} onValueChange={([v]) => onChange(v)} min={min} max={max} step={step} aria-label={label} className={cn("relative flex h-5 w-full touch-none select-none items-center", className)}>
      <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
        <SliderPrimitive.Range className="absolute h-full bg-primary" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full border-2 border-primary bg-card shadow focus-ring" />
    </SliderPrimitive.Root>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer select-none items-start gap-3 text-[13px]">
      <SwitchPrimitive.Root checked={checked} onCheckedChange={onChange} className="relative h-5 w-9 shrink-0 rounded-full bg-input transition-colors data-[state=checked]:bg-primary focus-ring">
        <SwitchPrimitive.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
      </SwitchPrimitive.Root>
      {label}
    </label>
  );
}

export function Segmented<T extends string>({ value, onChange, options, className, size = "md" }: { value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode; disabled?: boolean }[]; className?: string; size?: "sm" | "md" }) {
  return (
    <ToggleGroupPrimitive.Root type="single" value={value} onValueChange={(v) => v && onChange(v as T)} className={cn("inline-flex rounded-md border bg-card p-0.5", className)}>
      {options.map((o) => (
        <ToggleGroupPrimitive.Item key={o.value} value={o.value} disabled={o.disabled} className={cn("rounded-[6px] px-2.5 font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=on]:bg-muted data-[state=on]:text-foreground disabled:opacity-40 focus-ring", size === "sm" ? "h-6 text-[12px]" : "h-7 text-[12.5px]")}>
          {o.label}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}

export function Chip({ active, onClick, children, className }: { active?: boolean; onClick?: () => void; children: React.ReactNode; className?: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={cn("inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors focus-ring", active ? "border-foreground bg-foreground text-background" : "bg-card text-muted-foreground hover:bg-muted hover:text-foreground", className)}>
      {children}
    </button>
  );
}

/** One filter: a pill that opens a searchable list of values with counts. Several values are OR-ed. */
export function FacetFilter({ label, values, selected, onChange }: { label: string; values: [string, number, number?][]; selected: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = React.useState("");
  const shown = values.filter((v) => !q || v[0].toLowerCase().includes(q.toLowerCase()));
  const toggle = (v: string) => onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  return (
    <PopoverPrimitive.Root onOpenChange={(o) => !o && setQ("")}>
      <PopoverPrimitive.Trigger asChild>
        <button type="button" className={cn("inline-flex h-7 max-w-[280px] items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors focus-ring", selected.length ? "border-primary/40 bg-accent text-accent-foreground" : "bg-card text-muted-foreground hover:bg-muted hover:text-foreground")}>
          <span className="truncate">{label}{selected.length ? `: ${selected[0]}` : ""}</span>
          {selected.length > 1 && <span className="rounded-full bg-primary px-1.5 text-[10.5px] text-primary-foreground">+{selected.length - 1}</span>}
          <ChevronDown className="h-3 w-3 shrink-0" />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content align="start" sideOffset={6} className="z-50 w-72 rounded-lg border bg-popover shadow-pop focus:outline-none">
          {values.length > 8 && (
            <div className="relative border-b p-2">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${values.length} values`} autoFocus className="h-8 w-full rounded-md bg-muted/60 pl-8 pr-2 text-[12.5px] outline-none placeholder:text-muted-foreground" aria-label={`Search ${label}`} />
            </div>
          )}
          <ul className="max-h-72 overflow-y-auto p-1">
            {shown.slice(0, 200).map(([v, n, wrong]) => (
              <li key={v}>
                <button type="button" onClick={() => toggle(v)} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-muted">
                  <span className={cn("grid h-4 w-4 shrink-0 place-items-center rounded border border-input", selected.includes(v) && "border-primary bg-primary text-primary-foreground")}>{selected.includes(v) && <Check className="h-3 w-3" />}</span>
                  <span className="min-w-0 flex-1 truncate">{v}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">{n.toLocaleString()}</span>
                  {!!wrong && <span className="w-9 text-right font-mono text-[11px] text-danger">{wrong.toLocaleString()}</span>}
                </button>
              </li>
            ))}
            {!shown.length && <li className="px-2 py-3 text-[12.5px] text-muted-foreground">No values match.</li>}
            {shown.length > 200 && <li className="px-2 py-2 text-[12px] text-muted-foreground">Showing 200 of {shown.length}; search to narrow.</li>}
          </ul>
          <div className="flex items-center justify-between border-t px-3 py-2 text-[11.5px] text-muted-foreground"><span>samples · <span className="text-danger">wrong</span></span>{selected.length > 0 && <button type="button" className="font-medium text-primary hover:underline" onClick={() => onChange([])}>Clear</button>}</div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
