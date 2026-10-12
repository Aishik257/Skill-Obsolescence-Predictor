import type { ReactNode } from "react";

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg className={`animate-spin text-brand-600 ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-20" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading...", height = "h-48" }: { label?: string; height?: string }) {
  return (
    <div role="status" aria-live="polite" className={`flex ${height} items-center justify-center gap-3 text-sm text-slate-500`}>
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-6 text-center">
      <p className="text-sm font-medium text-red-800">Something went wrong</p>
      <p className="max-w-xl text-sm text-red-700">{message}</p>
      {onRetry && <button type="button" className="btn-secondary" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
      <p className="text-sm font-medium text-slate-800">{title}</p>
      {hint && <p className="max-w-md text-sm text-slate-500">{hint}</p>}
      {action}
    </div>
  );
}

/** Renders loading / error / empty / content for an ApiState-like value. */
export function Async<T>({ state, children, isEmpty, empty }: {
  state: { data: T | null; loading: boolean; error: string | null; reload: () => void };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
}) {
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (state.loading && !state.data) return <Loading />;
  if (!state.data) return <Loading />;
  if (isEmpty?.(state.data)) return <>{empty ?? <EmptyState title="Nothing to show yet" />}</>;
  return (
    <div className={state.loading ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={state.loading}>
      {children(state.data)}
    </div>
  );
}
