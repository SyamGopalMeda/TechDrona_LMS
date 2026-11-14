/**
 * React wrapper around the portal map (./engine.ts, a verbatim port of js/map/map.js on npm leaflet@1.9.4).
 * Leaflet, its CSS, the map CSS and the district GeoJSON load only when a map is first shown (lazy chunk).
 *
 *   <CollegeMap
 *     colleges={rows}                       // GET /api/colleges rows (scoped); unplaced rows are counted, not drawn
 *     places={{ districts: meta.districts, cities: meta.cities }}
 *     focus={{ kind: "district", id: "guntur" }}   // or {kind:"state"} | {kind:"city", district, id} | {kind:"college", id}
 *     highlight={hoveredCollegeId}
 *     className="td-mapcard" style={{ height: 420 }}  // give it a height
 *   />
 *
 * Features (all from the engine): district boundaries with target groups outlined and out-of-scope districts dimmed
 * (follows the global district scope automatically), district / town bubbles that become pins as you zoom,
 * the "show closed colleges" toggle (localStorage `td.map.showClosed`, shared with the panels via
 * `useShowClosed`), zoom-to-district, a reset (home) control, light/dark tiles following the portal theme,
 * touch-friendly gestures and an OSM fallback when tiles fail. Clicks navigate to the portal pages by default.
 *
 * Tiles come from tile.openstreetmap.org: the page CSP must allow them in img-src (see PORTING-GUIDE, CSP).
 */
import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import { portalPath } from "../lib/routes";
import { getScope, subscribeScope, targetDistrictIds, targetGroups } from "../lib/scope";
import type { City, CollegeRow, District } from "../lib/types";

/** The engine's public API (see engine.ts header). */
export interface MapApi {
  setColleges(rows: CollegeRow[]): void;
  setPlaces(p: { districts: District[]; cities: City[] }): void;
  setScope(s: { all: boolean; ids: string[] | null; target: string[]; groups: Record<string, readonly string[]> }): void;
  focusState(): void;
  focusDistrict(id: string): void;
  focusCity(districtId: string, cityId: string): void;
  focusCollege(id: string): void;
  highlight(id: string | null): void;
  setShowClosed(show: boolean): void;
  getClosedCount(): number;
  getUnplacedCount(): number;
  invalidateSize(): void;
  destroy(): void;
}

export type MapFocus = { kind: "state" } | { kind: "district"; id: string } | { kind: "city"; district: string; id: string } | { kind: "college"; id: string };

type EngineModule = { createMap: (el: HTMLElement, handlers: Record<string, unknown>) => MapApi };
let enginePromise: Promise<EngineModule> | null = null;
/** Load (once) the map chunk: Leaflet + CSS + engine. */
export function loadMapEngine(): Promise<EngineModule> {
  if (!enginePromise) {
    enginePromise = Promise.all([import("./engine"), import("../styles/map.css")]).then(([m]) => m as unknown as EngineModule);
    enginePromise.catch(() => {
      enginePromise = null;
    });
  }
  return enginePromise;
}

/* ---- closed-college visibility (same key + event as the engine, so map and panels stay in sync) ---- */
const CLOSED_KEY = "td.map.showClosed";
const CLOSED_EVENT = "td:closed-visibility";
function readShowClosed(): boolean {
  try {
    return localStorage.getItem(CLOSED_KEY) === "1";
  } catch {
    return false;
  }
}
export function setShowClosedPref(show: boolean): void {
  try {
    localStorage.setItem(CLOSED_KEY, show ? "1" : "0");
  } catch {
    /* private mode */
  }
  window.dispatchEvent(new CustomEvent(CLOSED_EVENT, { detail: { show } }));
}
/** React: whether possibly-closed / closed colleges are shown (lists use it to match the map). */
export function useShowClosed(): [boolean, (show: boolean) => void] {
  const v = useSyncExternalStore(
    (fn) => {
      window.addEventListener(CLOSED_EVENT, fn);
      return () => window.removeEventListener(CLOSED_EVENT, fn);
    },
    readShowClosed,
    () => false,
  );
  return [v, setShowClosedPref];
}
export const isClosedCollege = (r: { op_status?: string | null }) => r.op_status === "possibly_closed" || r.op_status === "closed";

export interface CollegeMapProps {
  colleges?: CollegeRow[] | null;
  places?: { districts: District[]; cities: City[] } | null;
  focus?: MapFocus;
  highlight?: string | null;
  className?: string;
  style?: CSSProperties;
  /** override navigation (default: open the district / town / college page; reset → Home) */
  onSelectDistrict?: (id: string) => void;
  onSelectCity?: (districtId: string, cityId: string) => void;
  onSelectCollege?: (id: string) => void;
  onReset?: () => void;
  /** the map API once ready (for screens that need more control) */
  onReady?: (api: MapApi) => void;
  ariaLabel?: string;
}

function pushScope(api: MapApi): void {
  const s = getScope();
  api.setScope({ all: s.all, ids: s.ids, target: targetDistrictIds(), groups: targetGroups() });
}

export function CollegeMap({ colleges, places, focus, highlight, className, style, onSelectDistrict, onSelectCity, onSelectCollege, onReset, onReady, ariaLabel = "Map of Andhra Pradesh" }: CollegeMapProps) {
  const el = useRef<HTMLDivElement>(null);
  const [api, setApi] = useState<MapApi | null>(null);
  const [failed, setFailed] = useState<Error | null>(null);
  const navigate = useNavigate();
  const handlers = useRef({ onSelectDistrict, onSelectCity, onSelectCollege, onReset, navigate, onReady });
  handlers.current = { onSelectDistrict, onSelectCity, onSelectCollege, onReset, navigate, onReady };

  useEffect(() => {
    let alive = true;
    let made: MapApi | null = null;
    loadMapEngine()
      .then((m) => {
        if (!alive || !el.current) return;
        made = m.createMap(el.current, {
          onSelectDistrict: (id: string) => (handlers.current.onSelectDistrict ? handlers.current.onSelectDistrict(id) : void handlers.current.navigate(portalPath.district(id))),
          onSelectCity: (d: string, c: string) => (handlers.current.onSelectCity ? handlers.current.onSelectCity(d, c) : void handlers.current.navigate(portalPath.city(d, c))),
          onSelectCollege: (id: string) => (handlers.current.onSelectCollege ? handlers.current.onSelectCollege(id) : void handlers.current.navigate(portalPath.college(id))),
          onReset: () => (handlers.current.onReset ? handlers.current.onReset() : void handlers.current.navigate(portalPath.home)),
          sheetEl: null,
        });
        pushScope(made);
        setApi(made);
        handlers.current.onReady?.(made);
      })
      .catch((e: unknown) => {
        console.warn("[map] unavailable", e);
        if (alive) setFailed(e instanceof Error ? e : new Error(String(e)));
      });
    return () => {
      alive = false;
      made?.destroy();
    };
  }, []);

  useEffect(() => {
    if (!api) return;
    return subscribeScope(() => pushScope(api));
  }, [api]);
  useEffect(() => {
    if (api && places) api.setPlaces({ districts: places.districts ?? [], cities: places.cities ?? [] });
  }, [api, places]);
  useEffect(() => {
    if (api && colleges) api.setColleges(colleges);
  }, [api, colleges]);
  const focusKey = JSON.stringify(focus ?? null);
  useEffect(() => {
    if (!api || !focus) return;
    if (focus.kind === "state") api.focusState();
    else if (focus.kind === "district") api.focusDistrict(focus.id);
    else if (focus.kind === "city") api.focusCity(focus.district, focus.id);
    else api.focusCollege(focus.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, focusKey]);
  useEffect(() => {
    if (api) api.highlight(highlight ?? null);
  }, [api, highlight]);

  if (failed) {
    return (
      <div className={className} style={style}>
        <div className="td-map-fallback">
          <div className="td-map-fallback__title">Map unavailable</div>
          <p>The map could not be loaded. Everything else works — use the list instead.</p>
        </div>
      </div>
    );
  }
  return <div ref={el} className={className ? `td-map ${className}` : "td-map"} style={style} role="region" aria-label={ariaLabel} />;
}
