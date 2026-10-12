import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/endpoints";
import { Card, PageHeader } from "@/components/Ui";
import { Async, EmptyState } from "@/components/States";
import { CategoryStatusChart, Heatmap, RiskScatter } from "@/components/charts";
import { useApi } from "@/hooks/useApi";
import { useFilters } from "@/hooks/useFilters";
import { DIMENSION_LABELS, MODEL_LABELS, num } from "@/utils/format";

type Dimension = "role" | "industry" | "region" | "country";

export default function Analytics() {
  const { scope } = useFilters();
  const navigate = useNavigate();
  const [dimension, setDimension] = useState<Dimension>("role");
  const filterKey = JSON.stringify(scope);
  const risk = useApi(() => api.riskMap(scope), [filterKey]);
  const categories = useApi(() => api.categories(scope), [filterKey]);
  const heatmap = useApi(() => api.demandBy({ dimension }), [dimension]);
  const candidates = useApi(() => api.candidates({ min_mentions: 3, limit: 30 }), []);
  const performance = useApi(() => api.modelPerformance(), []);

  return (
    <>
      <PageHeader title="Analytics" subtitle="Explore demand and obsolescence patterns, compare skill categories and review phrases the extractor has not matched to the taxonomy." />
      <div className="space-y-5">
        <Async state={risk}>
          {(data) => data.items.length ? (
            <Card title="Demand and obsolescence risk" subtitle={`Each point is a skill. Select one to open its detail page. Scope: ${data.scope}.`}>
              <RiskScatter points={data.items} onSelect={(id) => navigate(`/skills/${id}`)} />
            </Card>
          ) : <EmptyState title="No scored skills in this scope" hint="Run the analysis pipeline or broaden the current filters." />}
        </Async>

        <Async state={categories}>
          {(data) => data.items.length ? (
            <Card title="Trend status by category" subtitle="Counts of skills classified as emerging, growing, stable, declining or at risk.">
              <CategoryStatusChart items={data.items} />
            </Card>
          ) : <EmptyState title="No category summaries available" hint="Load job postings and run the analysis pipeline to build category statistics." />}
        </Async>

        <Async state={heatmap}>
          {(data) => (
            <Card title="Demand by market segment" subtitle="Share of postings mentioning each skill in the last 12 months.">
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <label htmlFor="heatmap-dimension" className="text-sm font-medium text-slate-700">Group by</label>
                <select id="heatmap-dimension" className="input max-w-xs" value={dimension}
                  onChange={(event) => setDimension(event.target.value as Dimension)}>
                  {(Object.keys(DIMENSION_LABELS) as Dimension[]).map((value) => <option key={value} value={value}>{DIMENSION_LABELS[value]}</option>)}
                </select>
                {data.as_of && <span className="text-xs text-slate-500">Data through {new Date(data.as_of).toLocaleDateString()}</span>}
              </div>
              {data.empty ? <p className="py-6 text-center text-sm text-slate-500">Not enough postings to build this comparison.</p> : (
                <>
                  <Heatmap groups={data.groups.map((group) => group.group)} skills={data.skills} cells={data.cells} />
                  <p className="mt-3 text-xs text-slate-500">Values are shares within each group, not shares of the total market.</p>
                </>
              )}
            </Card>
          )}
        </Async>

        <div className="grid gap-5 lg:grid-cols-2">
          <Async state={performance}>
            {(data) => data.available && data.models?.length ? (
              <Card title="Forecast model comparison" subtitle="Rolling-origin validation, grouped by model.">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-200">
                    <thead><tr><th className="th">Model</th><th className="th">Selected</th><th className="th">Mean RMSE</th><th className="th">RMSE vs naive</th></tr></thead>
                    <tbody className="divide-y divide-slate-100">
                      {data.models.map((model) => (
                        <tr key={model.model}>
                          <td className="td font-medium">{MODEL_LABELS[model.model] ?? model.model}</td>
                          <td className="td tabular-nums">{num(model.times_selected)}</td>
                          <td className="td tabular-nums">{num(model.mean_rmse, 5)}</td>
                          <td className="td tabular-nums">{model.rmse_vs_naive === null ? "-" : `${num(model.rmse_vs_naive, 2)}x`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : <Card title="Forecast model comparison"><p className="text-sm text-slate-500">Model evaluation is not available yet. Run the pipeline to train and validate forecasts.</p></Card>}
          </Async>

          <Async state={candidates}>
            {(data) => (
              <Card title="Skill candidates for review" subtitle="Frequent unmatched phrases that may be missing from the skill taxonomy.">
                {data.items.length ? (
                  <>
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200">
                        <thead><tr><th className="th">Phrase</th><th className="th">Mentions</th><th className="th">Suggested category</th><th className="th">Years seen</th></tr></thead>
                        <tbody className="divide-y divide-slate-100">
                          {data.items.map((candidate) => (
                            <tr key={candidate.phrase}>
                              <td className="td font-medium">{candidate.suggested_name ?? candidate.phrase}</td>
                              <td className="td tabular-nums">{num(candidate.mentions)}</td>
                              <td className="td">{candidate.suggested_category ?? "-"}</td>
                              <td className="td">{candidate.first_year} - {candidate.last_year}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="mt-3 text-xs text-slate-500">{data.note}</p>
                  </>
                ) : <p className="py-6 text-center text-sm text-slate-500">No unmatched phrases currently meet the review threshold.</p>}
              </Card>
            )}
          </Async>
        </div>
      </div>
    </>
  );
}
