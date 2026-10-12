import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

/** Global filters. They live in the URL (?role=...&year=...) so any view can be bookmarked or shared. */
export const FILTER_KEYS = ["role", "industry", "country", "region", "year", "category", "status", "risk"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string>>;

/** Filters that slice the *data* (postings); the rest only narrow lists of skills. */
export const SCOPE_KEYS: FilterKey[] = ["role", "industry", "country", "region", "year"];

interface FilterContextValue {
  filters: Filters;
  /** Scope filters only - accepted by every analytics endpoint. */
  scope: Filters;
  set: (key: FilterKey, value: string) => void;
  clear: () => void;
  activeCount: number;
}

const FilterContext = createContext<FilterContextValue | null>(null);

export function FilterProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();

  const filters = useMemo(() => {
    const out: Filters = {};
    for (const k of FILTER_KEYS) {
      const v = params.get(k);
      if (v) out[k] = v;
    }
    return out;
  }, [params]);

  const set = useCallback((key: FilterKey, value: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      next.delete("page");
      return next;
    }, { replace: true });
  }, [setParams]);

  const clear = useCallback(() => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      FILTER_KEYS.forEach((k) => next.delete(k));
      next.delete("page");
      return next;
    }, { replace: true });
  }, [setParams]);

  const value = useMemo<FilterContextValue>(() => {
    const scope: Filters = {};
    for (const k of SCOPE_KEYS) if (filters[k]) scope[k] = filters[k];
    return { filters, scope, set, clear, activeCount: Object.keys(filters).length };
  }, [filters, set, clear]);

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used inside <FilterProvider>");
  return ctx;
}
