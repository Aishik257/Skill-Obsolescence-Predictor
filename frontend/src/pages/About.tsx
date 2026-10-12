import { Card, Limitations, PageHeader } from "@/components/Ui";

const scoreWeights = [
  { name: "Historical decline", weight: "25%", signal: "Long-term relative change in job-posting demand." },
  { name: "Recent momentum", weight: "20%", signal: "Annualized slope across the most recent six quarters." },
  { name: "Forecasted decline", weight: "25%", signal: "Projected change in demand over the next two years." },
  { name: "Current demand", weight: "10%", signal: "Low current share of postings contributes more risk." },
  { name: "Market persistence", weight: "10%", signal: "How far demand has fallen below its own historical peak." },
  { name: "Emerging replacement risk", weight: "10%", signal: "Evidence that a growing, related skill may be replacing it." },
];

export default function About() {
  return (
    <>
      <PageHeader title="About SkillPulse" subtitle="How the data is processed, what the forecasts mean and where the limits of this analysis are." />
      <div className="space-y-5">
        <Card title="Methodology">
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-slate-700">
            <li>Job-posting records are validated, cleaned and checked for near-duplicates.</li>
            <li>Skill mentions are extracted from descriptions and normalized to the project skill taxonomy.</li>
            <li>Demand is measured as the share of postings that mention a skill, then summarized over time and by market segment.</li>
            <li>Trend classifications use historical behavior and statistical evidence; forecast models are compared using rolling-origin time-series validation.</li>
            <li>An explainable 0-100 score combines market-demand signals. Higher scores indicate greater risk of declining posting demand, not lower technical value.</li>
          </ol>
        </Card>

        <Card title="Obsolescence score weights" subtitle="Weights apply to normalized component risk values. When a component is unavailable, remaining weights are re-normalized.">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead><tr><th className="th">Component</th><th className="th">Weight</th><th className="th">Signal</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {scoreWeights.map((row) => (
                  <tr key={row.name}><td className="td font-medium">{row.name}</td><td className="td tabular-nums">{row.weight}</td><td className="td whitespace-normal">{row.signal}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-slate-500">A stable trend is capped below the high-risk band. Confidence is reported separately and reflects data volume, trend significance, forecast quality and signal agreement.</p>
        </Card>

        <Card title="Forecasting">
          <p className="text-sm leading-6 text-slate-700">
            Candidate models are evaluated with expanding-window, rolling-origin cross-validation rather than shuffled samples. Forecasts are selected using validation RMSE, with a preference for the simpler model when performance is within the configured tie margin. Prediction intervals communicate uncertainty and should be interpreted alongside the historical series and confidence label.
          </p>
        </Card>

        <Limitations items={[
          "Job-posting trends are a proxy for market demand and do not perfectly represent the entire technology labor market.",
          "A declining mention rate does not necessarily mean that a technology is technically obsolete.",
          "Predictions are estimates based on historical data and should not be interpreted as guaranteed future outcomes.",
        ]} />
      </div>
    </>
  );
}
