/**
 * District scope: which districts every portal page shows (port of the old portal's js/state.js).
 *
 * - Default = the target districts: the OLD undivided Guntur / Krishna / West Godavari = 7 present-day ids
 *   (GET /api/program `target_district_groups`; a built-in copy is used until it answers).
 * - Persisted in localStorage `td.districtScope` ('all' or a JSON id list; absent = default). Same key and same
 *   origin as the old portal, so a user's choice carries over.
 * - URL: `?d=all|target|id,id` sets it (deep links); PortalLayout applies it and keeps it in step (see useScopeUrlSync).
 * - Every scoped API call adds `districts=<ids>` (lib/api.ts `scoped: true`); "All districts" sends nothing.
 *
 * A tiny external store (no React needed) so lib/api.ts can read it; React reads it with useDistrictScope().
 */
import { useSyncExternalStore } from "react";
import { prettySlug } from "./fmt";
import type { Program } from "./types";

export const SCOPE_KEY = "td.districtScope";

/** Built-in fallback until GET /api/program answers (same values the backend seeds into settings). */
export const DEFAULT_TARGET_GROUPS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  Guntur: ["guntur", "palnadu", "bapatla"],
  Krishna: ["krishna", "ntr"],
  "West Godavari": ["west-godavari", "eluru"],
});

export interface DistrictScope {
  /** true = "All districts" (no `districts=` filter) */
  all: boolean;
  /** selected present-day district ids; null when `all` */
  ids: string[] | null;
  /** true when the selection is the target districts (the default) */
  isDefault: boolean;
}

/** null = default (target districts) · 'all' · an explicit id list */
type Selection = null | "all" | string[];

interface ScopeContext {
  program: Program | null;
  /** id → display name (from /api/meta and /api/program) */
  names: Map<string, string>;
}

const listeners = new Set<() => void>();
let ctx: ScopeContext = { program: null, names: new Map() };

function readStored(): Selection {
  try {
    const raw = localStorage.getItem(SCOPE_KEY);
    if (!raw) return null;
    if (raw === "all") return "all";
    const ids: unknown = JSON.parse(raw);
    return Array.isArray(ids) && ids.length ? ids.filter((x): x is string => typeof x === "string") : null;
  } catch {
    return null;
  }
}

let sel: Selection = readStored();

const sameSet = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x));

export function targetGroups(): Record<string, readonly string[]> {
  const g = ctx.program?.target_district_groups;
  return g && typeof g === "object" && Object.keys(g).length ? g : (DEFAULT_TARGET_GROUPS as Record<string, readonly string[]>);
}

export function targetDistrictIds(): string[] {
  const p = ctx.program?.target_district_ids;
  return Array.isArray(p) && p.length ? [...p] : Object.values(targetGroups()).flat();
}

/** Target group name for a present-day district id ("Guntur" for palnadu), or null. */
export function targetGroupOf(id: string): string | null {
  for (const [name, ids] of Object.entries(targetGroups())) if (ids.includes(id)) return name;
  return null;
}

function compute(): DistrictScope {
  if (sel === "all") return { all: true, ids: null, isDefault: false };
  const ids = sel ? [...sel] : targetDistrictIds();
  return { all: false, ids, isDefault: !sel || sameSet(ids, targetDistrictIds()) };
}

let snapshot: DistrictScope = compute();

function emit(): void {
  const next = compute();
  if (JSON.stringify(next) !== JSON.stringify(snapshot)) snapshot = next;
  for (const l of listeners) l();
}

/** Current selection (the same object until it changes: safe for useSyncExternalStore). */
export function getScope(): DistrictScope {
  return snapshot;
}

export function subscribeScope(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Value for the `districts=` query param; undefined = all districts (no filter). */
export function scopeParam(): string | undefined {
  const s = getScope();
  return s.all ? undefined : (s.ids ?? []).join(",");
}

/** true when the district is inside the current scope (all → always). */
export function inScope(districtId: string): boolean {
  const s = getScope();
  return s.all || (s.ids ?? []).includes(districtId);
}

/** Client-side fallback filter for rows from servers that ignore `districts=` (rows without the key are kept). */
export function scopeRows<T extends Record<string, unknown>>(rows: T[], key = "district_id"): T[] {
  const s = getScope();
  if (s.all || !Array.isArray(rows)) return rows;
  const set = new Set(s.ids);
  return rows.filter((r) => !r || r[key] === undefined || r[key] === null || set.has(String(r[key])));
}

/**
 * setDistrictScope('all' | 'default' | 'target' | null | string[] | 'a,b') → true when it changed.
 * A list equal to the target districts is stored as the default (so a later programme change follows it).
 */
export function setDistrictScope(v: "all" | "default" | "target" | null | undefined | string | readonly string[]): boolean {
  let next: Selection;
  if (v === "all") next = "all";
  else if (v === null || v === undefined || v === "default" || v === "target") next = null;
  else {
    const list = Array.isArray(v) ? v : String(v).split(",");
    const ids = [...new Set(list.map((x) => String(x).trim()).filter(Boolean))];
    next = !ids.length || sameSet(ids, targetDistrictIds()) ? null : ids;
  }
  const before = JSON.stringify(sel);
  sel = next;
  try {
    if (next === null) localStorage.removeItem(SCOPE_KEY);
    else localStorage.setItem(SCOPE_KEY, next === "all" ? "all" : JSON.stringify(next));
  } catch {
    /* private mode */
  }
  const changed = before !== JSON.stringify(sel);
  if (changed) emit();
  return changed;
}

export function resetDistrictScope(): boolean {
  return setDistrictScope(null);
}

/** Serialised form for the `?d=` query: 'all', 'target' or comma ids. */
export function scopeQueryValue(): string {
  const s = getScope();
  return s.all ? "all" : s.isDefault ? "target" : (s.ids ?? []).join(",");
}

/**
 * Parse a `?d=` value. Unknown ids are dropped when `known` (the district ids) is given; returns null when
 * nothing usable is left (the caller then ignores the parameter).
 */
export function parseScopeQuery(v: string | null | undefined, known?: ReadonlySet<string>): "all" | "target" | string[] | null {
  const val = String(v ?? "").trim();
  if (!val) return null;
  if (val === "all") return "all";
  if (val === "target" || val === "default") return "target";
  const ids = val
    .split(",")
    .map((x) => x.trim())
    .filter((x) => x && (!known || !known.size || known.has(x)));
  return ids.length ? ids : null;
}

/** Feed the programme (target groups) and district names in; PortalLayout calls it when /meta and /program load. */
export function setScopeContext(next: { program?: Program | null; districts?: readonly { id: string; name?: string | null }[] }): void {
  const names = new Map(ctx.names);
  for (const d of next.districts ?? []) if (d?.id) names.set(d.id, d.name || d.id);
  for (const d of next.program?.districts ?? []) if (d?.id && !names.has(d.id)) names.set(d.id, d.name || d.id);
  ctx = { program: next.program !== undefined ? next.program : ctx.program, names };
  emit();
}

export function districtName(id: string): string {
  return ctx.names.get(id) ?? prettySlug(id);
}

/** "Guntur · Krishna · West Godavari", "All districts", "Guntur · NTR"… (whole groups use the old name). */
export function scopeLabel({ max = 4 }: { max?: number } = {}): string {
  const s = getScope();
  if (s.all) return "All districts";
  const left = new Set(s.ids);
  const parts: string[] = [];
  for (const [name, ids] of Object.entries(targetGroups())) {
    if (ids.length && ids.every((x) => left.has(x))) {
      parts.push(name);
      ids.forEach((x) => left.delete(x));
    }
  }
  for (const id of s.ids ?? []) if (left.has(id)) parts.push(districtName(id));
  if (!parts.length) return "No districts";
  return parts.length > max ? `${parts.slice(0, max - 1).join(" · ")} +${parts.length - (max - 1)} more` : parts.join(" · ");
}

/** React: the current scope; re-renders on change. */
export function useDistrictScope(): DistrictScope {
  return useSyncExternalStore(subscribeScope, getScope, getScope);
}

/** React: the scope label; re-renders when the scope or the district names / programme change. */
export function useScopeLabel(max = 4): string {
  const get = () => scopeLabel({ max });
  return useSyncExternalStore(subscribeScope, get, get);
}

/** Tests only: forget the stored selection and context. */
export function resetScopeForTests(): void {
  sel = readStored();
  ctx = { program: null, names: new Map() };
  snapshot = compute();
}
