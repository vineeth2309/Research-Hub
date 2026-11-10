import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Dialog({ open, onOpenChange, title, description, children, className, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title?: React.ReactNode; description?: React.ReactNode; children: React.ReactNode; className?: string; wide?: boolean }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100vw-24px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-card p-5 shadow-pop focus:outline-none", wide ? "max-w-6xl" : "max-w-lg", className)}>
          {title && <DialogPrimitive.Title className="pr-8 text-[15px] font-semibold tracking-tight">{title}</DialogPrimitive.Title>}
          {description && <DialogPrimitive.Description className="mt-1 text-[12.5px] text-muted-foreground">{description}</DialogPrimitive.Description>}
          <div className={title ? "mt-4" : ""}>{children}</div>
          <DialogPrimitive.Close className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-ring" aria-label="Close"><X className="h-4 w-4" /></DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function Popover({ trigger, children, align = "start", className }: { trigger: React.ReactNode; children: React.ReactNode; align?: "start" | "end" | "center"; className?: string }) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content align={align} sideOffset={6} className={cn("z-50 w-80 rounded-lg border bg-popover p-3 shadow-pop focus:outline-none", className)}>{children}</PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactElement }) {
  return (
    <TooltipPrimitive.Provider delayDuration={300}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content sideOffset={4} className="z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-[12px] text-background shadow-pop">{content}</TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

export type MenuItem = { label?: React.ReactNode; onSelect?: () => void; hint?: React.ReactNode; active?: boolean; separator?: boolean };
export function Menu({ trigger, items, align = "end" }: { trigger: React.ReactNode; items: MenuItem[]; align?: "start" | "end" }) {
  return (
    <DropdownPrimitive.Root>
      <DropdownPrimitive.Trigger asChild>{trigger}</DropdownPrimitive.Trigger>
      <DropdownPrimitive.Portal>
        <DropdownPrimitive.Content align={align} sideOffset={6} className="z-50 min-w-[220px] rounded-lg border bg-popover p-1 shadow-pop">
          {items.map((it, i) =>
            it.separator ? <DropdownPrimitive.Separator key={i} className="my-1 h-px bg-border" /> : (
              <DropdownPrimitive.Item key={i} onSelect={it.onSelect} className={cn("flex cursor-default select-none flex-col gap-0.5 rounded-md px-2.5 py-1.5 text-[13px] outline-none data-[highlighted]:bg-muted", it.active && "bg-accent/60")}>
                <span>{it.label}</span>
                {it.hint && <span className="text-[11.5px] text-muted-foreground">{it.hint}</span>}
              </DropdownPrimitive.Item>
            ),
          )}
        </DropdownPrimitive.Content>
      </DropdownPrimitive.Portal>
    </DropdownPrimitive.Root>
  );
}

// ------------------------------------------------------------------ toasts
type Toast = { id: number; text: string };
const listeners = new Set<(t: Toast[]) => void>();
let toasts: Toast[] = [];
export function toast(text: string) {
  const t = { id: Date.now() + Math.random(), text };
  toasts = [...toasts, t];
  listeners.forEach((l) => l(toasts));
  setTimeout(() => { toasts = toasts.filter((x) => x !== t); listeners.forEach((l) => l(toasts)); }, 3200);
}
export function Toaster() {
  const [list, setList] = React.useState<Toast[]>([]);
  React.useEffect(() => { listeners.add(setList); return () => { listeners.delete(setList); }; }, []);
  return (
    <div className="pointer-events-none fixed bottom-5 left-1/2 z-[60] flex -translate-x-1/2 flex-col gap-2">
      {list.map((t) => <div key={t.id} className="rounded-md bg-foreground px-3.5 py-2 text-[13px] text-background shadow-pop">{t.text}</div>)}
    </div>
  );
}
