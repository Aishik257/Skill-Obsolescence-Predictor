/** Types mirroring the SkillPulse API responses (see backend/app/api/routes). */

export type TrendStatus = "growing" | "stable" | "declining" | "at_risk" | "emerging" | "insufficient_data";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type ConfidenceLabel = "High" | "Medium" | "Low";

export interface SkillSummary {
  skill_id: number;
  name: string;
  slug: string;
  category: string;
  aliases: string[];
  scope: string;
  trend_status: TrendStatus;
  status_label: string;
  current_demand: number | null;
  growth_rate: number | null;
  yoy_growth: number | null;
  cagr: number | null;
  momentum: number | null;
  future_demand: number | null;
  forecast_horizon: number | null;
  forecast_status: string | null;
  forecast_model: string | null;
  obsolescence_score: number | null;
  risk_level: RiskLevel | null;
  confidence: number | null;
  confidence_label: ConfidenceLabel | null;
  model_version: string | null;
  prediction_date: string | null;
  match_score?: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  scope?: string;
  filters?: Record<string, unknown>;
}

export interface Kpis {
  total_jobs: number;
  unique_skills: number;
  growing: number;
  declining: number;
  at_risk: number;
  emerging: number;
  stable: number;
  insufficient_data: number;
}

export interface Overview {
  scope: string;
  filters: Record<string, string>;
  kpis: Kpis;
  date_range: { min: string | null; max: string | null };
  postings_by_year: { year: number; postings: number }[];
  top_growing: SkillSummary[];
  top_declining: SkillSummary[];
  highest_risk: SkillSummary[];
  emerging: SkillSummary[];
  market_outlook: { headline: string; bullets: string[] };
  limitations: string[];
  has_data: boolean;
  has_predictions: boolean;
}

export interface FilterOptions {
  roles: { value: string; postings: number }[];
  industries: { value: string; postings: number }[];
  countries: { value: string; postings: number }[];
  regions: { value: string; postings: number }[];
  years: number[];
  categories: string[];
  statuses: string[];
  risk_levels: string[];
  date_min: string | null;
  date_max: string | null;
}

export interface CategorySummary {
  category: string;
  skills: number;
  status_counts: Record<string, number>;
  avg_obsolescence_score: number | null;
  avg_current_demand: number | null;
  top_growing: string | null;
  highest_risk: string | null;
  postings_share_by_year: { year: number; share: number }[];
}

export interface RiskPoint {
  skill_id: number;
  name: string;
  category: string;
  current_demand: number | null;
  growth_rate: number | null;
  yoy_growth: number | null;
  obsolescence_score: number | null;
  risk_level: RiskLevel | null;
  trend_status: TrendStatus;
}

export interface ModelPerformance {
  available: boolean;
  model_version?: string;
  trained_at?: string;
  validation?: { method: string; horizon_quarters: number; step_quarters: number; max_folds: number;
                 min_train_quarters: number; metrics: string[]; selection: string };
  models?: { model: string; skills_evaluated: number; times_selected: number; mean_mae: number | null;
             mean_rmse: number | null; mean_mape: number | null; median_r2: number | null; rmse_vs_naive: number | null }[];
  selected_summary?: { skills_with_forecast: number; mean_rmse: number | null; mean_mape: number | null;
                       mean_mae: number | null; median_r2: number | null };
  per_skill?: { skill_id: number; name: string; model: string; mae: number | null; rmse: number | null;
                mape: number | null; r2: number | null; folds: number }[];
}

export interface HistoryPoint {
  period: string;
  jobs: number;
  mentions: number;
  frequency: number;
  moving_average?: number;
  ci_low?: number;
  ci_high?: number;
  reliable?: boolean;
}

export interface TrendMetricsDto {
  [key: string]: unknown;
  first_period?: string; last_period?: string; first_demand?: number; current_demand?: number; prev_demand?: number;
  peak_demand?: number; peak_period?: string; pp_change?: number; long_term_growth?: number; yoy_growth?: number;
  cagr?: number; momentum?: number; persistence?: number; p_long?: number; p_recent?: number; kendall_tau?: number;
  kendall_p?: number; n_quarters?: number; total_mentions?: number; total_jobs?: number; years_span?: number;
  window_first?: string; window_last?: string; current_ci?: number[];
}

export interface HistoryResponse {
  skill_id: number;
  name: string;
  granularity: string;
  empty: boolean;
  points: HistoryPoint[];
  total_jobs: number;
  total_mentions: number;
  metrics: TrendMetricsDto | null;
  ma_window: number;
  filters: Record<string, string>;
}

export interface ForecastPoint { step: number; period: string; predicted: number; lower: number; upper: number; confidence: number }
export interface ForecastHorizon { period: string; predicted: number; lower: number; upper: number; confidence: number; change: number | null }
export interface ForecastModelRow { model: string; mae: number | null; rmse: number | null; mape: number | null; r2: number | null; folds: number; selected: boolean }

export interface ForecastResponse {
  skill_id: number;
  name: string;
  scope: string;
  status: string; // ok | insufficient_data | ...
  message?: string;
  model: string | null;
  model_version: string | null;
  history: HistoryPoint[];
  models: ForecastModelRow[];
  forecast: ForecastPoint[];
  current_demand: number | null;
  horizons: Record<"1y" | "2y" | "3y", ForecastHorizon> | Record<string, never>;
}

export interface ForecastRow {
  skill_id: number;
  name: string;
  category: string;
  current_demand: number | null;
  trend_status: TrendStatus;
  risk_level: RiskLevel | null;
  status: string;
  model: string | null;
  y1: number | null; y2: number | null; y3: number | null;
  change_1y: number | null; change_2y: number | null; change_3y: number | null;
  confidence_2y: number | null;
  lower_2y: number | null; upper_2y: number | null;
}

export interface ScoreComponent { risk: number | null; label: string; value: number | null; points: number; weight: number; note?: string }

export interface Explanation {
  as_of: string;
  rules: { rule: string; detail: string; passed: boolean }[];
  status: TrendStatus;
  bullets: string[];
  summary: string;
  category: string;
  headline: string;
  risk_text: string;
  limitations: string[];
  score_notes: string[];
  status_label: string;
  recommendation: string;
  score_breakdown: (ScoreComponent & { component: string })[];
  confidence_reasons: string[];
}

export interface RelatedSkill { skill_id: number; name: string; category: string; score: number;
  details: { lift: number; together: number; share_with: number } }

export interface ReplacementCandidate { skill_id: number; name: string; category: string; score: number;
  details: { note: string; lift: number; together: number; overlap: number; correlation: number;
             components: Record<string, number>; grower_change: number; decliner_change: number; grower_pp_change: number } }

export interface SkillDetail extends SkillSummary {
  description: string | null;
  explanation: Explanation;
  components: Record<string, ScoreComponent>;
  metrics: TrendMetricsDto & { forecast?: Record<string, unknown> };
  top_roles: { role: string; share: number }[];
  related_skills: RelatedSkill[];
  replacements: ReplacementCandidate[];
}

export interface BreakdownGroup {
  group: string; jobs: number; mentions: number; overall_share: number; sufficient: boolean;
  current_demand: number | null; relevance: string; growth: number | null; yoy_growth: number | null;
  momentum: number | null; pp_change: number | null; trend_status: TrendStatus | null; status_label: string | null;
  growth_label: string | null; p_value: number | null;
}
export interface BreakdownResponse { skill_id: number; dimension: string; groups: BreakdownGroup[]; filters: Record<string, string> }

export interface SeriesResponse {
  granularity: string;
  periods: string[];
  jobs: number[];
  series: { skill_id: number; name: string; category: string; frequency: (number | null)[]; mentions: number[] }[];
  empty: boolean;
}

export interface DemandByResponse {
  dimension: string;
  groups: { group: string; postings: number }[];
  skills: { skill_id: number; name: string }[];
  cells: { group: string; skill_id: number; skill: string; share: number | null }[];
  as_of: string | null;
  empty: boolean;
}

export interface JobRow {
  id: number; source_job_id: string; title: string; company: string; location: string | null; industry: string | null;
  role: string | null; country: string | null; posted_date: string | null; is_duplicate: boolean; skills_count: number; source: string | null;
}

export interface JobStats {
  total_postings: number; duplicates: number; active_postings: number; pending_cleaning: number; pending_extraction: number;
  skills_extracted_links: number; date_min: string | null; date_max: string | null;
  postings_by_year: { year: number; postings: number }[];
  has_predictions: boolean; last_prediction: string | null; analysis_stale: boolean;
  last_run: PipelineSummary | null;
}

export interface UploadReport {
  file_name: string; dry_run: boolean; total_records: number; valid_records: number; imported: number;
  duplicates_removed: number; duplicates_in_file: number; duplicates_existing: number; invalid_records: number;
  missing_descriptions: number; missing_dates: number; invalid_dates: number; malformed_records: number;
  missing_required_fields: number; date_range: { min: string | null; max: string | null };
  columns_detected: string[]; warnings: string[]; errors: { row: number; reason: string; detail: string }[];
}

export interface PipelineSummary {
  status: string; jobs_processed?: number; skills_detected?: number; trends_calculated?: number;
  predictions_generated?: number; duration_seconds?: number; details?: Record<string, unknown>;
}

export interface PipelineRun {
  run_id: number; kind: string; status: "running" | "completed" | "failed"; step: string; progress: number;
  started_at: string | null; finished_at: string | null; result: PipelineSummary | null; error: string | null;
  log?: { t: string; stage: string; message: string }[];
}

export interface RecommendationItem {
  skill_id: number; name: string; category: string; trend_status: TrendStatus; priority_score: number;
  priority: "HIGH" | "MEDIUM" | "LOW"; role_demand: number | null; role_growth: number | null;
  forecast_change: number | null; obsolescence_score: number | null; reasons: string[];
  components: Record<string, number>; rank?: number;
}

export interface SkillGap {
  role: string | null; as_of: string; unrecognized: string[];
  strong_skills: (SkillSummary & { role_demand?: number })[];
  skills_to_strengthen: RecommendationItem[];
  emerging_to_consider: RecommendationItem[];
  at_risk_skills: SkillSummary[];
  [key: string]: unknown;
}

export interface LearningPath {
  role: string | null; as_of: string; role_postings: number; current_skills: string[]; unrecognized: string[];
  recommendations: RecommendationItem[]; method: string;
}

export interface SearchResponse { query: string; results: SkillSummary[]; role_views: { skill_id: number; name: string; skill: string; role: string; share: number }[] }

export interface Candidate { phrase: string; mentions: number; first_year: number; last_year: number;
  suggested_name: string | null; suggested_category: string | null; source: string }
