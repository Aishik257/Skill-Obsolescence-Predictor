import { Link } from "react-router-dom";
import { api } from "@/api/endpoints";
import { RiskBadge, ScoreBar, StatusBadge } from "@/components/Badges";
import FilterBar from "@/components/FilterBar";
import { Async, EmptyState } from "@/components/States";
import { Card, KpiCard, Limitations, PageHeader } from "@/components/Ui";
import { YearBars } from "@/components/charts";
import { useApi } from "@/hooks/useApi";
import { useFilters } from "@/hooks/useFilters";
import type { SkillSummary } from "@/types/api";
import { dateLabel, num, pct, signedPct } from "@/utils/format";

function MiniList({ title, subtitle, items, metric }: {
  title: string; subtitle: string; items: SkillSummary[]; metric: "growth" | "risk";
}) {
  return (
    <Card title={title} subtitle={subtitle}>
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-500">No skills in this group for the current filters.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((s) => (
            <li key={s.skill_id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <Link to={`/skills/${s.skill_id}`} className="block truncate text-sm font-medium text-brand-700 hover:underline">{s.name}</Link>
                <p className="text-xs text-slate-500">{s.category} - demand {pct(s.current_demand)}</p>
              </div>
              {metric === "growth" ? (
                <div className="flex shrink-0 items-center gap-2">
                  <span className={`text-sm tabular-nums ${(s.growth_rate ?? 0) >= 0 ? "text-green-700" : "text-red-700"}`}>{signedPct(s.growth_rate)}</span>
                  <StatusBadge status={s.trend_status} />
                </div>
              ) : (
                <div className="flex shrink-0 items-center gap-3"><ScoreBar value={s.obsolescence_score} /><RiskBadge level={s.risk_level} /></div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Dashboard() {
  const { scope, clear } = useFilters();
  const state = useApi(() => api.overview(scope), [JSON.stringify(scope)]);

  return (
    <>
      <PageHeader title="Skill market overview"
        subtitle="Which skills are gaining or losing share of job postings, what the models forecast, and which skills carry a high obsolescence risk." />
      <FilterBar show={["role", "industry", "country", "year"]} />
      <Async state={state}>
        {(d) => {
          const k = d.kpis;
          if (!d.has_data) {
            return (
              <EmptyState title="No job postings yet" hint="Load the sample dataset or upload your own CSV to see trends, forecasts and risk scores."
                action={<Link to="/data" className="btn-primary">Go to Job data</Link>} />
            );
          }
          if (!d.has_predictions) {
            return (
              <div className="space-y-5">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  <KpiCard label="Matching job postings" value={num(k.total_jobs)}
                    hint={`${dateLabel(d.date_range.min)} - ${dateLabel(d.date_range.max)}`} />
                  <KpiCard label="Skills with enough evidence" value={num(k.unique_skills)}
                    hint="Enough history to calculate a trend" />
                  <KpiCard label="Insufficient data" value={num(k.insufficient_data)}
                    hint="Skills that did not meet the trend evidence threshold" />
                </div>
                <EmptyState title="Not enough data for trend analysis with these filters"
                  hint="Postings are loaded. This filtered slice is too small or sparse over time to calculate reliable skill trends. A skill needs at least 8 usable quarters (each with 8 or more matching postings) and 20 skill mentions. Broaden the filters, for example by removing the role filter. Uploading the sample CSV or rerunning the pipeline will not add more evidence to this slice."
                  action={<button type="button" className="btn-primary" onClick={clear}>Clear filters and broaden the view</button>} />
              </div>
            );
          }
          return (
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <KpiCard label="Job postings" value={num(k.total_jobs)} hint={`${dateLabel(d.date_range.min)} - ${dateLabel(d.date_range.max)}`} />
                <KpiCard label="Skills analysed" value={num(k.unique_skills)} hint="mentioned at least once" />
                <KpiCard label="Growing" value={num(k.growing)} tone="good" hint="share of postings rising" />
                <KpiCard label="Emerging" value={num(k.emerging)} tone="info" hint="new and accelerating" />
                <KpiCard label="Declining" value={num(k.declining)} tone="warn" hint="share of postings falling" />
                <KpiCard label="High obsolescence risk" value={num(k.at_risk)} tone="bad" hint="declining and forecast to keep falling" />
              </div>

              <Card title={d.market_outlook.headline} subtitle="Market outlook, generated from the computed trends">
                <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
                  {d.market_outlook.bullets.map((b) => <li key={b}>{b}</li>)}
                </ul>
              </Card>

              <div className="grid gap-5 lg:grid-cols-2">
                <MiniList title="Fastest growing" subtitle="Largest long-term gain in share of postings" items={d.top_growing} metric="growth" />
                <MiniList title="Emerging skills" subtitle="Rare at first, now clearly rising" items={d.emerging} metric="growth" />
                <MiniList title="Declining skills" subtitle="Largest long-term loss in share of postings" items={d.top_declining} metric="growth" />
                <MiniList title="Highest obsolescence risk" subtitle="Score 0-100, higher means more risk to market demand" items={d.highest_risk} metric="risk" />
              </div>

              <div className="grid gap-5 lg:grid-cols-3">
                <Card title="Postings per year" subtitle="Volume behind every percentage on this page" className="lg:col-span-1">
                  <YearBars data={d.postings_by_year} />
                </Card>
                <div className="lg:col-span-2"><Limitations items={d.limitations} /></div>
              </div>
            </div>
          );
        }}
      </Async>
    </>
  );
}
