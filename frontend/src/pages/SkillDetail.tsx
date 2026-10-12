import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/endpoints";
import { ConfidenceBadge, RiskBadge, ScoreBar, StatusBadge } from "@/components/Badges";
import FilterBar from "@/components/FilterBar";
import { Async, EmptyState, ErrorState, Loading } from "@/components/States";
import { Card, KpiCard, Limitations, PageHeader, Tabs } from "@/components/Ui";
import { ScoreBreakdownChart, TrendChart } from "@/components/charts";
import { useApi } from "@/hooks/useApi";
import { useFilters } from "@/hooks/useFilters";
import type { BreakdownGroup, ForecastResponse, SkillDetail } from "@/types/api";
import { modelLabel, num, pct, pValue, signedPct, DIMENSION_LABELS } from "@/utils/format";

function ForecastSection({ id, scope, name }: { id: string; scope: Record<string, string>; name: string }) {
  const history = useApi(() => api.skillHistory(id, { ...scope, granularity: "quarter" }), [id, JSON.stringify(scope)]);
  const forecast = useApi(() => api.skillForecast(id, scope), [id, JSON.stringify(scope)]);
  const f: ForecastResponse | null = forecast.data;
  const ok = f?.status === "ok";

  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2" title={`Demand for ${name}`} subtitle="Share of job postings mentioning the skill, with a 4-quarter average, 95% interval and the selected model's forecast">
        {history.error ? <ErrorState message={history.error} onRetry={history.reload} />
          : !history.data ? <Loading />
          : history.data.empty || history.data.points.length === 0
            ? <EmptyState title="Not enough postings to chart this skill" hint="Try removing a filter." />
            : <TrendChart history={history.data.points} forecast={ok ? f!.forecast : undefined} />}
        {history.data && history.data.points.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            {num(history.data.total_mentions)} mentions in {num(history.data.total_jobs)} postings. Quarters with fewer than the minimum number of postings are excluded.
          </p>
        )}
      </Card>

      <Card title="Forecast" subtitle={ok ? `Model: ${modelLabel(f!.model)} (chosen by rolling-origin cross-validation)` : undefined}>
        {forecast.error ? <ErrorState message={forecast.error} onRetry={forecast.reload} />
          : !f ? <Loading />
          : !ok ? <EmptyState title="Insufficient historical data" hint={f.message ?? "At least 12 quarters of history and 40 mentions are needed for a reliable forecast."} />
          : (
            <div>
              <table className="w-full text-sm">
                <thead><tr><th className="th px-0">Horizon</th><th className="th text-right">Demand</th><th className="th text-right">Range</th><th className="th text-right">vs now</th></tr></thead>
                <tbody>
                  {(["1y", "2y", "3y"] as const).map((h) => {
                    const p = (f.horizons as Record<string, ForecastResponse["horizons"][keyof ForecastResponse["horizons"]]>)[h];
                    if (!p) return null;
                    return (
                      <tr key={h} className="border-t border-slate-100">
                        <td className="py-2 font-medium">{h === "1y" ? "1 year" : h === "2y" ? "2 years" : "3 years"} <span className="text-xs text-slate-400">{(p as { period: string }).period}</span></td>
                        <td className="td text-right tabular-nums">{pct((p as { predicted: number }).predicted)}</td>
                        <td className="td text-right text-xs tabular-nums text-slate-500">{pct((p as { lower: number }).lower)} - {pct((p as { upper: number }).upper)}</td>
                        <td className="td text-right tabular-nums">{signedPct((p as { change: number | null }).change)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-slate-500">Ranges are widened by each model's back-test error, so they show how unsure the forecast is. This is an estimate, not a guarantee.</p>
            </div>
          )}
      </Card>

      {ok && f!.models.length > 0 && (
        <Card className="xl:col-span-3" title="Model comparison" subtitle="Each candidate was back-tested on this skill's own history (rolling-origin cross-validation, never shuffled). Lower error is better.">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead><tr><th className="th">Model</th><th className="th text-right">MAE</th><th className="th text-right">RMSE</th><th className="th text-right">MAPE</th><th className="th text-right">R²</th><th className="th text-right">Folds</th><th className="th" /></tr></thead>
              <tbody>
                {f!.models.map((m) => (
                  <tr key={m.model} className={`border-t border-slate-100 ${m.selected ? "bg-brand-50/60" : ""}`}>
                    <td className="td font-medium">{modelLabel(m.model)}</td>
                    <td className="td text-right tabular-nums">{pct(m.mae, 2)}</td>
                    <td className="td text-right tabular-nums">{pct(m.rmse, 2)}</td>
                    <td className="td text-right tabular-nums">{pct(m.mape, 0)}</td>
                    <td className="td text-right tabular-nums">{m.r2 === null ? "-" : m.r2.toFixed(2)}</td>
                    <td className="td text-right tabular-nums">{m.folds}</td>
                    <td className="td">{m.selected && <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-medium text-white">selected</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function BreakdownSection({ id, scope }: { id: string; scope: Record<string, string> }) {
  const [dim, setDim] = useState<"role" | "industry" | "country">("role");
  const state = useApi(() => api.skillBreakdown(id, dim, scope), [id, dim, JSON.stringify(scope)]);
  return (
    <Card title="Where it is in demand" subtitle="Share of postings mentioning the skill within each group, and how that share has changed"
      actions={<Tabs value={dim} onChange={setDim} options={(["role", "industry", "country"] as const).map((d) => ({ value: d, label: DIMENSION_LABELS[d] }))} />}>
      <Async state={state} isEmpty={(d) => d.groups.length === 0} empty={<EmptyState title="No breakdown available" />}>
        {(d) => (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead><tr><th className="th">{DIMENSION_LABELS[dim]}</th><th className="th text-right">Postings</th><th className="th text-right">Demand</th><th className="th text-right">Change</th><th className="th">Trend</th><th className="th">Significance</th></tr></thead>
              <tbody>
                {d.groups.map((g: BreakdownGroup) => (
                  <tr key={g.group} className="border-t border-slate-100">
                    <td className="td font-medium">{g.group}</td>
                    <td className="td text-right tabular-nums">{num(g.jobs)}</td>
                    <td className="td text-right tabular-nums">{g.sufficient ? pct(g.current_demand) : "-"}</td>
                    <td className="td text-right tabular-nums">{g.sufficient ? signedPct(g.growth) : "-"}</td>
                    <td className="td">{g.sufficient ? <StatusBadge status={g.trend_status} /> : <span className="text-xs text-slate-400">too few postings</span>}</td>
                    <td className="td text-xs text-slate-500">{g.sufficient ? pValue(g.p_value) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </Card>
  );
}

function Detail({ d, id, scope }: { d: SkillDetail; id: string; scope: Record<string, string> }) {
  const [showRules, setShowRules] = useState(false);
  const ex = d.explanation;
  const m = d.metrics;
  return (
    <div className="space-y-5">
      <div className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{d.category}</p>
            <h1 className="mt-0.5">{d.name}</h1>
            {d.description && <p className="mt-1 text-sm text-slate-600">{d.description}</p>}
            {d.aliases.length > 0 && <p className="mt-1 text-xs text-slate-500">Also written as: {d.aliases.join(", ")}</p>}
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2"><StatusBadge status={d.trend_status} /><RiskBadge level={d.risk_level} /></div>
            <div className="flex items-center gap-2 text-xs text-slate-500">Score <ScoreBar value={d.obsolescence_score} /> Confidence <ConfidenceBadge label={d.confidence_label} value={d.confidence} /></div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiCard label="Current demand" value={pct(d.current_demand)} hint="share of postings, last 4 quarters" />
        <KpiCard label="Long-term change" value={signedPct(d.growth_rate)} tone={(d.growth_rate ?? 0) >= 0 ? "good" : "bad"} hint="first year vs latest year" />
        <KpiCard label="Year over year" value={signedPct(d.yoy_growth)} tone={(d.yoy_growth ?? 0) >= 0 ? "good" : "bad"} hint="latest 12 months vs the 12 before" />
        <KpiCard label="Momentum" value={signedPct(d.momentum)} hint="annualised, last 6 quarters" />
        <KpiCard label="Demand in 2 years" value={d.future_demand === null ? "n/a" : pct(d.future_demand)} hint={d.forecast_model ? modelLabel(d.forecast_model) : "no forecast"} />
      </div>

      <Card title={ex.headline} subtitle={ex.risk_text}>
        <p className="text-sm text-slate-700">{ex.summary}</p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">{ex.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
        <p className="mt-3 rounded-lg bg-brand-50 p-3 text-sm text-brand-900">{ex.recommendation}</p>
        <button type="button" className="mt-3 text-xs font-medium text-brand-700 hover:underline" aria-expanded={showRules} onClick={() => setShowRules((s) => !s)}>
          {showRules ? "Hide" : "Show"} how the trend status was decided
        </button>
        {showRules && (
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {ex.rules.map((r) => (
              <li key={r.rule}><span className={r.passed ? "font-semibold text-green-700" : "text-slate-400"}>{r.passed ? "✔" : "✘"}</span> <span className="font-medium">{r.rule.replace("_", " ")}</span>: {r.detail}</li>
            ))}
          </ul>
        )}
      </Card>

      <ForecastSection id={id} scope={scope} name={d.name} />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Why this obsolescence score" subtitle={`${d.obsolescence_score?.toFixed(0) ?? "-"} / 100 - points contributed by each factor`}>
          <ScoreBreakdownChart components={ex.score_breakdown} />
          {ex.score_notes.length > 0 && <ul className="mt-2 space-y-1 text-xs text-amber-800">{ex.score_notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <div className="mt-3 border-t border-slate-100 pt-3">
            <p className="text-xs font-medium text-slate-700">Confidence: <ConfidenceBadge label={d.confidence_label} value={d.confidence} /></p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-600">{ex.confidence_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        </Card>

        <Card title="Statistical evidence" subtitle="Computed from this skill's quarterly shares">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            {([
              ["Quarters of data", m.n_quarters != null ? String(m.n_quarters) : "-"],
              ["Mentions / postings", `${num(m.total_mentions as number)} / ${num(m.total_jobs as number)}`],
              ["First-year demand", pct(m.first_demand as number)],
              ["Current demand", pct(m.current_demand as number)],
              ["Peak demand", `${pct(m.peak_demand as number)} (${m.peak_period ?? "-"})`],
              ["CAGR", signedPct(m.cagr as number, 1)],
              ["Long-term significance", pValue(m.p_long as number)],
              ["Recent significance", pValue(m.p_recent as number)],
              ["Kendall tau (trend)", m.kendall_tau != null ? (m.kendall_tau as number).toFixed(2) : "-"],
              ["Window compared", `${m.window_first ?? "-"} → ${m.window_last ?? "-"}`],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium tabular-nums">{v}</dd></div>
            ))}
          </dl>
        </Card>
      </div>

      <BreakdownSection id={id} scope={scope} />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Skills it appears with" subtitle="Co-occurrence in the same postings (NPMI); a complement, not a substitute">
          {d.related_skills.length === 0 ? <p className="py-4 text-sm text-slate-500">No pairs with enough evidence.</p> : (
            <ul className="divide-y divide-slate-100">
              {d.related_skills.map((r) => (
                <li key={r.skill_id} className="flex items-center justify-between py-2 text-sm">
                  <Link className="font-medium text-brand-700 hover:underline" to={`/skills/${r.skill_id}`}>{r.name}</Link>
                  <span className="text-xs text-slate-500">in {pct(r.details.share_with, 0)} of its postings - lift {r.details.lift.toFixed(1)}×</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Possible replacement trends" subtitle="Hypotheses about market shifts, not proof that one skill replaced another">
          {d.replacements.length === 0 ? (
            <p className="py-4 text-sm text-slate-500">No growing skill matches this one's pattern well enough to suggest a transition.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {d.replacements.map((r) => (
                <li key={r.skill_id} className="py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <Link className="font-medium text-brand-700 hover:underline" to={`/skills/${r.skill_id}`}>{r.name}</Link>
                    <span className="text-xs text-slate-500">match {(r.score * 100).toFixed(0)}% - grew {signedPct(r.details.grower_change)}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">{r.details.note}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Limitations items={ex.limitations} />
    </div>
  );
}

export default function SkillDetailPage() {
  const { id = "" } = useParams();
  const { scope } = useFilters();
  const state = useApi(() => api.skill(id, scope), [id, JSON.stringify(scope)]);
  return (
    <>
      <p className="mb-3 text-sm"><Link to="/skills" className="text-brand-700 hover:underline">← All skills</Link></p>
      <FilterBar show={["role", "industry", "country", "year"]} />
      <Async state={state}>{(d) => <Detail d={d} id={id} scope={scope} />}</Async>
    </>
  );
}

export { PageHeader };
