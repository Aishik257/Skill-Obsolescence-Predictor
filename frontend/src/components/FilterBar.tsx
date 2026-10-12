import { api } from "@/api/endpoints";
import { useApi } from "@/hooks/useApi";
import { useFilters, type FilterKey } from "@/hooks/useFilters";
import { RISK_LABELS, STATUS_LABELS } from "@/utils/format";
import type { RiskLevel, TrendStatus } from "@/types/api";

function Select({ id, label, value, onChange, options }: {
  id: string; label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  return (
    <div className="min-w-[8.5rem] flex-1">
      <label htmlFor={id} className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</label>
      <select id={id} className="input py-1.5" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

/** Global filters: scope (role, industry, country, region, year) plus category / status / risk. */
export default function FilterBar({ show = ["role", "industry", "country", "year", "category", "status", "risk"] }: { show?: FilterKey[] }) {
  const { filters, set, clear, activeCount } = useFilters();
  const opts = useApi(() => api.filterOptions(), []);
  const o = opts.data;
  const has = (k: FilterKey) => show.includes(k);
  return (
    <div className="card card-pad mb-5" aria-label="Filters">
      <div className="flex flex-wrap items-end gap-3">
        {has("role") && <Select id="f-role" label="Role" value={filters.role ?? ""} onChange={(v) => set("role", v)} options={(o?.roles ?? []).map((r) => ({ value: r.value, label: r.value }))} />}
        {has("industry") && <Select id="f-industry" label="Industry" value={filters.industry ?? ""} onChange={(v) => set("industry", v)} options={(o?.industries ?? []).map((r) => ({ value: r.value, label: r.value }))} />}
        {has("country") && <Select id="f-country" label="Location" value={filters.country ?? ""} onChange={(v) => set("country", v)} options={(o?.countries ?? []).map((r) => ({ value: r.value, label: r.value }))} />}
        {has("region") && <Select id="f-region" label="Region" value={filters.region ?? ""} onChange={(v) => set("region", v)} options={(o?.regions ?? []).map((r) => ({ value: r.value, label: r.value }))} />}
        {has("year") && <Select id="f-year" label="Year" value={filters.year ?? ""} onChange={(v) => set("year", v)} options={(o?.years ?? []).map((y) => ({ value: String(y), label: String(y) }))} />}
        {has("category") && <Select id="f-category" label="Category" value={filters.category ?? ""} onChange={(v) => set("category", v)} options={(o?.categories ?? []).map((c) => ({ value: c, label: c }))} />}
        {has("status") && <Select id="f-status" label="Trend" value={filters.status ?? ""} onChange={(v) => set("status", v)}
          options={(o?.statuses ?? []).map((s) => ({ value: s, label: STATUS_LABELS[s as TrendStatus] ?? s }))} />}
        {has("risk") && <Select id="f-risk" label="Risk" value={filters.risk ?? ""} onChange={(v) => set("risk", v)}
          options={(o?.risk_levels ?? []).map((r) => ({ value: r, label: RISK_LABELS[r as RiskLevel] ?? r }))} />}
        {activeCount > 0 && <button type="button" className="btn-secondary" onClick={clear}>Clear filters ({activeCount})</button>}
      </div>
      {opts.error && <p role="alert" className="mt-2 text-xs text-red-700">Filter options could not be loaded: {opts.error}</p>}
    </div>
  );
}
