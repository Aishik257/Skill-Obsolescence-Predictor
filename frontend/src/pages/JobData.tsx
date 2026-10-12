import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { api } from "@/api/endpoints";
import { Async, EmptyState, ErrorState } from "@/components/States";
import { Card, KpiCard, PageHeader } from "@/components/Ui";
import { useApi } from "@/hooks/useApi";
import type { JobRow, PipelineRun, UploadReport } from "@/types/api";
import { dateLabel, num } from "@/utils/format";

function UploadSummary({ report }: { report: UploadReport }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Rows found" value={num(report.total_records)} />
        <KpiCard label="Valid rows" value={num(report.valid_records)} tone="good" />
        <KpiCard label="Invalid rows" value={num(report.invalid_records)} tone={report.invalid_records ? "warn" : "default"} />
        <KpiCard label={report.dry_run ? "Ready to import" : "Imported"} value={num(report.dry_run ? report.valid_records : report.imported)} tone="info" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Detected columns</p>
          <p className="mt-1 text-sm text-slate-700">{report.columns_detected.join(", ") || "None detected"}</p>
          <p className="mt-2 text-xs text-slate-500">
            {num(report.duplicates_in_file)} duplicates in file · {num(report.duplicates_existing)} already in dataset · {num(report.missing_descriptions)} missing descriptions · {num(report.invalid_dates)} invalid dates
          </p>
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Date range</p>
          <p className="mt-1 text-sm text-slate-700">{dateLabel(report.date_range.min)} - {dateLabel(report.date_range.max)}</p>
          {report.warnings.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs text-amber-800">{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
        </div>
      </div>
      {report.errors.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-sm font-medium text-amber-900">Rows needing attention</p>
          <ul className="mt-2 max-h-40 list-disc space-y-1 overflow-y-auto pl-5 text-xs text-amber-900">
            {report.errors.slice(0, 30).map((error, index) => <li key={`${error.row}-${index}`}>Row {error.row}: {error.reason}{error.detail ? ` - ${error.detail}` : ""}</li>)}
          </ul>
          {report.errors.length > 30 && <p className="mt-2 text-xs text-amber-800">Showing the first 30 of {report.errors.length} row issues.</p>}
        </div>
      )}
    </div>
  );
}

function RecentJobs({ items }: { items: JobRow[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">No job postings have been imported.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200">
        <thead><tr><th className="th">Title</th><th className="th">Company</th><th className="th">Role</th><th className="th">Posted</th><th className="th">Skills</th></tr></thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((job) => (
            <tr key={job.id}>
              <td className="td font-medium">{job.title}</td><td className="td">{job.company}</td>
              <td className="td">{job.role ?? "-"}</td><td className="td">{dateLabel(job.posted_date)}</td>
              <td className="td tabular-nums">{num(job.skills_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PipelineLog({ run }: { run: PipelineRun }) {
  const log = run.log ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-800">
          {run.status === "running" ? `Working: ${run.step || "starting"}` : run.status === "completed" ? "Pipeline completed" : "Pipeline failed"}
        </p>
        <span className="text-sm tabular-nums text-slate-600">{Math.round(run.progress)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="Pipeline progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(run.progress)}>
        <div className={`h-full transition-all ${run.status === "failed" ? "bg-red-500" : "bg-brand-600"}`} style={{ width: `${Math.min(100, Math.max(0, run.progress))}%` }} />
      </div>
      {run.error && <p role="alert" className="text-sm text-red-700">{run.error}</p>}
      {run.result && <p className="text-xs text-slate-600">
        {num(run.result.jobs_processed)} postings processed · {num(run.result.skills_detected)} skills detected · {num(run.result.predictions_generated)} predictions · {run.result.duration_seconds != null ? `${num(run.result.duration_seconds, 1)} seconds` : ""}
      </p>}
      {log.length > 0 && (
        <ol className="max-h-48 space-y-1 overflow-y-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
          {log.slice(-20).map((entry, index) => <li key={`${entry.t}-${index}`}><span className="font-medium text-slate-700">{entry.stage}:</span> {entry.message}</li>)}
        </ol>
      )}
    </div>
  );
}

export default function JobData() {
  const stats = useApi(() => api.jobStats(), []);
  const runs = useApi(() => api.pipelineRuns(8), []);
  const jobs = useApi(() => api.jobs({ page: 1, page_size: 8 }), []);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<UploadReport | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<PipelineRun | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!pipeline || pipeline.status !== "running") return;
    let cancelled = false;
    let pending = false;
    const poll = async () => {
      if (pending || cancelled) return;
      pending = true;
      try {
        const current = await api.pipelineStatus(pipeline.run_id);
        if (cancelled) return;
        setPipeline(current);
        setPipelineError(null);
        if (current.status !== "running") {
          stats.reload();
          runs.reload();
        }
      } catch (error) {
        if (!cancelled) setPipelineError(error instanceof Error ? error.message : "Could not read pipeline progress.");
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [pipeline?.run_id, pipeline?.status, stats.reload, runs.reload]);

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    setReport(null);
    setUploadError(null);
  }

  async function validate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setReport(null);
    try {
      setReport(await api.uploadJobs(file, true));
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "CSV validation failed.");
    } finally {
      setUploading(false);
    }
  }

  async function importFile() {
    if (!file || !report?.dry_run || report.valid_records < 1) return;
    setUploading(true);
    setUploadError(null);
    try {
      const imported = await api.uploadJobs(file, false);
      setReport(imported);
      stats.reload();
      jobs.reload();
      runs.reload();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "CSV import failed.");
    } finally {
      setUploading(false);
    }
  }

  async function runPipeline() {
    setStarting(true);
    setPipelineError(null);
    try {
      const response = await api.runPipeline("run-all", true);
      if (response.run_id === undefined) throw new Error("The API did not return a pipeline run ID.");
      setPipeline({ run_id: response.run_id, kind: "run-all", status: "running", step: "starting", progress: 0,
        started_at: null, finished_at: null, result: null, error: null, log: [] });
    } catch (error) {
      setPipelineError(error instanceof Error ? error.message : "Could not start the analysis pipeline.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <PageHeader title="Job data" subtitle="Import job postings, inspect the dataset and run the analysis pipeline that powers trends, forecasts and recommendations." />
      <div className="space-y-5">
        <Async state={stats}>
          {(data) => (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <KpiCard label="Postings" value={num(data.total_postings)} hint={`${dateLabel(data.date_min)} - ${dateLabel(data.date_max)}`} />
              <KpiCard label="Active postings" value={num(data.active_postings)} />
              <KpiCard label="Duplicates" value={num(data.duplicates)} />
              <KpiCard label="Skill links" value={num(data.skills_extracted_links)} />
              <KpiCard label="Pending cleaning" value={num(data.pending_cleaning)} tone={data.pending_cleaning ? "warn" : "good"} />
              <KpiCard label="Pending extraction" value={num(data.pending_extraction)} tone={data.pending_extraction ? "warn" : "good"} />
            </div>
          )}
        </Async>

        <Card title="Upload job postings" subtitle="Select a CSV to validate it first. Import is enabled only after a successful dry run with valid rows.">
          <form onSubmit={validate} className="flex flex-wrap items-end gap-3">
            <div className="min-w-[16rem] flex-1">
              <label htmlFor="job-csv" className="mb-1 block text-sm font-medium text-slate-700">CSV file</label>
              <input id="job-csv" className="input file:mr-3 file:rounded-md file:border-0 file:bg-brand-50 file:px-3 file:py-1 file:text-sm file:font-medium file:text-brand-700" type="file" accept=".csv,text/csv" onChange={selectFile} />
              {file && <p className="mt-1 text-xs text-slate-500">{file.name} · {num(file.size)} bytes</p>}
            </div>
            <button type="submit" className="btn-primary" disabled={!file || uploading}>{uploading ? "Checking..." : "Validate CSV"}</button>
            {report?.dry_run && <button type="button" className="btn-secondary" onClick={() => void importFile()} disabled={uploading || report.valid_records < 1}>
              {uploading ? "Importing..." : `Import ${num(report.valid_records)} valid rows`}
            </button>}
          </form>
          {uploadError && <div className="mt-4"><ErrorState message={uploadError} /></div>}
          {report && <div className="mt-5 border-t border-slate-100 pt-4"><UploadSummary report={report} /></div>}
          {report && !report.dry_run && report.imported > 0 && <p className="mt-3 text-sm font-medium text-green-700">Import complete. The dataset has been refreshed; run the pipeline to update analysis results.</p>}
        </Card>

        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Analysis pipeline" subtitle="Clean, extract skills, analyse trends, train forecasts and update predictions.">
            {pipeline ? <PipelineLog run={pipeline} /> : <p className="text-sm text-slate-600">Run all analysis stages on the current dataset. You can continue monitoring this page while the job runs.</p>}
            {pipelineError && <p role="alert" className="mt-3 text-sm text-red-700">{pipelineError}</p>}
            <button type="button" className="btn-primary mt-4" onClick={() => void runPipeline()}
              disabled={starting || pipeline?.status === "running" || (stats.data?.total_postings ?? 0) === 0}>
              {starting ? "Starting..." : pipeline?.status === "running" ? "Pipeline running..." : "Run full pipeline"}
            </button>
          </Card>
          <Async state={runs}>
            {(data) => (
              <Card title="Recent pipeline runs">
                {data.items.length ? (
                  <ul className="divide-y divide-slate-100">
                    {data.items.map((run) => (
                      <li key={run.run_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                        <div><p className="font-medium text-slate-800">{run.kind}</p><p className="text-xs text-slate-500">{dateLabel(run.started_at)} · {run.step}</p></div>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${run.status === "completed" ? "bg-green-100 text-green-800" : run.status === "failed" ? "bg-red-100 text-red-800" : "bg-sky-100 text-sky-800"}`}>{run.status} · {Math.round(run.progress)}%</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-sm text-slate-500">No pipeline runs recorded yet.</p>}
              </Card>
            )}
          </Async>
        </div>
        <Async state={jobs}>
          {(data) => <Card title="Recently imported postings" subtitle={`Showing ${data.items.length} of ${num(data.total)} postings.`}>
            {data.items.length ? <RecentJobs items={data.items} /> : <EmptyState title="No job data yet" hint="Upload a CSV above or use the seed script to load the sample dataset." />}
          </Card>}
        </Async>
      </div>
    </>
  );
}
