/**
 * District scope control (top bar button + picker): desktop popover, phone bottom sheet. Port of app.js
 * buildScopeControl / scopePickerBody. Presets "Target districts (default)" and "All districts"; target groups
 * with their present-day districts; other districts by college count; districts with no colleges folded away.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { fmt } from "../lib/fmt";
import {
  resetDistrictScope,
  setDistrictScope,
  targetDistrictIds,
  targetGroupOf,
  targetGroups,
  useDistrictScope,
  useScopeLabel,
} from "../lib/scope";
import type { PortalMeta, Program } from "../lib/types";
import { Button } from "../ui/Button";
import { cx, usePortalUi } from "../ui/context";
import { Icon } from "../ui/Icon";
import { Drawer, toast } from "../ui/Overlay";

export interface ScopeDistrict {
  id: string;
  name: string;
  colleges: number | null;
  group: string | null;
}

/** Per-district rows for the picker (program first, then /api/meta). */
export function scopeDistricts(program: Program | null | undefined, meta: PortalMeta | null | undefined): ScopeDistrict[] {
  const p = program && Array.isArray(program.districts) ? program.districts : null;
  const m = meta && Array.isArray(meta.districts) ? meta.districts : [];
  const base: { id: string; name?: string; colleges_total?: number; colleges?: number }[] = p && p.length ? p : m;
  return base.map((d) => {
    const md = m.find((x) => x.id === d.id);
    const colleges = Number.isFinite(d.colleges_total) ? d.colleges_total! : Number.isFinite(md?.colleges) ? md!.colleges! : Number.isFinite(d.colleges) ? d.colleges! : null;
    return { id: d.id, name: d.name || md?.name || d.id, colleges, group: targetGroupOf(d.id) };
  });
}

function PickerBody({ districts, onDone }: { districts: ScopeDistrict[]; onDone: () => void }) {
  const cur = useDistrictScope();
  const targetIds = targetDistrictIds();
  const byId = useMemo(() => new Map(districts.map((d) => [d.id, d])), [districts]);
  const [sel, setSel] = useState<Set<string>>(() => new Set(cur.all ? districts.map((d) => d.id) : (cur.ids ?? [])));
  const [allMode, setAllMode] = useState(cur.all);
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => first.current?.focus(), []);

  const toggle = (ids: string[], on: boolean) => {
    setAllMode(false);
    setSel((s) => {
      const n = new Set(s);
      ids.forEach((x) => (on ? n.add(x) : n.delete(x)));
      return n;
    });
  };
  const isT = !allMode && sel.size === targetIds.length && targetIds.every((x) => sel.has(x));
  const nCol = [...sel].reduce((a, x) => a + (byId.get(x)?.colleges || 0), 0);
  const summary = allMode
    ? `All districts · ${fmt.plural(districts.reduce((a, d) => a + (d.colleges || 0), 0), "college")}`
    : sel.size
      ? `${fmt.plural(sel.size, "district")} · ${fmt.plural(nCol, "college")}`
      : "Select at least one district";
  const apply = () => {
    if (!allMode && !sel.size) return;
    const everything = allMode || districts.every((d) => sel.has(d.id));
    onDone();
    setDistrictScope(everything ? "all" : [...sel]);
  };
  const cnt = (d: ScopeDistrict | undefined) => (d && d.colleges !== null ? fmt.plural(d.colleges, "college") : "—");
  const box = (d: ScopeDistrict, sub = false) => (
    <li key={d.id} className={cx("td-scope__item", sub && "is-sub", d.colleges === 0 && "is-empty")}>
      <label>
        <input type="checkbox" value={d.id} checked={sel.has(d.id)} onChange={(e) => toggle([d.id], e.target.checked)} />
        <span className="td-scope__name">{d.name}</span>
        <span className="td-scope__cnt td-num">{cnt(d)}</span>
      </label>
    </li>
  );
  const others = districts.filter((d) => !d.group).sort((a, b) => (b.colleges || 0) - (a.colleges || 0) || a.name.localeCompare(b.name));
  const withCols = others.filter((d) => d.colleges !== 0);
  const noCols = others.filter((d) => d.colleges === 0);

  return (
    <>
      <div className="td-scope__body">
        <div className="td-scope__presets" role="group" aria-label="Quick choices">
          <button
            ref={first}
            type="button"
            className="td-scope__preset"
            aria-pressed={isT}
            onClick={() => {
              setAllMode(false);
              setSel(new Set(targetIds));
            }}
          >
            <strong>Target districts (default)</strong>
            <span>{Object.keys(targetGroups()).join(" · ")}</span>
          </button>
          <button
            type="button"
            className="td-scope__preset"
            aria-pressed={allMode}
            onClick={() => {
              setAllMode(true);
              setSel(new Set(districts.map((d) => d.id)));
            }}
          >
            <strong>All districts</strong>
            <span>Every district in Andhra Pradesh</span>
          </button>
        </div>
        <div className="td-scope__sec">
          <h3 className="td-scope__h">Target districts</h3>
          <p className="td-scope__note">Grouped by the old undivided districts (includes districts formed in 2022: Palnadu, Bapatla, NTR, Eluru).</p>
          <ul className="td-scope__list">
            {Object.entries(targetGroups()).map(([gname, ids]) => {
              const n = ids.filter((x) => sel.has(x)).length;
              const total = ids.reduce((a, x) => a + (byId.get(x)?.colleges || 0), 0);
              return (
                <li key={gname} className="td-scope__group">
                  <label className="td-scope__gl">
                    <input
                      type="checkbox"
                      checked={n === ids.length}
                      ref={(el) => {
                        if (el) el.indeterminate = n > 0 && n < ids.length;
                      }}
                      onChange={(e) => toggle([...ids], e.target.checked)}
                    />
                    <span className="td-scope__name">
                      <strong>{gname}</strong>
                      <span className="td-scope__tag">Target</span>
                    </span>
                    <span className="td-scope__cnt td-num">{fmt.plural(total, "college")}</span>
                  </label>
                  <ul className="td-scope__sub">{ids.map((x) => box(byId.get(x) ?? { id: x, name: x, colleges: null, group: gname }, true))}</ul>
                </li>
              );
            })}
          </ul>
        </div>
        {withCols.length ? (
          <div className="td-scope__sec">
            <h3 className="td-scope__h">Other districts</h3>
            <ul className="td-scope__list">{withCols.map((d) => box(d))}</ul>
          </div>
        ) : null}
        {noCols.length ? (
          <details className="td-scope__sec td-scope__more">
            <summary>{fmt.plural(noCols.length, "district")} with no colleges listed</summary>
            <ul className="td-scope__list">{noCols.map((d) => box(d))}</ul>
          </details>
        ) : null}
      </div>
      <div className="td-scope__foot">
        <p className="td-scope__sum" aria-live="polite">
          {summary}
        </p>
        <div className="td-scope__btns">
          <Button
            tone="ghost"
            onClick={() => {
              onDone();
              resetDistrictScope();
            }}
          >
            Reset
          </Button>
          <Button tone="primary" disabled={!allMode && !sel.size} onClick={apply}>
            Apply
          </Button>
        </div>
      </div>
    </>
  );
}

/** The top-bar button + picker. `open` / `onOpenChange` let the shell open it from elsewhere (scope pills). */
export function ScopeControl({ districts, open, onOpenChange }: { districts: ScopeDistrict[]; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { form } = usePortalUi();
  const scope = useDistrictScope();
  const label = useScopeLabel(3);
  const root = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const n = scope.all ? null : (scope.ids ?? []).length;
  // short label (tablet / phone): a count, never the bare word "Target" (owner review)
  const short = scope.all ? "All districts" : `${n} district${n === 1 ? "" : "s"}`;
  const phone = form === "phone";

  useEffect(() => {
    if (!open || phone) return;
    const outside = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) onOpenChange(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onOpenChange(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", outside, true);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("mousedown", outside, true);
      document.removeEventListener("keydown", key, true);
    };
  }, [open, phone, onOpenChange]);

  const openPicker = () => {
    if (!districts.length) {
      toast("The district list is still loading. Try again in a moment.", "info");
      return;
    }
    onOpenChange(!open);
  };
  const close = () => onOpenChange(false);

  return (
    <div className="td-scope" ref={root}>
      <button
        ref={btn}
        type="button"
        className={cx("td-scope__btn", !scope.isDefault && "is-custom")}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Districts shown: ${label}${scope.isDefault ? " (default target districts)" : ""}. Change districts`}
        title={`Districts shown on every page: ${label}${scope.isDefault ? " (the target districts)" : ""}. Click to change.`}
        onClick={openPicker}
      >
        <Icon name="map" size={16} className="td-scope__icon" />
        <span className="td-scope__k">Districts:</span>
        <span className="td-scope__v">{label}</span>
        <span className="td-scope__short">{short}</span>
        {scope.isDefault ? null : <span className="td-scope__chip">{scope.all ? "All" : "Custom"}</span>}
        <Icon name="chevron" size={14} className="td-scope__caret" />
      </button>
      {open && !phone && districts.length ? (
        <div className="td-scope__pop" role="dialog" aria-label="Choose districts">
          <div className="td-scope__head">
            <h2>Districts shown</h2>
            <p>Every page shows only these districts.</p>
          </div>
          <PickerBody districts={districts} onDone={close} />
        </div>
      ) : null}
      <Drawer open={open && phone && districts.length > 0} title="Districts shown" onClose={close}>
        <div className="td-scope__sheet">
          <p className="td-scope__lead">Every page shows only these districts.</p>
          <PickerBody districts={districts} onDone={close} />
        </div>
      </Drawer>
    </div>
  );
}
