/**
 * List filter bar (components.js filterBar): search box + select / segmented / toggle filters + "Clear filters",
 * active filters as removable chips. On phones the filter controls move into a bottom sheet behind a
 * "Filters (n)" button. Controlled: keep the values in the URL with useQueryState().
 *
 *   const [q, setQuery] = useQueryState();
 *   <FilterBar
 *     values={q}
 *     onChange={(v) => setQuery({ ...v, page: null }, { history: "auto" })}
 *     search={{ key: "q", placeholder: "Search name or phone" }}
 *     filters={[{ key: "status", label: "Status", options: [["active", "Active"], ["inactive", "Inactive"]] },
 *               { key: "mine", label: "Only unassigned", type: "toggle" }]}
 *     actions={<Button icon="external" size="sm">Export</Button>}
 *   />
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { debounce } from "../lib/fmt";
import { Chip } from "./Badges";
import { Button } from "./Button";
import { cx, usePortalUi } from "./context";
import { normOptions, type OptionInput } from "./Form";
import { Icon } from "./Icon";
import { Drawer } from "./Overlay";
import { Segmented } from "./Tabs";

export interface FilterDef {
  key: string;
  label: string;
  type?: "select" | "segmented" | "toggle";
  options?: readonly OptionInput[];
  /** first option label ("All") */
  allLabel?: string;
}

export type FilterValues = Record<string, string | boolean>;

const isSet = (v: unknown) => !(v === null || v === undefined || v === "" || v === false || v === "0" || v === "false");

export function FilterBar({
  values,
  onChange,
  search,
  filters = [],
  actions,
  showClear = true,
  collapse = "auto",
}: {
  /** current values (strings from the URL are fine; toggles accept "1"/"true") */
  values: Record<string, string | boolean | undefined>;
  onChange: (values: FilterValues, changedKey: string | null) => void;
  search?: { key?: string; placeholder?: string; debounce?: number };
  filters?: (FilterDef | null | false | undefined)[];
  actions?: ReactNode;
  showClear?: boolean;
  /** 'auto' = sheet on phones, 'always', 'never' */
  collapse?: "auto" | "always" | "never";
}) {
  const defs = filters.filter((f): f is FilterDef => !!f);
  const { form } = usePortalUi();
  const uid = useId();
  const sKey = search?.key ?? "q";
  const [text, setText] = useState(String(values[sKey] ?? ""));
  const [sheet, setSheet] = useState(false);
  const latest = useRef({ values, onChange });
  latest.current = { values, onChange };

  const current = (): FilterValues => {
    const out: FilterValues = {};
    if (search) out[sKey] = String(latest.current.values[sKey] ?? "");
    for (const f of defs) {
      const v = latest.current.values[f.key];
      out[f.key] = f.type === "toggle" ? isSet(v) : String(v ?? "");
    }
    return out;
  };
  const emit = (patch: FilterValues, k: string | null) => latest.current.onChange({ ...current(), ...patch }, k);

  // keep the box in step when the URL changes from outside (Back, Clear)
  useEffect(() => setText(String(values[sKey] ?? "")), [values, sKey]);
  const fire = useRef(debounce((v: string) => emit({ [sKey]: v.trim() }, sKey), search?.debounce ?? 250));
  useEffect(() => () => fire.current.cancel(), []);

  const active = defs.filter((f) => isSet(values[f.key]));
  const anySet = active.length > 0 || isSet(values[sKey]);
  const collapsed = collapse === "always" || (collapse === "auto" && form === "phone");
  const clearAll = () => {
    setText("");
    const out: FilterValues = {};
    if (search) out[sKey] = "";
    for (const f of defs) out[f.key] = f.type === "toggle" ? false : "";
    latest.current.onChange(out, null);
  };
  const chipLabel = (f: FilterDef) => {
    if (f.type === "toggle") return f.label;
    const v = values[f.key];
    const op = normOptions(f.options ?? []).find((x) => String(x.value) === String(v));
    return `${f.label}: ${op ? op.label : String(v)}`;
  };

  const controls = (
    <div className="td-fbar__items">
      {defs.map((f) => {
        const id = `${uid}-${f.key}`;
        if (f.type === "segmented")
          return (
            <div key={f.key} className="td-fbar__item td-fbar__item--seg">
              <span className="td-fbar__label" aria-hidden="true">
                {f.label}
              </span>
              <Segmented
                size="sm"
                ariaLabel={f.label}
                value={String(values[f.key] ?? "")}
                options={[{ value: "", label: f.allLabel ?? "All" }, ...normOptions(f.options ?? []).map((o) => ({ value: String(o.value), label: o.label }))]}
                onChange={(v) => emit({ [f.key]: v }, f.key)}
              />
            </div>
          );
        if (f.type === "toggle")
          return (
            <label key={f.key} htmlFor={id} className="td-fbar__item td-fbar__toggle">
              <input id={id} type="checkbox" className="td-check" checked={isSet(values[f.key])} onChange={(e) => emit({ [f.key]: e.target.checked }, f.key)} />
              <span>{f.label}</span>
            </label>
          );
        const opts = normOptions(f.options ?? []);
        const idx = opts.findIndex((o) => String(o.value) === String(values[f.key] ?? ""));
        return (
          <div key={f.key} className="td-fbar__item">
            <label htmlFor={id} className="td-fbar__label">
              {f.label}
            </label>
            <select
              id={id}
              className={cx("td-input", "td-select", "td-input--sm", idx >= 0 && "is-set")}
              aria-label={f.label}
              value={idx < 0 ? "" : String(idx)}
              onChange={(e) => emit({ [f.key]: e.target.value === "" ? "" : String(opts[Number(e.target.value)]?.value ?? "") }, f.key)}
            >
              <option value="">{f.allLabel ?? `${f.label}: all`}</option>
              {opts.map((o, i) => (
                <option key={i} value={String(i)}>
                  {f.allLabel ? o.label : `${f.label}: ${o.label}`}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      {showClear && anySet ? (
        <Button icon="close" tone="ghost" size="sm" onClick={clearAll}>
          Clear filters
        </Button>
      ) : null}
    </div>
  );

  return (
    <div className={cx("td-fbar", defs.length && collapse === "auto" && "td-fbar--auto", collapse === "always" && "td-fbar--collapsed")} role="search">
      <div className="td-fbar__main">
        {search ? (
          <div className="td-fbar__search">
            <Icon name="search" size={16} className="td-fbar__qicon" />
            <input
              type="search"
              className="td-input td-fbar__q"
              placeholder={search.placeholder ?? "Search…"}
              aria-label={search.placeholder ?? "Search"}
              enterKeyHint="search"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                fire.current(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape" && text) {
                  e.stopPropagation();
                  setText("");
                  fire.current.cancel();
                  emit({ [sKey]: "" }, sKey);
                }
              }}
            />
          </div>
        ) : null}
        {collapsed ? null : controls}
        {defs.length ? (
          <Button
            icon="filter"
            size="sm"
            className={cx("td-fbar__more", active.length > 0 && "is-set")}
            aria-haspopup="dialog"
            ariaLabel={active.length ? `Filters, ${active.length} active` : "Filters"}
            onClick={() => setSheet(true)}
          >
            Filters{active.length ? ` (${active.length})` : ""}
          </Button>
        ) : null}
      </div>
      {actions ? <div className="td-fbar__actions">{actions}</div> : null}
      {active.length ? (
        <div className="td-fbar__chips" role="group" aria-label="Active filters">
          {active.map((f) => (
            <Chip key={f.key} active label={chipLabel(f)} onRemove={() => emit({ [f.key]: f.type === "toggle" ? false : "" }, f.key)} />
          ))}
        </div>
      ) : null}
      <Drawer open={sheet} title={active.length ? `Filters (${active.length})` : "Filters"} onClose={() => setSheet(false)}>
        <div className="td-fbar-sheet">
          {controls}
          <div className="td-fbar-sheet__foot">
            <Button tone="ghost" onClick={clearAll}>
              Clear all
            </Button>
            <Button tone="primary" onClick={() => setSheet(false)}>
              Show results
            </Button>
          </div>
        </div>
      </Drawer>
    </div>
  );
}
