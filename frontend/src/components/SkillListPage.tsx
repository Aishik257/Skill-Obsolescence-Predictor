import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "@/hooks/useApi";
import { useDebounce } from "@/hooks/useDebounce";
import { useFilters } from "@/hooks/useFilters";
import type { Page, SkillSummary } from "@/types/api";
import type { Params } from "@/api/client";
import FilterBar from "./FilterBar";
import { Async, EmptyState } from "./States";
import { Limitations, PageHeader, Pagination } from "./Ui";
import { SkillTable, type Sort } from "./SkillTable";

const PAGE_SIZE = 25;

/** Shared list view: search + global filters + sortable table + pagination, all state kept in the URL. */
export default function SkillListPage({ title, subtitle, loader, defaultSort, showLimitations = false }: {
  title: string; subtitle: string; defaultSort: Sort;
  loader: (params: Params) => Promise<Page<SkillSummary>>;
  showLimitations?: boolean;
}) {
  const { filters } = useFilters();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const sort: Sort = { key: params.get("sort") ?? defaultSort.key, order: (params.get("order") as "asc" | "desc") ?? defaultSort.order };
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounce(q.trim(), 300);

  const patch = (changes: Record<string, string | null>) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
      return next;
    }, { replace: true });

  useEffect(() => { if ((params.get("q") ?? "") !== dq) patch({ q: dq || null, page: null }); /* eslint-disable-next-line */ }, [dq]);

  const state = useApi(
    () => loader({ ...filters, q: dq, sort: sort.key, order: sort.order, page, page_size: PAGE_SIZE }),
    [JSON.stringify(filters), dq, sort.key, sort.order, page],
  );

  const onSort = (key: string) =>
    patch({ sort: key, order: sort.key === key && sort.order === "desc" ? "asc" : "desc", page: null });

  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <FilterBar />
      <div className="mb-3 max-w-sm">
        <label htmlFor="list-q" className="sr-only">Filter by skill name</label>
        <input id="list-q" className="input" type="search" placeholder="Filter by skill name or alias..." value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Async state={state} isEmpty={(d) => d.items.length === 0}
        empty={<EmptyState title="No skills match these filters" hint="Try clearing a filter or searching for a different name. Slices with very few postings are not analysed." />}>
        {(d) => (
          <>
            <SkillTable rows={d.items} sort={sort} onSort={onSort} />
            <Pagination page={d.page} pages={d.pages} total={d.total} onPage={(p) => patch({ page: String(p) })} />
          </>
        )}
      </Async>
      {showLimitations && <div className="mt-6"><Limitations compact /></div>}
    </>
  );
}
