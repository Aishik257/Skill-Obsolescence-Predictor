import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { FILTER_KEYS } from "@/hooks/useFilters";
import SkillSearch from "./SkillSearch";

const NAV = [
  { to: "/", label: "Dashboard", end: true, filtered: true },
  { to: "/skills", label: "Skills", filtered: true },
  { to: "/trends", label: "Trends", filtered: true },
  { to: "/predictions", label: "Predictions", filtered: true },
  { to: "/forecasts", label: "Forecasts" },
  { to: "/analytics", label: "Analytics", filtered: true },
  { to: "/my-skills", label: "My skills" },
  { to: "/data", label: "Job data" },
  { to: "/about", label: "About & limits" },
];

export default function Layout() {
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => setMenu(false), [loc.pathname]);

  // keep the active filters when moving between filterable pages
  const params = new URLSearchParams(loc.search);
  const keep = new URLSearchParams();
  FILTER_KEYS.forEach((k) => { const v = params.get(k); if (v) keep.set(k, v); });
  const search = keep.toString() ? `?${keep.toString()}` : "";

  return (
    <div className="min-h-screen lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
      <aside className={`${menu ? "block" : "hidden"} border-b border-slate-200 bg-white lg:sticky lg:top-0 lg:block lg:h-screen lg:w-56 lg:shrink-0 lg:border-b-0 lg:border-r`}>
        <div className="hidden items-center gap-2 px-5 py-5 lg:flex">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white" aria-hidden>SP</span>
          <div>
            <p className="text-sm font-semibold leading-tight text-slate-900">SkillPulse</p>
            <p className="text-[11px] leading-tight text-slate-500">Skill obsolescence predictor</p>
          </div>
        </div>
        <nav aria-label="Main" className="flex flex-col gap-0.5 px-3 pb-4 pt-2 lg:pt-0">
          {NAV.map((n) => (
            <NavLink key={n.to} to={{ pathname: n.to, search: n.filtered ? search : "" }} end={n.end}
              className={({ isActive }) => `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6">
          <button type="button" className="btn-secondary lg:hidden" aria-expanded={menu} aria-label="Toggle navigation" onClick={() => setMenu((m) => !m)}>Menu</button>
          <SkillSearch />
        </header>
        <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          <Outlet />
        </main>
        <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-slate-500 sm:px-6">
          Job-posting trends are a proxy for market demand. Predictions are estimates, not guarantees.
        </footer>
      </div>
    </div>
  );
}
