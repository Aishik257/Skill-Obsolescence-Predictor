import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/endpoints";
import FilterBar from "@/components/FilterBar";
import { Async, EmptyState, ErrorState, Loading } from "@/components/States";
import { Card, Limitations, PageHeader, Tabs } from "@/components/Ui";
import { StatusBadge } from "@/components/Badges";
import { MultiLineChart } from "@/components/charts";
import { useApi } from "@/hooks/useApi";
import { useDebounce } from "@/hooks/useDebounce";
import { useFilters } from "@/hooks/useFilters";
import type { SkillSummary } from "@/types/api";
import { pct, signedPct } from "@/utils/format";

type Kind = "growing" | "emerging" | "declining";

function TrendLists({ kind, scope }: { kind: Kind; scope: Record<string, string> }) {
  const state = useApi(() => api.trendList(kind, { ...scope, limit: 12 }), [kind, JSON.stringify(scope)]);
  return (
    <Async state={state} isEmpty={(d) => d.items.length === 0}
      empty={<EmptyState title={`No ${kind} skills for these filters`} hint="Try a broader selection; small slices do not have enough postings for a reliable trend." />}>
      {(d) => (
        <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {d.items.map((s: SkillSummary, i) => (
            <li key={s.skill_id} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium"><span className="mr-1.5 text-slate-400">{i + 1}.</span>
                  <Link className="text-brand-700 hover:underline" to={`/skills/${s.skill_id}`}>{s.name}</Link></p>
                <p className="text-xs text-slate-500">{pct(s.current_demand)} of postings - YoY {signedPct(s.yoy_growth)}</p>
              </div>
              <div className="text-right">
                <p className={`text-sm font-semibold tabular-nums ${(s.growth_rate ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>{signedPct(s.growth_rate)}</p>
                <StatusBadge status={s.trend_status} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </Async>
  );
}

function Compare({ scope }: { scope: Record<string, string> }) {
  const [selected, setSelected] = useState<{ id: number; name: string }[]>([]);
  const [q, setQ] = useState("");
  const dq = useDebounce(q.trim(), 200);
  const [options, setOptions] = useState<SkillSummary[]>([]);
  const [granularity, setGranularity] = useState<"quarter" | "month" | "year">("quarter");

  // default: the three highest-demand growing skills
  const defaults = useApi(() => api.trendList("growing", { ...scope, limit: 3 }), [JSON.stringify(scope)], selected.length === 0);
  useEffect(() => {
    if (selected.length === 0 && defaults.data?.items.length) setSelected(defaults.data.items.map((s) => ({ id: s.skill_id, name: s.name })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults.data]);

  useEffect(() => {
    if (!dq) { setOptions([]); return; }
    const c = new AbortController();
    api.searchSkills(dq, 6, c.signal).then((r) => setOptions(r.results)).catch(() => undefined);
    return () => c.abort();
  }, [dq]);

  const ids = selected.map((s) => s.id);
  const series = useApi(() => api.series(ids, { ...scope, granularity }), [ids.join(","), JSON.stringify(scope), granularity], ids.length > 0);

  return (
    <Card title="Compare skills over time" subtitle="Share of job postings mentioning each skill. Add up to 6 skills."
      actions={<Tabs value={granularity} onChange={setGranularity} options={[{ value: "quarter", label: "Quarterly" }, { value: "month", label: "Monthly" }, { value: "year", label: "Yearly" }]} />}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {selected.map((s) => (
          <span key={s.id} className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
            {s.name}
            <button type="button" aria-label={`Remove ${s.name}`} className="ml-1 text-brand-700 hover:text-red-600" onClick={() => setSelected((x) => x.filter((y) => y.id !== s.id))}>×</button>
          </span>
        ))}
        <div className="relative">
          <label htmlFor="compare-add" className="sr-only">Add a skill to compare</label>
          <input id="compare-add" className="input w-56 py-1.5" placeholder="Add a skill..." value={q} onChange={(e) => setQ(e.target.value)} disabled={selected.length >= 6} />
          {options.length > 0 && q && (
            <ul className="absolute z-20 mt-1 w-full rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
              {options.filter((o) => !ids.includes(o.skill_id)).map((o) => (
                <li key={o.skill_id}>
                  <button type="button" className="w-full px-3 py-1.5 text-left text-sm hover:bg-slate-50"
                    onClick={() => { setSelected((x) => [...x, { id: o.skill_id, name: o.name }]); setQ(""); setOptions([]); }}>{o.name}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {ids.length === 0 ? <EmptyState title="Pick a skill to compare" /> :
        series.error ? <ErrorState message={series.error} onRetry={series.reload} /> :
        series.loading && !series.data ? <Loading /> :
        series.data?.empty ? <EmptyState title="Not enough postings in this slice" hint="Widen the filters to see a trend." /> :
        series.data ? <MultiLineChart series={series.data} /> : null}
    </Card>
  );
}

export default function Trends() {
  const { scope } = useFilters();
  const [kind, setKind] = useState<Kind>("growing");
  return (
    <>
      <PageHeader title="Trends" subtitle="Normalised frequency (mentions per posting) removes the effect of changing posting volume, so trends are comparable across years." />
      <FilterBar show={["role", "industry", "country", "year"]} />
      <div className="space-y-5">
        <Compare scope={scope} />
        <Card title="Skill movers" actions={<Tabs value={kind} onChange={setKind}
          options={[{ value: "growing", label: "Growing" }, { value: "emerging", label: "Emerging" }, { value: "declining", label: "Declining" }]} />}>
          <TrendLists kind={kind} scope={scope} />
        </Card>
        <Limitations compact />
      </div>
    </>
  );
}
