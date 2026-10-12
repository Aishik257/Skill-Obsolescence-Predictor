import { Link } from "react-router-dom";
import type { SkillSummary } from "@/types/api";
import { pct, signedPct } from "@/utils/format";
import { ConfidenceBadge, RiskBadge, ScoreBar, StatusBadge } from "./Badges";

export type SortKey = "name" | "current_demand" | "growth_rate" | "yoy_growth" | "obsolescence_score" | "confidence" | "momentum";

export interface Sort { key: string; order: "asc" | "desc" }

function Th({ label, sortKey, sort, onSort, align = "left" }: {
  label: string; sortKey?: string; sort?: Sort; onSort?: (key: string) => void; align?: "left" | "right";
}) {
  const active = sort && sortKey === sort.key;
  const ariaSort = active ? (sort!.order === "asc" ? "ascending" : "descending") : "none";
  return (
    <th scope="col" className={`th ${align === "right" ? "text-right" : ""}`} aria-sort={sortKey ? ariaSort : undefined}>
      {sortKey && onSort ? (
        <button type="button" onClick={() => onSort(sortKey)} className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-slate-900">
          {label}<span aria-hidden className="text-[10px]">{active ? (sort!.order === "asc" ? "▲" : "▼") : ""}</span>
        </button>
      ) : label}
    </th>
  );
}

const growthTone = (v: number | null) => (v === null ? "" : v > 0.02 ? "text-green-700" : v < -0.02 ? "text-red-700" : "text-slate-600");

/** The main sortable skills table used on Skills, Trends and Predictions pages. */
export function SkillTable({ rows, sort, onSort, showForecast = true }: {
  rows: SkillSummary[]; sort?: Sort; onSort?: (key: string) => void; showForecast?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            <Th label="Skill" sortKey="name" sort={sort} onSort={onSort} />
            <Th label="Category" />
            <Th label="Demand" sortKey="current_demand" sort={sort} onSort={onSort} align="right" />
            <Th label="Long-term" sortKey="growth_rate" sort={sort} onSort={onSort} align="right" />
            <Th label="YoY" sortKey="yoy_growth" sort={sort} onSort={onSort} align="right" />
            {showForecast && <Th label="2y forecast" align="right" />}
            <Th label="Status" />
            <Th label="Score" sortKey="obsolescence_score" sort={sort} onSort={onSort} />
            <Th label="Risk" />
            <Th label="Confidence" sortKey="confidence" sort={sort} onSort={onSort} />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((s) => (
            <tr key={s.skill_id} className="hover:bg-slate-50">
              <td className="td font-medium"><Link className="text-brand-700 hover:underline" to={`/skills/${s.skill_id}`}>{s.name}</Link></td>
              <td className="td text-slate-500">{s.category}</td>
              <td className="td text-right tabular-nums" title="Share of postings mentioning the skill (trailing 4 quarters)">{pct(s.current_demand)}</td>
              <td className={`td text-right tabular-nums ${growthTone(s.growth_rate)}`}>{signedPct(s.growth_rate)}</td>
              <td className={`td text-right tabular-nums ${growthTone(s.yoy_growth)}`}>{signedPct(s.yoy_growth)}</td>
              {showForecast && <td className="td text-right tabular-nums">{pct(s.future_demand)}</td>}
              <td className="td"><StatusBadge status={s.trend_status} /></td>
              <td className="td"><ScoreBar value={s.obsolescence_score} /></td>
              <td className="td"><RiskBadge level={s.risk_level} /></td>
              <td className="td"><ConfidenceBadge label={s.confidence_label} value={s.confidence} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
