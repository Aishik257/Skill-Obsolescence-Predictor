import type { RiskLevel, TrendStatus } from "@/types/api";

export const pct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(digits)}%`;

/** Signed percentage for changes: +12.3% / -4.0%. */
export const signedPct = (v: number | null | undefined, digits = 0): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const p = v * 100;
  return `${p >= 0 ? "+" : ""}${Math.abs(p) >= 1000 ? p.toFixed(0) : p.toFixed(digits)}%`;
};

export const num = (v: number | null | undefined, digits = 0): string =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : v.toLocaleString("en-US", { maximumFractionDigits: digits });

export const score = (v: number | null | undefined): string => (v === null || v === undefined ? "-" : v.toFixed(0));

export const dateLabel = (iso: string | null | undefined): string => {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
};

export const pValue = (p: number | null | undefined): string =>
  p === null || p === undefined ? "-" : p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;

export const STATUS_LABELS: Record<TrendStatus, string> = {
  growing: "Growing", stable: "Stable", declining: "Declining", at_risk: "At risk", emerging: "Emerging", insufficient_data: "Insufficient data",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  LOW: "Low risk", MEDIUM: "Medium risk", HIGH: "High risk", CRITICAL: "Critical risk",
};

export const STATUS_COLORS: Record<TrendStatus, string> = {
  growing: "#16a34a", emerging: "#0891b2", stable: "#64748b", declining: "#f59e0b", at_risk: "#dc2626", insufficient_data: "#94a3b8",
};

export const RISK_COLORS: Record<RiskLevel, string> = { LOW: "#16a34a", MEDIUM: "#eab308", HIGH: "#f97316", CRITICAL: "#dc2626" };

export const MODEL_LABELS: Record<string, string> = {
  naive_mean: "Naive mean", linear_trend: "Linear trend", damped_holt: "Damped Holt", ar_ridge: "Ridge autoregression",
};

export const modelLabel = (m: string | null | undefined): string => (m ? MODEL_LABELS[m] ?? m : "-");

/** "2024-Q3" -> "Q3 '24" for compact axis ticks. */
export const periodTick = (p: string): string => {
  const m = /^(\d{4})-Q(\d)$/.exec(p);
  return m ? `Q${m[2]} '${m[1].slice(2)}` : p;
};

export const DIMENSION_LABELS: Record<string, string> = { role: "Job role", industry: "Industry", country: "Country", region: "Region" };
