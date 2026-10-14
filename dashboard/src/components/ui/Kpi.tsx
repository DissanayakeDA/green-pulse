import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/** A stat tile: label, value, a line of context, and an optional trend sparkline. */
export function Kpi({
  icon: Icon,
  label,
  value,
  children,
  trend,
  className = "",
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  children?: ReactNode;
  trend?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-w-0 flex-col rounded-xl border border-line bg-surface p-4 shadow-card ${className}`} aria-label={label}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-ink-3">{label}</p>
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand">
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {children && <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">{children}</div>}
      {trend && <div className="mt-auto pt-3">{trend}</div>}
    </section>
  );
}
