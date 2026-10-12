import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/endpoints";
import SkillSearch from "@/components/SkillSearch";
import FilterBar from "@/components/FilterBar";
import Dashboard from "@/pages/Dashboard";
import JobData from "@/pages/JobData";
import SkillDetailPage from "@/pages/SkillDetail";
import { FilterProvider } from "@/hooks/useFilters";
import type {
  BreakdownResponse, FilterOptions, ForecastResponse, HistoryResponse, JobRow, JobStats,
  Overview, PipelineRun, SkillDetail, SkillSummary, UploadReport,
} from "@/types/api";

const skill: SkillSummary = {
  skill_id: 7, name: "Python", slug: "python", category: "Programming languages", aliases: ["py"],
  scope: "global", trend_status: "growing", status_label: "Growing", current_demand: 0.25, growth_rate: 0.12,
  yoy_growth: 0.08, cagr: 0.1, momentum: 0.04, future_demand: 0.3, forecast_horizon: 8, forecast_status: "ok",
  forecast_model: "linear_trend", obsolescence_score: 12, risk_level: "LOW", confidence: 0.8,
  confidence_label: "High", model_version: "test", prediction_date: "2025-01-01",
};

const filterOptions: FilterOptions = {
  roles: [{ value: "Data Scientist", postings: 120 }], industries: [{ value: "FinTech", postings: 40 }],
  countries: [], regions: [], years: [2025], categories: ["Programming languages"], statuses: ["growing"],
  risk_levels: ["LOW"], date_min: "2024-01-01", date_max: "2025-12-31",
};

const noDataOverview: Overview = {
  scope: "global", filters: {}, kpis: {
    total_jobs: 0, unique_skills: 0, growing: 0, declining: 0, at_risk: 0,
    emerging: 0, stable: 0, insufficient_data: 0,
  }, date_range: { min: null, max: null }, postings_by_year: [], top_growing: [],
  top_declining: [], highest_risk: [], emerging: [],
  market_outlook: { headline: "No data", bullets: [] }, limitations: [], has_data: false, has_predictions: false,
};

const skillDetail: SkillDetail = {
  ...skill,
  description: "A general-purpose programming language.",
  explanation: {
    as_of: "2025-01-01", rules: [], status: "growing", bullets: ["Demand is increasing."], summary: "Demand is increasing.",
    category: skill.category, headline: "Growing skill", risk_text: "Low market-demand risk.", limitations: [],
    score_notes: [], status_label: "Growing", recommendation: "Continue monitoring.", score_breakdown: [],
    confidence_reasons: ["Sufficient data."],
  },
  components: {},
  metrics: { n_quarters: 20, total_mentions: 200, total_jobs: 800, first_demand: 0.1, current_demand: 0.25 },
  top_roles: [], related_skills: [], replacements: [],
};

const history: HistoryResponse = {
  skill_id: 7, name: "Python", granularity: "quarter", empty: true, points: [], total_jobs: 0,
  total_mentions: 0, metrics: null, ma_window: 4, filters: {},
};

const forecast: ForecastResponse = {
  skill_id: 7, name: "Python", scope: "global", status: "insufficient_data",
  message: "Not enough historical data.", model: null, model_version: null, history: [], models: [],
  forecast: [], current_demand: null, horizons: {},
};

const breakdown: BreakdownResponse = { skill_id: 7, dimension: "role", groups: [], filters: {} };

const jobStats: JobStats = {
  total_postings: 0, duplicates: 0, active_postings: 0, pending_cleaning: 0, pending_extraction: 0,
  skills_extracted_links: 0, date_min: null, date_max: null, postings_by_year: [],
  has_predictions: false, last_prediction: null, analysis_stale: false, last_run: null,
};

const job: JobRow = {
  id: 1, source_job_id: "sample-1", title: "Data analyst", company: "Example", location: null,
  industry: "FinTech", role: "Data Scientist", country: null, posted_date: "2025-01-01",
  is_duplicate: false, skills_count: 2, source: "upload",
};

const uploadReport: UploadReport = {
  file_name: "jobs.csv", dry_run: true, total_records: 1, valid_records: 1, imported: 0,
  duplicates_removed: 0, duplicates_in_file: 0, duplicates_existing: 0, invalid_records: 0,
  missing_descriptions: 0, missing_dates: 0, invalid_dates: 0, malformed_records: 0,
  missing_required_fields: 0, date_range: { min: "2025-01-01", max: "2025-01-01" },
  columns_detected: ["title", "company", "description", "posted_date"], warnings: [], errors: [],
};

function renderDashboard(initialEntry = "/") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FilterProvider><Dashboard /></FilterProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("dashboard and filters", () => {
  it("shows its loading state and then the empty-data action", async () => {
    let resolveOverview: (data: Overview) => void = () => {};
    vi.spyOn(api, "overview").mockReturnValue(new Promise((resolve) => { resolveOverview = resolve; }));
    vi.spyOn(api, "filterOptions").mockResolvedValue(filterOptions);
    renderDashboard();

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    resolveOverview(noDataOverview);
    expect(await screen.findByText("No job postings yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Job data" })).toHaveAttribute("href", "/data");
  });

  it("explains sparse filtered data instead of asking to rerun the pipeline", async () => {
    const sparseSlice: Overview = {
      ...noDataOverview,
      scope: "filtered",
      filters: { role: "Software Engineer", industry: "Technology", country: "India" },
      kpis: { ...noDataOverview.kpis, total_jobs: 102, insufficient_data: 159 },
      date_range: { min: "2019-01-13", max: "2026-10-05" },
      has_data: true,
    };
    vi.spyOn(api, "overview").mockResolvedValue(sparseSlice);
    vi.spyOn(api, "filterOptions").mockResolvedValue(filterOptions);
    renderDashboard("/?role=Software%20Engineer&industry=Technology&country=India");

    expect(await screen.findByText("Not enough data for trend analysis with these filters")).toBeInTheDocument();
    expect(screen.getByText("102", { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/at least 8 usable quarters/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Run the analysis" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters and broaden the view" })).toBeInTheDocument();
  });

  it("reports dashboard API errors with a retry action", async () => {
    vi.spyOn(api, "overview").mockRejectedValue(new Error("API unavailable"));
    vi.spyOn(api, "filterOptions").mockResolvedValue(filterOptions);
    renderDashboard();
    expect(await screen.findByRole("alert")).toHaveTextContent("API unavailable");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("updates URL filters without discarding other filters", async () => {
    vi.spyOn(api, "filterOptions").mockResolvedValue(filterOptions);
    function Location() {
      const location = useLocation();
      return <output aria-label="Current query">{location.search}</output>;
    }
    render(
      <MemoryRouter initialEntries={["/?industry=FinTech&page=3"]}>
        <FilterProvider><FilterBar show={["role"]} /><Location /></FilterProvider>
      </MemoryRouter>,
    );

    await userEvent.selectOptions(await screen.findByLabelText("Role"), "Data Scientist");
    await waitFor(() => expect(screen.getByLabelText("Current query")).toHaveTextContent("industry=FinTech"));
    expect(screen.getByLabelText("Current query")).toHaveTextContent("role=Data");
    expect(screen.getByLabelText("Current query")).not.toHaveTextContent("page=3");
  });
});

describe("global skill search", () => {
  it("finds a skill and navigates to its detail route", async () => {
    vi.spyOn(api, "searchSkills").mockResolvedValue({ query: "python", results: [skill], role_views: [] });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<SkillSearch />} />
          <Route path="/skills/:id" element={<p>Opened skill detail</p>} />
        </Routes>
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByRole("combobox", { name: "Search skills" }), "python");
    await userEvent.click(await screen.findByRole("button", { name: /Python/ }));
    expect(await screen.findByText("Opened skill detail")).toBeInTheDocument();
  });
});

describe("skill detail", () => {
  it("loads a skill and handles sections with no history", async () => {
    vi.spyOn(api, "skill").mockResolvedValue(skillDetail);
    vi.spyOn(api, "skillHistory").mockResolvedValue(history);
    vi.spyOn(api, "skillForecast").mockResolvedValue(forecast);
    vi.spyOn(api, "skillBreakdown").mockResolvedValue(breakdown);
    vi.spyOn(api, "filterOptions").mockResolvedValue(filterOptions);
    render(
      <MemoryRouter initialEntries={["/skills/7"]}>
        <FilterProvider><Routes><Route path="/skills/:id" element={<SkillDetailPage />} /></Routes></FilterProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Python" })).toBeInTheDocument();
    expect(await screen.findByText("Insufficient historical data")).toBeInTheDocument();
    expect(screen.getByText("A general-purpose programming language.")).toBeInTheDocument();
  });
});

describe("job data CSV import", () => {
  it("validates a CSV before importing the valid rows", async () => {
    const reportAfterImport = { ...uploadReport, dry_run: false, imported: 1 };
    const upload = vi.spyOn(api, "uploadJobs").mockResolvedValueOnce(uploadReport).mockResolvedValueOnce(reportAfterImport);
    vi.spyOn(api, "jobStats").mockResolvedValue(jobStats);
    vi.spyOn(api, "pipelineRuns").mockResolvedValue({ items: [] as PipelineRun[] });
    vi.spyOn(api, "jobs").mockResolvedValue({ items: [job], total: 1, page: 1, page_size: 8, pages: 1 });
    render(
      <MemoryRouter><JobData /></MemoryRouter>,
    );

    const file = new File(["title,company\nAnalyst,Example"], "jobs.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });
    await userEvent.click(screen.getByRole("button", { name: "Validate CSV" }));
    expect(await screen.findByText("Detected columns")).toBeInTheDocument();
    expect(upload).toHaveBeenNthCalledWith(1, file, true);

    await userEvent.click(screen.getByRole("button", { name: "Import 1 valid rows" }));
    expect(await screen.findByText(/Import complete/)).toBeInTheDocument();
    expect(upload).toHaveBeenNthCalledWith(2, file, false);
  });
});
