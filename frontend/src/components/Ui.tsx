import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Card({ title, subtitle, actions, children, className = "" }: {
  title?: string; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card card-pad ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function KpiCard({ label, value, hint, tone = "default" }: {
  label: string; value: ReactNode; hint?: string; tone?: "default" | "good" | "warn" | "bad" | "info";
}) {
  const tones = { default: "text-slate-900", good: "text-green-600", warn: "text-amber-600", bad: "text-red-600", info: "text-cyan-600" };
  return (
    <div className="card card-pad" data-testid="kpi-card">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Pagination({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  if (pages <= 1) return <p className="mt-3 text-xs text-slate-500">{total.toLocaleString()} result{total === 1 ? "" : "s"}</p>;
  return (
    <div className="mt-3 flex items-center justify-between text-sm">
      <p className="text-xs text-slate-500">{total.toLocaleString()} results - page {page} of {pages}</p>
      <div className="flex gap-2">
        <button type="button" className="btn-secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button type="button" className="btn-secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function Limitations({ items, compact = false }: { items?: string[]; compact?: boolean }) {
  const list = items?.length ? items : DEFAULT_LIMITATIONS;
  return (
    <aside aria-label="Limitations" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <p className="font-medium">How to read these numbers</p>
      <ul className={`mt-1.5 list-disc space-y-1 pl-5 ${compact ? "text-xs" : ""}`}>
        {list.map((l) => <li key={l}>{l}</li>)}
      </ul>
    </aside>
  );
}

export const DEFAULT_LIMITATIONS = [
  "Job-posting trends are a proxy for market demand and do not perfectly represent the entire technology labor market.",
  "A declining mention rate does not necessarily mean that a technology is technically obsolete.",
  "Predictions are estimates based on historical data and should not be interpreted as guaranteed future outcomes.",
];

export function Tabs<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[];
}) {
  return (
    <div role="tablist" className="inline-flex rounded-lg bg-slate-100 p-0.5">
      {options.map((o) => (
        <button key={o.value} role="tab" type="button" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${o.value === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
