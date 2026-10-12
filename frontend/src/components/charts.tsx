import { useMemo } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, Cell,
} from "recharts";
import type { CategorySummary, ForecastPoint, HistoryPoint, RiskPoint, ScoreComponent, SeriesResponse } from "@/types/api";
import { RISK_COLORS, STATUS_COLORS, STATUS_LABELS, pct, periodTick } from "@/utils/format";

const AXIS = { fontSize: 11, fill: "#64748b" };
const PALETTE = ["#4f46e5", "#0891b2", "#16a34a", "#f59e0b", "#dc2626", "#9333ea", "#0d9488", "#db2777"];

function tickEvery(n: number, target = 8) {
  return Math.max(0, Math.ceil(n / target) - 1);
}

/** Historical share of postings with its moving average, Wilson interval and an optional forecast band. */
export function TrendChart({ history, forecast, height = 320 }: { history: HistoryPoint[]; forecast?: ForecastPoint[]; height?: number }) {
  const data = useMemo(() => {
    const rows: Record<string, number | string | number[] | null>[] = history.map((p) => ({
      period: p.period, actual: p.frequency, average: p.moving_average ?? null,
      ci: p.ci_low != null && p.ci_high != null ? [p.ci_low, p.ci_high] : null,
    }));
    if (forecast?.length && history.length) {
      const last = history[history.length - 1];
      rows[rows.length - 1] = { ...rows[rows.length - 1], forecast: last.frequency, band: [last.frequency, last.frequency] };
      forecast.forEach((f) => rows.push({ period: f.period, forecast: f.predicted, band: [f.lower, f.upper] }));
    }
    return rows;
  }, [history, forecast]);
  const boundary = history.length ? history[history.length - 1].period : undefined;

  return (
    <div role="img" aria-label="Line chart of the share of job postings mentioning this skill over time">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="period" tick={AXIS} tickFormatter={periodTick} interval={tickEvery(data.length)} />
          <YAxis tick={AXIS} tickFormatter={(v) => pct(v, 0)} width={48} />
          <Tooltip formatter={(v: unknown, name: string) => [Array.isArray(v) ? `${pct(v[0])} - ${pct(v[1])}` : pct(v as number, 1), name]}
            labelFormatter={(l) => String(l)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area type="monotone" dataKey="ci" name="95% interval (history)" stroke="none" fill="#6366f1" fillOpacity={0.12} isAnimationActive={false} />
          <Area type="monotone" dataKey="band" name="Forecast range" stroke="none" fill="#f59e0b" fillOpacity={0.2} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual" name="Share of postings" stroke="#4f46e5" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          <Line type="monotone" dataKey="average" name="4-quarter average" stroke="#0891b2" strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false} />
          {forecast?.length ? (
            <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#d97706" strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />
          ) : null}
          {forecast?.length && boundary ? <ReferenceLine x={boundary} stroke="#94a3b8" strokeDasharray="2 2" label={{ value: "now", fontSize: 10, fill: "#64748b" }} /> : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Several skills over the same periods, for the Trends comparison view. */
export function MultiLineChart({ series, height = 340 }: { series: SeriesResponse; height?: number }) {
  const data = useMemo(() => series.periods.map((period, i) => {
    const row: Record<string, string | number | null> = { period };
    series.series.forEach((s) => { row[s.name] = s.frequency[i] ?? null; });
    return row;
  }), [series]);
  return (
    <div role="img" aria-label="Comparison of skill demand over time">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="period" tick={AXIS} tickFormatter={periodTick} interval={tickEvery(data.length)} />
          <YAxis tick={AXIS} tickFormatter={(v) => pct(v, 0)} width={48} />
          <Tooltip formatter={(v: number) => pct(v, 1)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.series.map((s, i) => (
            <Line key={s.skill_id} type="monotone" dataKey={s.name} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Points contributed by each component of the obsolescence score. */
export function ScoreBreakdownChart({ components }: { components: (ScoreComponent & { component?: string })[] }) {
  const data = components.filter((c) => c.risk !== null).map((c) => ({ name: c.label, points: Number(c.points.toFixed(1)), max: Number((c.weight * 100).toFixed(1)) }));
  return (
    <div role="img" aria-label="Bar chart of how many points each component adds to the obsolescence score">
      <ResponsiveContainer width="100%" height={Math.max(180, data.length * 38)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" tick={AXIS} domain={[0, 25]} />
          <YAxis type="category" dataKey="name" tick={AXIS} width={150} />
          <Tooltip formatter={(v: number, _n, item) => [`${v} of ${(item.payload as { max: number }).max} possible points`, "Contribution"]} />
          <Bar dataKey="points" radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.name} fill={d.points / d.max >= 0.66 ? "#dc2626" : d.points / d.max >= 0.33 ? "#f59e0b" : "#16a34a"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Obsolescence score vs current demand, coloured by risk band. */
export function RiskScatter({ points, onSelect, height = 380 }: { points: RiskPoint[]; onSelect?: (id: number) => void; height?: number }) {
  const groups = useMemo(() => {
    const out: Record<string, { x: number; y: number; name: string; id: number; status: string }[]> = { LOW: [], MEDIUM: [], HIGH: [], CRITICAL: [] };
    points.forEach((p) => {
      if (p.obsolescence_score === null || p.current_demand === null || !p.risk_level) return;
      out[p.risk_level].push({ x: p.current_demand * 100, y: p.obsolescence_score, name: p.name, id: p.skill_id, status: STATUS_LABELS[p.trend_status] });
    });
    return out;
  }, [points]);
  return (
    <div role="img" aria-label="Scatter plot of obsolescence score against current demand for every skill">
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 12, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis type="number" dataKey="x" name="Demand" unit="%" scale="sqrt" domain={[0, "auto"]} tick={AXIS}
            label={{ value: "Current demand (% of postings, sqrt scale)", position: "insideBottom", offset: -6, fontSize: 11, fill: "#64748b" }} />
          <YAxis type="number" dataKey="y" name="Score" domain={[0, 100]} tick={AXIS} width={40}
            label={{ value: "Obsolescence score", angle: -90, position: "insideLeft", fontSize: 11, fill: "#64748b" }} />
          <ZAxis range={[50, 50]} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ active, payload }) => {
            const p = active && payload?.[0]?.payload as { name: string; x: number; y: number; status: string } | undefined;
            return p ? (
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow">
                <p className="font-semibold text-slate-900">{p.name}</p>
                <p>Demand {p.x.toFixed(1)}% - score {p.y.toFixed(0)} - {p.status}</p>
              </div>
            ) : null;
          }} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map((lvl) => (
            <Scatter key={lvl} name={lvl[0] + lvl.slice(1).toLowerCase()} data={groups[lvl]} fill={RISK_COLORS[lvl]} fillOpacity={0.75}
              onClick={(d: { id?: number }) => d.id && onSelect?.(d.id)} cursor="pointer" isAnimationActive={false} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Stacked bars: how many skills of each trend status per category. */
export function CategoryStatusChart({ items, height = 360 }: { items: CategorySummary[]; height?: number }) {
  const statuses = ["emerging", "growing", "stable", "declining", "at_risk"] as const;
  const data = items.map((c) => ({ category: c.category, ...Object.fromEntries(statuses.map((s) => [s, c.status_counts[s] ?? 0])) }));
  return (
    <div role="img" aria-label="Stacked bar chart of trend statuses per skill category">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" tick={AXIS} allowDecimals={false} />
          <YAxis type="category" dataKey="category" tick={AXIS} width={140} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v: string) => STATUS_LABELS[v as keyof typeof STATUS_LABELS] ?? v} />
          {statuses.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={STATUS_COLORS[s]} isAnimationActive={false} name={s} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function YearBars({ data, height = 220 }: { data: { year: number; postings: number }[]; height?: number }) {
  return (
    <div role="img" aria-label="Bar chart of job postings per year">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="year" tick={AXIS} />
          <YAxis tick={AXIS} width={44} />
          <Tooltip formatter={(v: number) => [v.toLocaleString(), "Postings"]} />
          <Bar dataKey="postings" fill="#6366f1" radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Colour-scaled table: share of postings per group (rows) and skill (columns). */
export function Heatmap({ groups, skills, cells }: {
  groups: string[]; skills: { skill_id: number; name: string }[]; cells: { group: string; skill_id: number; share: number | null }[];
}) {
  const lookup = new Map(cells.map((c) => [`${c.group}|${c.skill_id}`, c.share]));
  const max = Math.max(0.01, ...cells.map((c) => c.share ?? 0));
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-separate border-spacing-1 text-xs">
        <thead>
          <tr><th className="th" />{skills.map((s) => <th key={s.skill_id} className="px-1 py-1 text-center font-medium text-slate-600">{s.name}</th>)}</tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={g}>
              <th scope="row" className="whitespace-nowrap pr-2 text-right font-medium text-slate-600">{g}</th>
              {skills.map((s) => {
                const v = lookup.get(`${g}|${s.skill_id}`) ?? null;
                return (
                  <td key={s.skill_id} className="rounded px-2 py-1.5 text-center tabular-nums"
                    style={{ background: v === null ? "#f1f5f9" : `rgba(79,70,229,${0.08 + 0.85 * (v / max)})`, color: v !== null && v / max > 0.55 ? "#fff" : "#1e293b" }}>
                    {v === null ? "-" : pct(v, 0)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
