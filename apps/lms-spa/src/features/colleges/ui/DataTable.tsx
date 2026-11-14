/**
 * Data table (components.js dataTable + pagination): sortable, paginated (client or server), row actions,
 * selectable rows, row links, loading / error / empty states, and a phone CARD mode.
 *
 *   <DataTable
 *     caption="Colleges" rows={rows} rowKey={(r) => r.id} pageSize={50} pageLabel="colleges"
 *     columns={[
 *       { key: "name", label: "College", primary: true, render: (r) => r.short_name ?? r.name },
 *       { key: "district_id", label: "District", render: (r) => districtName(r.district_id) },
 *       { key: "enrolled", label: "Enrolled", align: "right" },
 *       { key: "status", label: "Status", sortable: false, render: (r) => <StatusChip status={r.pace_status} size="sm" /> },
 *     ]}
 *     rowHref={(r) => portalPath.college(r.id)}
 *     rowActions={(r) => [{ label: "Edit", icon: "edit", onClick: () => edit(r), writeOnly: true }]}
 *     loading={loading} error={error} onRetry={reload}
 *     empty={<ListEmpty noun="colleges" filtered={hasFilters(q)} onClear={clear} />}
 *   />
 *
 * Fit (as before): priority-3 columns hide first when the table is narrow; below the width of the priority 1+2
 * columns, or on phones, rows become cards (`mobile: "scroll"` keeps a horizontally scrolling table instead).
 * Server sort / paging: pass `sort` + `onSort` and `page` + `total` + `onPage`; otherwise both run on `rows`.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode, type MouseEvent as ReactMouseEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { fmt } from "../lib/fmt";
import { ValueWithBasis } from "./Badges";
import { Button } from "./Button";
import { cx, usePortalUi } from "./context";
import { EmptyState, ErrorCard } from "./Feedback";
import type { IconName } from "./Icon";
import { Menu } from "./Menu";

export interface Column<R> {
  key: string;
  label: ReactNode;
  render?: (row: R) => ReactNode;
  /** value used for client-side sorting (default: row[key]) */
  sortValue?: (row: R) => unknown;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  width?: string;
  /** the card title on phones; also the 200 px minimum column */
  primary?: boolean;
  /** 1 = always, 2 = default, 3 = hides first when narrow */
  priority?: 1 | 2 | 3;
  minWidth?: number;
  hideOnPhone?: boolean;
  cardHidden?: boolean;
  /** label in card mode / phone sort select */
  phoneLabel?: string;
  sticky?: "left" | "right";
}

export interface RowAction<R> {
  label: string;
  icon?: IconName;
  tone?: "danger" | "primary" | "secondary" | "accent" | "ghost";
  onClick: (row: R, e?: ReactMouseEvent) => void;
  hidden?: boolean;
  writeOnly?: boolean;
}

export type SortState = { key: string; dir: "asc" | "desc" } | null;

export interface DataTableProps<R> {
  columns: (Column<R> | null | false | undefined)[];
  rows: R[] | undefined;
  rowKey?: (row: R) => string | number;
  caption?: string;
  sort?: SortState;
  /** server-side sort */
  onSort?: (key: string, dir: "asc" | "desc") => void;
  page?: number;
  pageSize?: number;
  /** server-side paging: total row count */
  total?: number;
  onPage?: (page: number) => void;
  pageLabel?: string;
  onRowClick?: (row: R) => void;
  /** in-portal link of a row (client navigation) */
  rowHref?: (row: R) => string | null;
  rowActions?: (row: R) => RowAction<R>[];
  selectable?: boolean;
  onSelect?: (rows: R[]) => void;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: ReactNode;
  mobile?: "cards" | "scroll";
  cardTitle?: (row: R) => ReactNode;
  cardSubtitle?: (row: R) => ReactNode;
  cardMeta?: (row: R) => ReactNode[];
  /** false: no sort select in card mode (the page has its own) */
  cardSort?: boolean;
  /** cards below this width even on larger screens */
  cardBreakpoint?: number;
  defaultSortLabel?: string;
  dense?: boolean;
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

function sortVal(v: unknown): unknown {
  if (v && typeof v === "object" && "value" in (v as object)) return (v as { value: unknown }).value;
  return v;
}

const coll = new Intl.Collator("en-IN", { numeric: true, sensitivity: "base" });

export function DataTable<R>(props: DataTableProps<R>) {
  const { rows = [], rowKey = (r: R) => (r as { id: string | number }).id, caption, pageSize, pageLabel = "rows", mobile = "cards", loading, error, onRetry, dense } = props;
  const columns = useMemo(() => props.columns.filter((c): c is Column<R> => !!c), [props.columns]);
  const { form, canWrite } = usePortalUi();
  const navigate = useNavigate();
  const [ownSort, setOwnSort] = useState<SortState>(props.sort ?? null);
  const [ownPage, setOwnPage] = useState(props.page ?? 1);
  const [selected, setSelected] = useState<Set<string | number>>(() => new Set());
  const root = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  const serverSort = typeof props.onSort === "function";
  const serverPage = typeof props.onPage === "function";
  const sort = serverSort ? (props.sort ?? null) : ownSort;
  const page = serverPage ? (props.page ?? 1) : ownPage;

  // client paging: back to page 1 when the rows change
  useEffect(() => {
    if (!serverPage) setOwnPage(1);
  }, [rows, serverPage]);

  useEffect(() => {
    const el = root.current;
    if (!el || typeof ResizeObserver !== "function") return;
    const ro = new ResizeObserver((ents) => {
      const w = Math.round(ents[0]?.contentRect.width ?? 0);
      if (w) setWidth((prev) => (Math.abs(prev - w) < 2 ? prev : w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const primaryIdx = Math.max(0, columns.findIndex((c) => c.primary));
  const prio = (c: Column<R>, i: number) => c.priority ?? (c.primary || i < 2 ? 1 : 2);
  const minW = (c: Column<R>, i: number) => c.minWidth ?? (i === primaryIdx ? 200 : 110);
  const need = (maxPrio: number) => columns.reduce((w, c, i) => (prio(c, i) <= maxPrio ? w + minW(c, i) : w), (props.selectable ? 44 : 0) + (props.rowActions ? 96 : 0));
  const w = width || (typeof window !== "undefined" ? window.innerWidth : 1280);
  const cards = mobile === "cards" && (form === "phone" || w < need(2) || (!!props.cardBreakpoint && w < props.cardBreakpoint));
  const hide3 = !cards && w < need(3);

  const sorted = useMemo(() => {
    if (serverSort || !sort?.key) return rows;
    const dir = sort.dir === "desc" ? -1 : 1;
    const col = columns.find((c) => c.key === sort.key);
    const get = col?.sortValue ?? ((r: R) => sortVal((r as Record<string, unknown>)[sort.key]));
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      const xn = isEmpty(x);
      const yn = isEmpty(y);
      if (xn && yn) return 0;
      if (xn) return 1;
      if (yn) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return coll.compare(String(x), String(y)) * dir;
    });
  }, [rows, sort, serverSort, columns]);

  const shown = serverPage || !pageSize ? sorted : sorted.slice((page - 1) * pageSize, page * pageSize);
  const total = serverPage ? (props.total ?? 0) : rows.length;

  const setSort = (s: SortState) => {
    if (serverSort) {
      if (s) props.onSort!(s.key, s.dir);
    } else {
      setOwnSort(s);
      setOwnPage(1);
    }
  };
  const toggleSort = (key: string) => setSort({ key, dir: sort?.key === key && sort.dir === "asc" ? "desc" : "asc" });
  const goPage = (n: number) => {
    if (serverPage) props.onPage!(n);
    else setOwnPage(n);
    root.current?.scrollIntoView?.({ block: "nearest" });
  };

  const updateSel = (next: Set<string | number>) => {
    setSelected(next);
    props.onSelect?.(rows.filter((r) => next.has(rowKey(r))));
  };

  const cell = (c: Column<R>, row: R): ReactNode => {
    if (c.render) return c.render(row);
    const v = (row as Record<string, unknown>)[c.key];
    if (v && typeof v === "object" && "value" in (v as object)) return <ValueWithBasis value={v as never} />;
    return isEmpty(v) ? "—" : typeof v === "number" ? fmt.num(v) : String(v);
  };

  const actions = (row: R) => {
    if (!props.rowActions) return null;
    const list = props.rowActions(row).filter((a) => a && !a.hidden && !(a.writeOnly && !canWrite));
    if (!list.length) return null;
    if (list.length <= 2)
      return (
        <div className="td-dt__acts">
          {list.map((a, i) => (
            <Button
              key={i}
              size="sm"
              icon={a.icon}
              tone={a.tone && ["danger", "primary", "secondary", "accent"].includes(a.tone) ? a.tone : "ghost"}
              onClick={(e) => {
                e.stopPropagation();
                a.onClick(row, e);
              }}
            >
              {a.label}
            </Button>
          ))}
        </div>
      );
    return (
      <div className="td-dt__acts">
        <Menu ariaLabel="Row actions" items={list.map((a) => ({ label: a.label, icon: a.icon, tone: a.tone === "danger" ? "danger" : undefined, onClick: () => a.onClick(row) }))} />
      </div>
    );
  };

  const rowProps = (row: R) => {
    const href = props.rowHref?.(row) ?? null;
    if (!props.onRowClick && !href) return {};
    const act = () => (props.onRowClick ? props.onRowClick(row) : href && navigate(href));
    return {
      tabIndex: 0,
      onClick: (e: ReactMouseEvent) => {
        if ((e.target as HTMLElement).closest("a,button,input,select,textarea,label")) return;
        act();
      },
      onKeyDown: (e: ReactKeyboardEvent) => {
        if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) {
          e.preventDefault();
          act();
        }
      },
      "data-click": "1",
    };
  };

  const selBox = (row: R) => {
    const k = rowKey(row);
    return (
      <label className="td-checkhit" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          className="td-check"
          aria-label="Select row"
          checked={selected.has(k)}
          onChange={(e) => {
            const n = new Set(selected);
            if (e.target.checked) n.add(k);
            else n.delete(k);
            updateSel(n);
          }}
        />
      </label>
    );
  };

  const emptyNode = props.empty ?? <EmptyState icon="list" title="Nothing to show" />;
  const colCls = (c: Column<R>, i: number) => cx(prio(c, i) >= 3 && "td-dt__p3", c.sticky === "left" && "td-dt__stick-l", c.sticky === "right" && "td-dt__stick-r");

  let body: ReactNode;
  if (cards) {
    const sortable = columns.filter((c) => c.sortable !== false && c.key);
    body = (
      <div className="td-dt__cards" role="list" aria-label={caption ?? "List"} aria-busy={loading || undefined}>
        {props.cardSort !== false && sortable.length && rows.length > 1 && !loading ? (
          <div className="td-dt__cardsort">
            <select
              className="td-input td-select td-input--sm"
              aria-label="Sort by"
              value={sort ? `${sort.key}:${sort.dir}` : ""}
              onChange={(e) => {
                const [k, d] = e.target.value.split(":");
                setSort(k ? { key: k, dir: d === "desc" ? "desc" : "asc" } : null);
              }}
            >
              <option value="">{props.defaultSortLabel ? `Sort: ${props.defaultSortLabel}` : "Sort: as listed"}</option>
              {sortable.flatMap((c) => [
                <option key={`${c.key}:asc`} value={`${c.key}:asc`}>
                  {c.phoneLabel ?? (typeof c.label === "string" ? c.label : c.key)} ↑
                </option>,
                <option key={`${c.key}:desc`} value={`${c.key}:desc`}>
                  {c.phoneLabel ?? (typeof c.label === "string" ? c.label : c.key)} ↓
                </option>,
              ])}
            </select>
          </div>
        ) : null}
        {loading ? (
          Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="td-dt-card td-dt-card--skel" aria-hidden="true">
              <div className="td-skel td-skel--title" />
              <div className="td-skel" />
              <div className="td-skel" style={{ width: "60%" }} />
            </div>
          ))
        ) : error ? (
          <ErrorCard title="Could not load this list" error={error} retry={onRetry} />
        ) : !shown.length ? (
          <div className="td-card">{emptyNode}</div>
        ) : (
          shown.map((row) => {
            const pc = columns[primaryIdx];
            const sub = props.cardSubtitle?.(row);
            const meta = (props.cardMeta?.(row) ?? []).filter(Boolean);
            const kv = columns.filter((c, i) => i !== primaryIdx && !c.hideOnPhone && !c.cardHidden);
            const rp = rowProps(row);
            return (
              <div key={rowKey(row)} role="listitem" className={cx("td-dt-card", props.selectable && selected.has(rowKey(row)) && "is-selected", !kv.length && "td-dt-card--bare", "data-click" in rp && "is-click")} {...rp}>
                <div className="td-dt-card__head">
                  {props.selectable ? selBox(row) : null}
                  <div className="td-dt-card__main">
                    <div className="td-dt-card__title">{props.cardTitle ? props.cardTitle(row) : pc ? cell(pc, row) : null}</div>
                    {!isEmpty(sub) ? <div className="td-dt-card__sub">{sub}</div> : null}
                    {meta.length ? <div className="td-dt-card__meta">{meta}</div> : null}
                  </div>
                  {actions(row)}
                </div>
                {kv.length ? (
                  <dl className="td-dt-card__kv">
                    {kv.map((c) => (
                      <div key={c.key} className="td-dt-card__row">
                        <dt>{c.phoneLabel ?? c.label}</dt>
                        <dd>{cell(c, row)}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </div>
            );
          })
        )}
      </div>
    );
  } else {
    const ncol = columns.length + (props.selectable ? 1 : 0) + (props.rowActions ? 1 : 0);
    const keys = shown.map(rowKey);
    const nSel = keys.filter((k) => selected.has(k)).length;
    body = (
      <div className="td-table-scroll" tabIndex={0} role="region" aria-label={caption ?? "Table"}>
        <table className={cx("td-table", "td-dt__table", (props.onRowClick || props.rowHref) && "td-table--click")}>
          {caption ? <caption className="td-sr-only">{caption}</caption> : null}
          <thead>
            <tr>
              {props.selectable ? (
                <th className="td-dt__sel" scope="col">
                  <label className="td-checkhit">
                    <input
                      type="checkbox"
                      className="td-check"
                      aria-label="Select all on this page"
                      checked={!!keys.length && nSel === keys.length}
                      ref={(el) => {
                        if (el) el.indeterminate = nSel > 0 && nSel < keys.length;
                      }}
                      onChange={(e) => {
                        const n = new Set(selected);
                        keys.forEach((k) => (e.target.checked ? n.add(k) : n.delete(k)));
                        updateSel(n);
                      }}
                    />
                  </label>
                </th>
              ) : null}
              {columns.map((c, i) => {
                const sortable = c.sortable !== false && !!c.key;
                const on = sort?.key === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className={cx(c.align && `td-al-${c.align}`, colCls(c, i))}
                    style={c.width ? { width: c.width } : undefined}
                    aria-sort={on ? (sort!.dir === "desc" ? "descending" : "ascending") : sortable ? "none" : undefined}
                  >
                    {sortable ? (
                      <button type="button" className={cx("td-th-sort", on && "is-sorted")} onClick={() => toggleSort(c.key)}>
                        <span>{c.label}</span>
                        <span className="td-th-sort__ind" aria-hidden="true" />
                      </button>
                    ) : (
                      c.label
                    )}
                  </th>
                );
              })}
              {props.rowActions ? (
                <th scope="col" className="td-al-right td-dt__actcol td-dt__stick-r">
                  <span className="td-sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: Math.min(Math.max(pageSize ?? 6, 4), 8) }, (_, i) => (
                <tr key={i} className="td-dt__skel" aria-hidden="true">
                  {Array.from({ length: ncol }, (_, j) => (
                    <td key={j}>
                      <div className="td-skel" style={{ width: `${55 + ((i * 13 + j * 17) % 40)}%` }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : error ? (
              <tr className="td-table-empty">
                <td colSpan={ncol}>
                  <ErrorCard title="Could not load this list" error={error} retry={onRetry} />
                </td>
              </tr>
            ) : !shown.length ? (
              <tr className="td-table-empty">
                <td colSpan={ncol}>{emptyNode}</td>
              </tr>
            ) : (
              shown.map((row) => {
                const rp = rowProps(row);
                return (
                  <tr key={rowKey(row)} className={cx(props.selectable && selected.has(rowKey(row)) && "is-selected", "data-click" in rp && "is-click")} {...rp}>
                    {props.selectable ? <td className="td-dt__sel">{selBox(row)}</td> : null}
                    {columns.map((c, i) => (
                      <td
                        key={c.key}
                        className={cx(c.align && `td-al-${c.align}`, i === primaryIdx && "td-td-primary", typeof (row as Record<string, unknown>)[c.key] === "number" && "td-num", colCls(c, i))}
                      >
                        {cell(c, row)}
                      </td>
                    ))}
                    {props.rowActions ? <td className="td-al-right td-dt__actcol td-dt__stick-r">{actions(row)}</td> : null}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div ref={root} className={cx("td-dt", dense && "td-dt--dense", mobile === "cards" && "td-dt--cards", hide3 && "td-dt--hide3", cards && "td-dt--is-cards")}>
      {body}
      {pageSize && !loading && !error && total > 0 ? <Pagination page={page} pageSize={pageSize} total={total} label={pageLabel} onPage={goPage} /> : null}
    </div>
  );
}

/** "1–50 of 312 colleges  ‹ Page 1 of 7 ›" (+ optional page-size select). */
export function Pagination({
  page = 1,
  pageSize = 50,
  total = 0,
  onPage,
  pageSizes,
  onPageSize,
  label = "rows",
}: {
  page?: number;
  pageSize?: number;
  total?: number;
  onPage: (page: number) => void;
  pageSizes?: number[];
  onPageSize?: (n: number) => void;
  label?: string;
}) {
  const pages = Math.max(1, Math.ceil((Number(total) || 0) / pageSize));
  const p = Math.min(Math.max(1, page), pages);
  const from = total ? (p - 1) * pageSize + 1 : 0;
  const to = Math.min(p * pageSize, total);
  const go = (n: number) => {
    if (n >= 1 && n <= pages && n !== p) onPage(n);
  };
  return (
    <div className="td-pager" role="navigation" aria-label="Pagination">
      <span className="td-pager__info td-num" aria-live="polite">
        {total ? `${fmt.num(from)}–${fmt.num(to)} of ${fmt.num(total)} ${label}` : `0 ${label}`}
      </span>
      <span className="td-pager__ctrl">
        {pageSizes && onPageSize ? (
          <select className="td-input td-select td-input--sm" aria-label="Rows per page" value={String(pageSize)} onChange={(e) => onPageSize(Number(e.target.value))}>
            {pageSizes.map((n) => (
              <option key={n} value={String(n)}>
                {n} per page
              </option>
            ))}
          </select>
        ) : null}
        {pages > 1 ? (
          <>
            <Button icon="chevron-left" tone="ghost" size="sm" ariaLabel="Previous page" disabled={p <= 1} onClick={() => go(p - 1)} />
            <span className="td-pager__page td-num">
              Page {p} of {pages}
            </span>
            <Button icon="chevron" tone="ghost" size="sm" ariaLabel="Next page" disabled={p >= pages} onClick={() => go(p + 1)} />
          </>
        ) : null}
      </span>
    </div>
  );
}
