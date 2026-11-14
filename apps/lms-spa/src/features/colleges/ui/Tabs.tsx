/**
 * Tabs (components.js tabs / linkTabs / segmented / scrollStrip).
 *
 *   <Tabs tabs={[{ id: "branches", label: "Branches", count: 6, render: () => <Branches/> }, …]} active={q.tab} onChange={(id) => setQuery({ tab: id })} />
 *   <LinkTabs items={[{ label: "Open", to: "?status=open", active: q.status !== "done" }, …]} />
 *   <Segmented options={[{ value: "", label: "All" }, { value: "open", label: "Open", count: 4 }]} value={v} onChange={setV} ariaLabel="Status" />
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { Link, useLocation } from "react-router";
import { fmt } from "../lib/fmt";
import { cx } from "./context";

/** Horizontal scroll strip with edge fades (td-strip--l / --r) that centres the active item. */
export function useScrollStrip<T extends HTMLElement>(ref: RefObject<T | null>, activeSel: string, deps: unknown[] = []): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const sync = () => {
      const max = el.scrollWidth - el.clientWidth;
      el.classList.toggle("td-strip--l", el.scrollLeft > 2);
      el.classList.toggle("td-strip--r", max > 2 && el.scrollLeft < max - 2);
    };
    el.classList.add("td-strip");
    const a = el.querySelector<HTMLElement>(activeSel);
    if (a && el.scrollWidth > el.clientWidth) el.scrollLeft = Math.max(0, a.offsetLeft - (el.clientWidth - a.offsetWidth) / 2);
    sync();
    el.addEventListener("scroll", sync, { passive: true });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(sync) : null;
    ro?.observe(el);
    return () => {
      el.removeEventListener("scroll", sync);
      ro?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, activeSel, ...deps]);
}

export interface TabDef {
  id: string;
  label: ReactNode;
  count?: number | null;
  render: () => ReactNode;
}

/** ARIA tabs with arrow-key navigation; only the active panel renders. Controlled (`active`) or not. */
export function Tabs({ tabs, active, onChange }: { tabs: TabDef[]; active?: string; onChange?: (id: string) => void }) {
  const id = useId();
  const [own, setOwn] = useState(() => (active && tabs.some((t) => t.id === active) ? active : tabs[0]?.id));
  const current = active && tabs.some((t) => t.id === active) ? active : own;
  const bar = useRef<HTMLDivElement>(null);
  useScrollStrip(bar, ".td-tab.is-active", [current]);
  const select = (tid: string) => {
    setOwn(tid);
    if (tid !== current) onChange?.(tid);
  };
  const onKey = (e: KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === current);
    let n: number | null = null;
    if (e.key === "ArrowRight") n = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = tabs.length - 1;
    if (n !== null) {
      e.preventDefault();
      const t = tabs[n]!;
      select(t.id);
      bar.current?.querySelector<HTMLElement>(`[data-tab="${CSS.escape(t.id)}"]`)?.focus();
    }
  };
  const cur = tabs.find((t) => t.id === current);
  return (
    <div className="td-tabs">
      <div className="td-tabs__list" role="tablist" ref={bar} onKeyDown={onKey}>
        {tabs.map((t) => {
          const on = t.id === current;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`${id}-${t.id}`}
              data-tab={t.id}
              aria-controls={`${id}-panel`}
              aria-selected={on}
              tabIndex={on ? 0 : -1}
              className={cx("td-tab", on && "is-active")}
              onClick={() => select(t.id)}
            >
              <span>{t.label}</span>
              {t.count !== undefined && t.count !== null ? <span className="td-tab__count td-num">{fmt.num(t.count)}</span> : null}
            </button>
          );
        })}
      </div>
      <div className="td-tabs__panel" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${current}`} tabIndex={0}>
        {cur?.render()}
      </div>
    </div>
  );
}

export interface LinkTab {
  label: ReactNode;
  /** path, path + query, or just "?query" (same page) */
  to: string;
  active?: boolean;
  count?: number | null;
}

/** Route-level tabs as links (section strips). Without `active`, the best href match for the URL wins. */
export function LinkTabs({ items, ariaLabel = "Section" }: { items: LinkTab[]; ariaLabel?: string }) {
  const loc = useLocation();
  const nav = useRef<HTMLElement>(null);
  const auto = bestMatch(
    items.map((t) => t.to),
    loc.pathname,
    loc.search,
  );
  useScrollStrip(nav, ".td-linktab.is-active", [loc.pathname, loc.search]);
  return (
    <nav className="td-linktabs" aria-label={ariaLabel} ref={nav}>
      {items.map((t, i) => {
        const on = t.active !== undefined ? t.active : i === auto;
        return (
          <Link key={`${t.to}-${i}`} to={t.to} className={cx("td-linktab", on && "is-active")} aria-current={on ? "page" : undefined}>
            <span>{t.label}</span>
            {t.count !== undefined && t.count !== null ? <span className="td-linktab__count td-num">{fmt.num(t.count)}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** Index of the href that best matches the location: same path and every query key of the href matches. */
export function bestMatch(hrefs: string[], pathname: string, search: string): number {
  const cur = new URLSearchParams(search);
  let best = -1;
  let score = -1;
  hrefs.forEach((href, i) => {
    const [p = "", qs] = href.split("?");
    if ((p || pathname) !== pathname) return;
    const q = [...new URLSearchParams(qs ?? "")];
    if (!q.every(([k, v]) => cur.get(k) === v)) return;
    if (q.length > score) {
      score = q.length;
      best = i;
    }
  });
  return best;
}

export interface SegOption<V extends string | number> {
  value: V;
  label: ReactNode;
  count?: number | null;
}

/** Segmented control (aria-pressed buttons, arrow keys move focus). */
export function Segmented<V extends string | number>({
  options,
  value,
  onChange,
  ariaLabel = "Choose",
  size,
}: {
  options: SegOption<V>[];
  value: V;
  onChange: (v: V) => void;
  ariaLabel?: string;
  size?: "sm";
}) {
  const root = useRef<HTMLDivElement>(null);
  const onKey = (e: KeyboardEvent) => {
    const btns = [...(root.current?.querySelectorAll<HTMLButtonElement>(".td-seg__btn") ?? [])];
    const i = btns.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    const n = e.key === "ArrowRight" ? (i + 1) % btns.length : e.key === "ArrowLeft" ? (i - 1 + btns.length) % btns.length : null;
    if (n !== null) {
      e.preventDefault();
      btns[n]?.focus();
    }
  };
  return (
    <div className={cx("td-seg", size === "sm" && "td-seg--sm")} role="group" aria-label={ariaLabel} ref={root} onKeyDown={onKey}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" className="td-seg__btn" aria-pressed={String(o.value) === String(value)} data-value={String(o.value)} onClick={() => onChange(o.value)}>
          <span>{o.label}</span>
          {o.count !== undefined && o.count !== null ? <span className="td-seg__count td-num">{fmt.num(o.count)}</span> : null}
        </button>
      ))}
    </div>
  );
}
