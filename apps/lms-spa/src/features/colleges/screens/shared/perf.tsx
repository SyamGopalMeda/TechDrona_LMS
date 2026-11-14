/**
 * Extra helpers for Home, Reports, Targets and the Planner on top of ./dashboard.tsx (the shared port of the old
 * dashboard.js helper block, re-exported here so these screens import from one place).
 */
import { useState, type ReactNode } from "react";
import { fmt } from "../../lib/fmt";

export {
  isNum,
  rowId,
  rowLabel,
  pctText,
  noTargetReason,
  rateText,
  daysLeftText,
  remainingText,
  leadOf,
  hrefFor,
  prettyReason,
  DIAG_INFO,
  DIAG_ORDER,
  collegesHref,
  ProgressNode,
  StatusNode,
  AttentionList,
  unassignedOf,
  ROLE_TIPS,
} from "./dashboard";

/* eslint-disable @typescript-eslint/no-explicit-any -- API rows are loosely typed (index signatures) */
export type AnyRow = Record<string, any>;

/** Rows from a list endpoint that may return an array or a {items,total} page. */
export const itemsOf = <T = AnyRow,>(res: unknown): T[] =>
  Array.isArray(res) ? (res as T[]) : res && Array.isArray((res as { items?: unknown }).items) ? (res as { items: T[] }).items : [];
/** Rows of /api/performance (array, {rows} or {items}). */
export const perfRows = (res: unknown): AnyRow[] => (!res ? [] : Array.isArray(res) ? res : ((res as AnyRow).rows ?? (res as AnyRow).items ?? []));

/** true when /api/target-dashboard says the programme target does not apply to this selection (v4.1). */
export const programmeNA = (T: AnyRow | null | undefined): boolean =>
  !!(T && T.program && (T.program.applies === false || (T.program.target === null && T.program.target_reason)));

/** "Could not load X." note (old errorNote). */
export function ErrorNote({ error, what = "this section" }: { error: unknown; what?: string }) {
  const msg = error && typeof error === "object" && "message" in error ? String((error as { message: unknown }).message) : "";
  return (
    <div className="vd-error" role="alert">
      Could not load {what}. <span className="vd-muted">{msg}</span>
    </div>
  );
}

/** A list that shows `limit` items and a "Show N more" toggle for the rest. */
export function Expandable({ items, limit, className, noun = "more" }: { items: ReactNode[]; limit: number; className?: string; noun?: string }) {
  const [open, setOpen] = useState(false);
  const extra = items.length - limit;
  const list = <ul className={className}>{open ? items : items.slice(0, limit)}</ul>;
  if (extra <= 0) return list;
  return (
    <div className="vd-expandable">
      {list}
      <button type="button" className="td-btn td-btn--ghost td-btn--sm vd-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? "Show fewer" : `Show ${fmt.num(extra)} ${noun}`}
      </button>
    </div>
  );
}
