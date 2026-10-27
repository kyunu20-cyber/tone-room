"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** Section header: `[ CH-01 ] TITLE ............ right` */
export function Head({ ch, title, right, className }: { ch: string; title: string; right?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex h-8 min-w-0 items-center gap-2 border-b border-rule px-3 text-[11px] tracking-[0.14em]", className)}>
      <span className="shrink-0 text-muted-foreground">[ {ch} ]</span>
      <span className="truncate font-medium">{title}</span>
      <span className="ml-auto flex shrink-0 items-center gap-2 text-muted-foreground">{right}</span>
    </div>
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; tone?: "default" | "accent" | "danger" };

export function Btn({ className, active, tone = "default", ...props }: BtnProps) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-7 shrink-0 items-center justify-center gap-1.5 border px-2.5 text-[11px] tracking-[0.12em] whitespace-nowrap transition-colors",
        "outline-none focus-visible:ring-1 focus-visible:ring-eva disabled:pointer-events-none disabled:opacity-35",
        tone === "accent" && "border-eva/70 text-eva hover:bg-eva hover:text-black",
        tone === "danger" && "border-rule-2 text-muted-foreground hover:border-destructive hover:text-destructive",
        tone === "default" && "border-rule-2 text-white hover:border-white",
        active && "border-eva bg-eva text-black hover:border-eva",
        className,
      )}
      {...props}
    />
  );
}

/** Segmented control (mono buttons sharing borders). */
export function Seg<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0", className)}>
      {options.map((o, i) => (
        <Btn key={o.value} active={o.value === value} onClick={() => onChange(o.value)} className={cn("flex-1 px-2", i > 0 && "-ml-px")}>
          {o.label}
        </Btn>
      ))}
    </div>
  );
}

export function Bar({ value, tone = "accent", className }: { value: number; tone?: "accent" | "muted" | "danger"; className?: string }) {
  return (
    <div className={cn("relative h-[3px] w-full overflow-hidden bg-[#1a1a1a]", className)}>
      <motion.div
        className={cn("absolute inset-y-0 left-0", tone === "accent" ? "bg-eva" : tone === "danger" ? "bg-destructive" : "bg-[#555]")}
        initial={false}
        animate={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        transition={{ ease: "linear", duration: 0.3 }}
      />
    </div>
  );
}

export function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-[10px] tracking-[0.16em] text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export function ErrorLine({ message, onClose }: { message: string | null; onClose?: () => void }) {
  if (!message) return null;
  return (
    <div className="flex items-start gap-2 border border-destructive/60 bg-destructive/10 px-3 py-2 text-xs text-[#ffb3b3]">
      <span className="shrink-0 tracking-[0.14em] text-destructive">ERR</span>
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onClose && (
        <button className="shrink-0 text-muted-foreground hover:text-white" onClick={onClose} aria-label="닫기">
          ×
        </button>
      )}
    </div>
  );
}
