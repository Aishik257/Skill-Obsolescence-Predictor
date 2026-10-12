import { Link } from "react-router-dom";
import { api } from "@/api/endpoints";
import { Async } from "@/components/States";
import { Card, KpiCard, PageHeader, Pagination } from "@/components/Ui";
import { RiskBadge, StatusBadge } from "@/components/Badges";
import { useApi } from "@/hooks/useApi";
import type { ForecastRow } from "@/types/api";
import { MODEL_LABELS, modelLabel, num, pct, signedPct } from "@/utils/format";
import { useState } from "react";

const PAGE_SIZE = 25;

function changeClass(value: number | null) {
  if (value === null) return "text-slate-400";
  return value >= 0 ? "text-green-700" : "text-red-700";
}

function ForecastTable({ rows }: { rows: ForecastRow[] }) {
  if (!rows.length) return <p className="py-8 text-center text-sm text-slate-500">No forecasts match this page.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead><tr>
          <th className="th">Skill</th><th className="th">Category</th><th className="th">Current demand</th>
          <th className="th">Trend</th><th className="th">Risk</th><th className="th">1 year</th>
          <th className="th">2 years</th><th className="th">3 years</th><th className="th">Model</th>
        </tr></thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.skill_id} className="hover:bg-slate-50">
              <td className="td font-medium"><Link to={`/skills/${row.skill_id}`} className="text-brand-700 hover:underline">{row.name}</Link></td>
              <td className="td">{row.category}</td>
              <td className="td tabular-nums">{pct(row.current_demand)}</td>
              <td className="td"><StatusBadge status={row.trend_status} /></td>
              <td className="td"><RiskBadge level={row.risk_level} /></td>
              <td className="td tabular-nums"><span className={changeClass(row.change_1y)}>{signedPct(row.change_1y)}</span></td>
              <td className="td tabular-nums">
                <span className={changeClass(row.change_2y)}>{signedPct(row.change_2y)}</span>
                {row.lower_2y !== null && row.upper_2y !== null &&
                  <span className="ml-1 block text-xs text-slate-500">{pct(row.lower_2y)} - {pct(row.upper_2y)}</span>}
              </td>
              <td className="td tabular-nums"><span className={changeClass(row.change_3y)}>{signedPct(row.change_3y)}</span></td>
              <td className="td">{modelLabel(row.model)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Forecasts() {
  const [page, setPage] = useState(1);
  const forecasts = useApi(
    () => api.forecasts({ page, page_size: PAGE_SIZE, sort: "change_2y", order: "desc" }),
    [page],
  );
  const performance = useApi(() => api.modelPerformance(), []);

  return (
    <>
      <PageHeader title="Forecasts" subtitle="Modelled changes in job-posting demand over one, two and three years. Forecast intervals describe uncertainty, not guarantees." />
      <div className="space-y-5">
        <Async state={performance}>
          {(data) => data.available && data.selected_summary ? (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <KpiCard label="Skills with forecasts" value={num(data.selected_summary.skills_with_forecast)} />
              <KpiCard label="Mean RMSE" value={num(data.selected_summary.mean_rmse, 4)} hint="Lower is better" />
              <KpiCard label="Mean MAPE" value={pct(data.selected_summary.mean_mape)} hint="Actual share >= 1%" />
              <KpiCard label="Model version" value={data.model_version ?? "-"} hint={data.trained_at ? `Trained ${new Date(data.trained_at).toLocaleDateString()}` : undefined} />
            </div>
          ) : <Card><p className="text-sm text-slate-500">No forecast model evaluation is available yet. Run the pipeline from Job data.</p></Card>}
        </Async>

        <Async state={forecasts}>
          {(data) => (
            <Card title="Skill demand forecasts" subtitle={`${num(data.total)} skills, ranked by projected two-year change`}>
              <ForecastTable rows={data.items} />
              <Pagination page={data.page} pages={data.pages} total={data.total} onPage={setPage} />
            </Card>
          )}
        </Async>

        {performance.data?.available && performance.data.models?.length ? (
          <Card title="Backtest performance" subtitle={performance.data.validation?.method}>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-200">
                  <thead><tr>
                    <th className="th">Model</th><th className="th">Skills evaluated</th><th className="th">Selected</th>
                    <th className="th">Mean MAE</th><th className="th">Mean RMSE</th><th className="th">Mean MAPE</th><th className="th">Median R2</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {performance.data.models.map((model) => (
                      <tr key={model.model}>
                        <td className="td font-medium">{MODEL_LABELS[model.model] ?? model.model}</td>
                        <td className="td tabular-nums">{num(model.skills_evaluated)}</td>
                        <td className="td tabular-nums">{num(model.times_selected)}</td>
                        <td className="td tabular-nums">{num(model.mean_mae, 5)}</td>
                        <td className="td tabular-nums">{num(model.mean_rmse, 5)}</td>
                        <td className="td tabular-nums">{pct(model.mean_mape)}</td>
                        <td className="td tabular-nums">{num(model.median_r2, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {performance.data.validation && <p className="mt-3 text-xs text-slate-500">{performance.data.validation.selection}. Validation uses {performance.data.validation.horizon_quarters}-quarter horizons and expanding training windows.</p>}
          </Card>
        ) : null}
      </div>
    </>
  );
}
