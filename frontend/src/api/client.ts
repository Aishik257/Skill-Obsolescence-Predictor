/** Thin fetch wrapper: JSON in/out, query-string building, and errors carrying the API's readable message. */

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>;

const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "/api";

export function buildQuery(params?: Params): string {
  if (!params) return "";
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

async function parse<T>(res: Response): Promise<T> {
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const msg = typeof detail === "string" ? detail
      : res.status === 0 || res.status >= 500 ? "The server hit an unexpected problem. Please try again."
      : `Request failed (${res.status})`;
    throw new ApiError(msg, res.status);
  }
  return body as T;
}

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the SkillPulse API. Check that the backend is running on port 8000.", 0);
  }
  return parse<T>(res);
}

export const http = {
  get: <T>(path: string, params?: Params, signal?: AbortSignal) => request<T>(`${path}${buildQuery(params)}`, undefined, signal),
  post: <T>(path: string, body?: unknown, params?: Params) =>
    request<T>(`${path}${buildQuery(params)}`, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  upload: <T>(path: string, file: File, params?: Params) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(`${path}${buildQuery(params)}`, { method: "POST", body: form });
  },
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
