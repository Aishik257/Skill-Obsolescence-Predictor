import type { ConfidenceLabel, RiskLevel, TrendStatus } from "@/types/api";
import { RISK_LABELS, STATUS_LABELS } from "@/utils/format";

const STATUS_STYLE: Record<TrendStatus, string> = {
  growing: "bg-green-100 text-green-800 ring-green-600/20",
  emerging: "bg-cyan-100 text-cyan-800 ring-cyan-600/20",
  stable: "bg-slate-100 text-slate-700 ring-slate-500/20",
  declining: "bg-amber-100 text-amber-800 ring-amber-600/20",
  at_risk: "bg-red-100 text-red-800 ring-red-600/20",
  insufficient_data: "bg-slate-100 text-slate-500 ring-slate-400/20",
};
const RISK_STYLE: Record<RiskLevel, string> = {
  LOW: "bg-green-100 text-green-800 ring-green-600/20",
  MEDIUM: "bg-yellow-100 text-yellow-800 ring-yellow-600/20",
  HIGH: "bg-orange-100 text-orange-800 ring-orange-600/20",
  CRITICAL: "bg-red-100 text-red-800 ring-red-600/20",
};
const CONF_STYLE: Record<ConfidenceLabel, string> = {
  High: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  Medium: "bg-sky-50 text-sky-700 ring-sky-600/20",
  Low: "bg-slate-100 text-slate-600 ring-slate-500/20",
};
const base = "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";

export function StatusBadge({ status }: { status: TrendStatus | null | undefined }) {
  if (!status) return <span className="text-slate-400">-</span>;
  return <span className={`${base} ${STATUS_STYLE[status]}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function RiskBadge({ level }: { level: RiskLevel | null | undefined }) {
  if (!level) return <span className="text-slate-400">-</span>;
  return <span className={`${base} ${RISK_STYLE[level]}`}>{RISK_LABELS[level]}</span>;
}

export function ConfidenceBadge({ label, value }: { label: ConfidenceLabel | null | undefined; value?: number | null }) {
  if (!label) return <span className="text-slate-400">-</span>;
  return (
    <span className={`${base} ${CONF_STYLE[label]}`} title={value != null ? `Confidence ${(value * 100).toFixed(0)}%` : undefined}>
      {label}
    </span>
  );
}

export function ScoreBar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="text-slate-400">-</span>;
  const color = value >= 70 ? "bg-red-500" : value >= 50 ? "bg-orange-500" : value >= 30 ? "bg-yellow-400" : "bg-green-500";
  return (
    <div className="flex items-center gap-2" title={`Obsolescence score ${value.toFixed(0)} / 100`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200" role="presentation">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
      <span className="w-7 text-right text-sm tabular-nums">{value.toFixed(0)}</span>
    </div>
  );
}
