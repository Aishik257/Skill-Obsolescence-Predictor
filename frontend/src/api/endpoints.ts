import type {
  BreakdownResponse, CategorySummary, Candidate, DemandByResponse, FilterOptions, ForecastResponse, ForecastRow,
  HistoryResponse, JobRow, JobStats, LearningPath, ModelPerformance, Overview, Page, PipelineRun, PipelineSummary,
  RiskPoint, SearchResponse, SeriesResponse, SkillDetail, SkillGap, SkillSummary, UploadReport,
} from "@/types/api";
import { http, type Params } from "./client";

/** Filters shared by most analytical endpoints. */
export type ScopeFilters = Params;

export const api = {
  health: () => http.get<{ status: string }>("/health"),
  overview: (f?: ScopeFilters) => http.get<Overview>("/analytics/overview", f),
  filterOptions: () => http.get<FilterOptions>("/analytics/filters"),
  categories: (f?: ScopeFilters) => http.get<{ items: CategorySummary[]; scope: string }>("/analytics/categories", f),
  riskMap: (f?: ScopeFilters) => http.get<{ items: RiskPoint[]; scope: string }>("/analytics/risk-map", f),
  modelPerformance: () => http.get<ModelPerformance>("/analytics/model-performance"),
  demandBy: (p: Params) => http.get<DemandByResponse>("/analytics/demand-by", p),
  candidates: (p?: Params) => http.get<{ items: Candidate[]; note: string }>("/analytics/candidates", p),

  skills: (p?: Params) => http.get<Page<SkillSummary>>("/skills", p),
  searchSkills: (q: string, limit = 8, signal?: AbortSignal) => http.get<SearchResponse>("/skills/search", { q, limit }, signal),
  skill: (id: number | string, f?: ScopeFilters) => http.get<SkillDetail>(`/skills/${id}`, f),
  skillHistory: (id: number | string, p?: Params) => http.get<HistoryResponse>(`/skills/${id}/history`, p),
  skillForecast: (id: number | string, f?: ScopeFilters) => http.get<ForecastResponse>(`/skills/${id}/forecast`, f),
  skillBreakdown: (id: number | string, dimension: string, f?: ScopeFilters) =>
    http.get<BreakdownResponse>(`/skills/${id}/breakdown`, { dimension, ...f }),

  trends: (p?: Params) => http.get<Page<SkillSummary>>("/trends", p),
  trendList: (kind: "growing" | "declining" | "emerging", p?: Params) =>
    http.get<{ items: SkillSummary[]; total: number }>(`/trends/${kind}`, p),
  series: (skillIds: number[], p?: Params) => http.get<SeriesResponse>("/trends/series", { skill_ids: skillIds.join(","), ...p }),

  forecasts: (p?: Params) => http.get<Page<ForecastRow>>("/forecasts", p),
  predictions: (p?: Params) => http.get<Page<SkillSummary>>("/predictions", p),
  highRisk: (p?: Params) => http.get<{ items: SkillSummary[]; total: number }>("/predictions/high-risk", p),

  jobs: (p?: Params) => http.get<Page<JobRow>>("/jobs", p),
  jobStats: () => http.get<JobStats>("/jobs/stats"),
  uploadJobs: (file: File, dryRun: boolean) => http.upload<UploadReport>("/jobs/upload", file, { dry_run: dryRun }),

  runPipeline: (kind: string, background = true) =>
    http.post<{ run_id?: number } & Partial<PipelineSummary>>(`/pipeline/${kind}`, undefined, { background }),
  pipelineStatus: (runId?: number) => http.get<PipelineRun>("/pipeline/status", { run_id: runId }),
  pipelineRuns: (limit = 8) => http.get<{ items: PipelineRun[] }>("/pipeline/runs", { limit }),

  skillGap: (role: string | null, skills: string[]) => http.post<SkillGap>("/recommendations/skill-gap", { role, skills }),
  learningPath: (role: string | null, skills: string[], limit = 12) =>
    http.post<LearningPath>("/recommendations/learning-path", { role, skills, limit }),
};
