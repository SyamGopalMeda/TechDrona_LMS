/**
 * Global search combobox (app.js buildSearch): GET /api/search?q= (≥ 2 characters, 200 ms debounce), results
 * grouped Districts / Cities & towns / Colleges / Branches / People, arrow keys + Enter, Esc closes, "/" focuses.
 * On compact bars (phones, < 900 px) it opens full-width from the top-bar search button.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { isPortalApiError, portalApi } from "../lib/api";
import { debounce } from "../lib/fmt";
import { searchHitHref } from "../lib/routes";
import type { SearchHit } from "../lib/types";
import { Button } from "../ui/Button";
import { Icon, type IconName } from "../ui/Icon";

const GROUPS: [string, string, IconName][] = [
  ["district", "Districts", "map"],
  ["city", "Cities & towns", "map"],
  ["college", "Colleges", "college"],
  ["branch", "Branches", "branch"],
  ["person", "People", "people"],
];

type Status = { kind: "idle" } | { kind: "loading" } | { kind: "error"; offline: boolean } | { kind: "done"; q: string; rows: SearchHit[] };

export interface GlobalSearchHandle {
  focus: () => void;
}

export const GlobalSearch = forwardRef<GlobalSearchHandle, { onClose?: () => void; showClose?: boolean }>(function GlobalSearch({ onClose, showClose }, ref) {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [active, setActive] = useState(-1);
  const token = useRef(0);
  useImperativeHandle(ref, () => ({ focus: () => input.current?.focus() }), []);

  const run = useRef(
    debounce(async (q: string) => {
      const my = ++token.current;
      if (q.length < 2) {
        setOpen(false);
        return;
      }
      setStatus({ kind: "loading" });
      setOpen(true);
      try {
        const rows = await portalApi.get<SearchHit[]>("search", { query: { q } });
        if (my !== token.current) return;
        setStatus({ kind: "done", q, rows: Array.isArray(rows) ? rows : [] });
        setActive(Array.isArray(rows) && rows.length ? 0 : -1);
      } catch (e) {
        if (my !== token.current) return;
        setStatus({ kind: "error", offline: isPortalApiError(e) && e.status === 0 });
      }
    }, 200),
  );
  useEffect(() => () => run.current.cancel(), []);

  const ordered: SearchHit[] =
    status.kind === "done" ? [...GROUPS.flatMap(([t]) => status.rows.filter((r) => r.type === t)), ...status.rows.filter((r) => !GROUPS.some(([t]) => t === r.type))] : [];

  const go = (hit: SearchHit) => {
    setOpen(false);
    setValue("");
    token.current++;
    input.current?.blur();
    onClose?.();
    void navigate(searchHitHref(hit));
  };

  let n = -1;
  const option = (it: SearchHit, ic: IconName | null) => {
    n += 1;
    const i = n;
    return (
      <div
        key={`${it.type}-${it.id}-${i}`}
        id={`td-so-${i}`}
        role="option"
        className="td-search__opt"
        aria-selected={i === active}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => go(it)}
      >
        {ic ? (
          <span className="td-search__oicon">
            <Icon name={ic} size={16} />
          </span>
        ) : null}
        <span className="td-search__otext">
          <span className="td-search__olabel">{it.label || it.id}</span>
          {it.sub ? <span className="td-search__osub">{it.sub}</span> : null}
        </span>
      </div>
    );
  };

  return (
    <div className={open ? "td-search is-open" : "td-search"}>
      <div className="td-search__box">
        <Icon name="search" size={18} className="td-search__icon" />
        <input
          ref={input}
          type="search"
          className="td-search__input"
          placeholder="Search districts, colleges, branches, people…"
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={open}
          aria-controls="td-search-list"
          aria-autocomplete="list"
          aria-label="Search the portal"
          aria-activedescendant={open && active >= 0 ? `td-so-${active}` : undefined}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            run.current(e.target.value.trim());
          }}
          onFocus={() => {
            if (value.trim().length >= 2 && status.kind !== "idle") setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              if (!open) run.current(value.trim());
              else setActive((a) => Math.min(a + 1, ordered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              const hit = ordered[active];
              if (open && hit) {
                e.preventDefault();
                go(hit);
              }
            } else if (e.key === "Escape") {
              if (open) {
                e.preventDefault();
                setOpen(false);
              } else {
                setValue("");
                input.current?.blur();
                onClose?.();
              }
            }
          }}
        />
        <kbd className="td-search__kbd" aria-hidden="true">
          /
        </kbd>
        {showClose ? <Button icon="close" tone="ghost" ariaLabel="Close search" className="td-search__close" onClick={() => onClose?.()} /> : null}
      </div>
      <div id="td-search-list" className="td-search__results" role="listbox" aria-label="Search results" hidden={!open}>
        {status.kind === "loading" ? (
          <div className="td-search__empty td-search__loading">
            <Icon name="search" size={16} />
            Searching…
          </div>
        ) : status.kind === "error" ? (
          <div className="td-search__empty">{status.offline ? "Server unreachable — search is unavailable." : "Search failed. Please try again."}</div>
        ) : status.kind === "done" && !status.rows.length ? (
          <div className="td-search__empty">
            <strong>No matches for “{status.q}”</strong>
            <span>Try a district, town, college short name (e.g. “KL”), branch code or a person’s name.</span>
          </div>
        ) : status.kind === "done" ? (
          <>
            {GROUPS.map(([type, label, ic]) => {
              const items = status.rows.filter((r) => r.type === type);
              if (!items.length) return null;
              return (
                <div key={type} role="group" aria-labelledby={`td-sg-${type}`} className="td-search__group">
                  <div id={`td-sg-${type}`} className="td-search__ghead">
                    {label}
                  </div>
                  {items.map((it) => option(it, ic))}
                </div>
              );
            })}
            {status.rows.some((r) => !GROUPS.some(([t]) => t === r.type)) ? (
              <div role="group" className="td-search__group">
                <div className="td-search__ghead">Other</div>
                {status.rows.filter((r) => !GROUPS.some(([t]) => t === r.type)).map((it) => option(it, null))}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
});
