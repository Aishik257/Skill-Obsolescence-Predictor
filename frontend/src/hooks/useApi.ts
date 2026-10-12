import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Runs an async loader whenever `deps` change. Stale responses are ignored, so quickly changing filters
 * can never show data for an older selection. `enabled=false` skips the request.
 */
export function useApi<T>(loader: (signal: AbortSignal) => Promise<T>, deps: unknown[], enabled = true): ApiState<T> {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null, loading: enabled, error: null,
  });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, loading: false }));
      return;
    }
    const ctrl = new AbortController();
    setState((s) => ({ data: s.data, loading: true, error: null }));
    loaderRef.current(ctrl.signal)
      .then((data) => !ctrl.signal.aborted && setState({ data, loading: false, error: null }))
      .catch((err: Error) => {
        if (ctrl.signal.aborted || err.name === "AbortError") return;
        setState({ data: null, loading: false, error: err.message || "Something went wrong" });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
