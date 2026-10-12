import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/endpoints";
import { useDebounce } from "@/hooks/useDebounce";
import type { SearchResponse } from "@/types/api";
import { StatusBadge } from "./Badges";

/** Global skill search with alias matching ("k8s" finds Kubernetes). Keyboard accessible. */
export default function SkillSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounce(q.trim(), 200);
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (debounced.length < 1) { setResult(null); setError(null); return; }
    const ctrl = new AbortController();
    setLoading(true);
    api.searchSkills(debounced, 8, ctrl.signal)
      .then((r) => { setResult(r); setError(null); setActive(0); })
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); })
      .finally(() => !ctrl.signal.aborted && setLoading(false));
    return () => ctrl.abort();
  }, [debounced]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const go = (id: number) => { setOpen(false); setQ(""); nav(`/skills/${id}`); };
  const hits = result?.results ?? [];

  return (
    <div ref={box} className="relative w-full max-w-md">
      <label htmlFor="global-search" className="sr-only">Search skills</label>
      <input id="global-search" type="search" className="input" placeholder="Search skills or aliases (e.g. k8s, react)..." autoComplete="off"
        role="combobox" aria-expanded={open} aria-controls="search-results" value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && hits[active]) go(hits[active].skill_id);
          else if (e.key === "Escape") setOpen(false);
        }} />
      {open && debounced && (
        <ul id="search-results" role="listbox" className="absolute z-30 mt-1 max-h-96 w-full overflow-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
          {loading && !result && <li className="px-3 py-2 text-sm text-slate-500">Searching...</li>}
          {error && <li role="alert" className="px-3 py-2 text-sm text-red-700">{error}</li>}
          {!loading && !error && hits.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">No skills match "{debounced}".</li>}
          {hits.map((s, i) => (
            <li key={s.skill_id} role="option" aria-selected={i === active}>
              <button type="button" onMouseEnter={() => setActive(i)} onClick={() => go(s.skill_id)}
                className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm ${i === active ? "bg-brand-50" : ""}`}>
                <span><span className="font-medium text-slate-900">{s.name}</span> <span className="text-xs text-slate-500">{s.category}</span></span>
                <StatusBadge status={s.trend_status} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
