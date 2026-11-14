/**
 * Building blocks of the district and town pages (port of the old js/views/geo.js helpers): out-of-scope note,
 * target block, summary KPIs, district picker, cities & towns list and the place map card.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { getScope, inScope, setDistrictScope, targetGroupOf, useDistrictScope } from "../../lib/scope";
import type { City, CollegeRow, District, Page, PortalMeta, Summary, ValueBasis } from "../../lib/types";
import { CollegeMap, type MapFocus } from "../../map/CollegeMap";
import { Button, Icon, LinkButton, StatCard, usePortalUi } from "../../ui";
import { Progress, ProgressNode, StatusNode, daysLeftText, isNum, itemsOf, pctText, remainingText, rowId } from "../shared/dashboard";

/** Server summary of a place (/api/summary?scope=district:x | city:y) with the place rollup fields. */
export type PlaceSummary = Summary & {
  colleges?: number;
  targeted_colleges?: number;
  operational_colleges?: number;
  cities?: number;
  colleges_with_lead?: number;
  ambassadors?: number;
  ambassador_leads?: number;
  branches_needing_ambassadors?: number;
  eligible?: ValueBasis | null;
  followups_open?: number;
  followups_overdue?: number;
  exams?: { in_exams?: number; exams_soon?: number; clear?: number; unknown?: number };
};

/** A leaderboard row (/api/leaderboard): enough for the target block and the city list. */
export type LbRow = { id?: string; scope_id?: string; target?: number | null; enrolled?: number | null; colleges?: number; [k: string]: unknown };
export const lbRows = (res: unknown): LbRow[] =>
  Array.isArray(res) ? (res as LbRow[]) : res && typeof res === "object" ? ((res as { rows?: LbRow[]; items?: LbRow[] }).rows ?? (res as { items?: LbRow[] }).items ?? []) : [];

/** 404 / 400 / "unknown scope": the place does not exist. */
export function isNotFound(err: unknown): boolean {
  const e = err as { status?: number; message?: string } | null;
  return !!e && (e.status === 404 || e.status === 400 || /unknown scope/i.test(e.message ?? ""));
}

/** Note on a district / town page outside the global district selection. */
export function OutOfScopeNote({ id, name }: { id: string; name: string }) {
  useDistrictScope(); // re-render when the selection changes
  if (inScope(id)) return null;
  const sc = getScope();
  return (
    <div className="vg-scope-note" role="note">
      <Icon name="info" size={18} />
      <div>
        <strong>{`${name} is outside the selected districts`}</strong>
        <p className="vd-muted vd-small">Home, Reports and the map leave it out. Add it to the selection to include it everywhere.</p>
      </div>
      <div className="vg-scope-act">
        <Button size="sm" tone="primary" onClick={() => setDistrictScope([...(sc.ids ?? []), id])}>
          {`Add ${name}`}
        </Button>
        <Button size="sm" onClick={() => setDistrictScope("all")}>
          All districts
        </Button>
      </div>
    </div>
  );
}

/** Target progress of the place (server summary). Rolled-up targets say how much they cover (TG-01). */
export function TargetBlock({ S, what, rows }: { S: PlaceSummary; what: string; rows?: LbRow[] | null }) {
  if (!(Number(S.target) > 0)) {
    return (
      <div className="vg-target td-card is-empty">
        <div>
          <strong>{S.target === 0 ? `Target 0 for this ${what}` : `No target for this ${what}`}</strong>
          <p className="vd-muted vd-small">{`${fmt.num(S.enrolled ?? 0)} confirmed so far.`}</p>
        </div>
        <LinkButton to={portalPath.targets} size="sm">
          Set targets
        </LinkButton>
      </div>
    );
  }
  const withT = Array.isArray(rows) ? rows.filter((r) => Number(r.target) > 0).length : null;
  const progressLine = [remainingText(S), isNum(S.pct) ? `${pctText(S.pct)} achieved` : null].filter(Boolean).join(" · ");
  return (
    <div className="vg-target td-card">
      <div className="vg-target-row">
        <strong>Target vs confirmed</strong>
        <StatusNode r={S} />
      </div>
      <Progress target={S.target} done={S.enrolled ?? 0} size="lg" />
      <div className="vg-target-meta vd-muted vd-small">
        {progressLine ? <span>{progressLine}</span> : null}
        <span>{daysLeftText(null, S.deadline)}</span>
        {S.target_source === "sum_of_children" ? (
          <span>{withT !== null && rows ? `Sum of lower-level targets · covers ${fmt.num(withT)} of ${fmt.num(rows.length)}` : "Sum of lower-level targets"}</span>
        ) : null}
      </div>
    </div>
  );
}

/** Stat card that never shows 0 for an unknown: null → "—" with a Pending basis (old dashboard.js kpi). */
function Stat({ label, value, sub, tone, icon, to, basis }: { label: string; value: number | null | undefined; sub?: string | null; tone?: string; icon?: string; to?: string; basis?: ValueBasis["basis"] }) {
  const navigate = useNavigate();
  const unknown = value === null || value === undefined || Number.isNaN(value);
  return (
    <StatCard
      label={label}
      icon={icon}
      tone={tone}
      sub={sub ?? undefined}
      value={unknown ? "—" : fmt.num(value)}
      basis={unknown ? "pending" : (basis ?? undefined)}
      onClick={to ? () => void navigate(to) : undefined}
    />
  );
}

/** Place KPIs; each links to the embedded colleges list with the matching filter (`base` = this page). */
export function SummaryKpis({ S, base }: { S: PlaceSummary; base: string }) {
  const ex = S.exams ?? {};
  const overdue = Number(S.followups_overdue) || 0;
  const need = Number(S.branches_needing_ambassadors) || 0;
  return (
    <div className="vg-kpiwrap">
      <div className="vd-kpis vd-kpis-tight vg-kpis">
        <Stat label="Targeted colleges" value={S.targeted_colleges} sub={isNum(S.operational_colleges) ? `${fmt.num(S.operational_colleges)} operational` : null} icon="college" to={`${base}?targeted=1`} />
        <Stat label="Colleges with a lead" value={S.colleges_with_lead} sub={isNum(S.targeted_colleges) ? `of ${fmt.num(S.targeted_colleges)} targeted` : null} icon="lead" to={`${base}?team=no_lead&targeted=1`} />
        <Stat label="Ambassadors" value={S.ambassadors} sub={isNum(S.ambassador_leads) ? fmt.plural(S.ambassador_leads, "ambassador lead") : null} icon="ambassador" />
        <Stat label="Target branches without ambassador" value={S.branches_needing_ambassadors} tone={need > 0 ? "warn" : undefined} icon="warn" to={`${base}?amb=gap`} />
        <Stat label="Likely prospects (est.)" value={S.eligible ? S.eligible.value : null} basis={S.eligible ? S.eligible.basis : "pending"} icon="people" />
        <Stat
          label="Follow-ups open"
          value={S.followups_open}
          sub={overdue > 0 ? `${fmt.num(overdue)} overdue` : null}
          tone={overdue > 0 ? "bad" : undefined}
          icon="followup"
          to={`${base}?followup=open`}
        />
        <Stat
          label="Exams now or in 14 days"
          value={isNum(ex.in_exams) || isNum(ex.exams_soon) ? (ex.in_exams ?? 0) + (ex.exams_soon ?? 0) : null}
          sub={isNum(ex.unknown) ? `${fmt.num(ex.unknown)} with unknown dates` : null}
          icon="exam"
          to={`${base}?exam=in_exams`}
        />
      </div>
    </div>
  );
}

export function DistrictPicker({ districts, current }: { districts: District[]; current: string }) {
  const navigate = useNavigate();
  useDistrictScope();
  const ds = [...districts].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const known = ds.some((d) => d.id === current);
  return (
    <label className="vd-field vg-picker">
      <span>Switch district</span>
      <select className="td-input td-select td-input--sm" value={known ? current : ""} onChange={(e) => e.target.value && void navigate(portalPath.district(e.target.value))}>
        {known ? null : <option value="">Choose a district…</option>}
        {ds.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name + (targetGroupOf(d.id) ? " (target)" : inScope(d.id) ? "" : " (not selected)")}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Cities & towns of a district, as compact links to the town page (most confirmed first). */
export function CityChips({ did, cities, lb }: { did: string; cities: City[]; lb: LbRow[] | null | undefined }) {
  const lbMap = new Map((lb ?? []).map((r) => [rowId(r), r]));
  const list = cities
    .filter((c) => c.district_id === did)
    .map((c) => ({ ...c, lb: lbMap.get(c.id) ?? null }))
    .filter((c) => (c.lb ? (c.lb.colleges ?? 1) > 0 : true))
    .sort((a, b) => (Number(b.lb?.enrolled) || 0) - (Number(a.lb?.enrolled) || 0) || String(a.name).localeCompare(String(b.name)));
  if (!list.length) return null;
  return (
    <details className="vg-cities">
      <summary>{`Cities & towns (${fmt.num(list.length)})`}</summary>
      <ul className="vg-citylist">
        {list.map((c) => (
          <li key={c.id}>
            <Link to={portalPath.city(did, c.id)} className="vg-city">
              <strong>{c.name}</strong>
              {c.lb && Number(c.lb.target) > 0 ? (
                <span className="vd-small">
                  <ProgressNode r={c.lb} />
                </span>
              ) : c.lb && c.lb.enrolled ? (
                <span className="vd-muted vd-small">{`${fmt.num(c.lb.enrolled)} confirmed`}</span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

const MAP_KEY = "td.geo.map";
function readMapOpen(phone: boolean): boolean {
  try {
    const v = localStorage.getItem(MAP_KEY);
    if (v !== null) return v === "1";
  } catch {
    /* private mode */
  }
  return !phone;
}

/**
 * Map card of the place: open by default on tablets and desktops, collapsed on phones; the choice is remembered
 * ('td.geo.map'). The district's own colleges are loaded, so the map is never empty outside the selection.
 */
export function PlaceMap({ districtId, title, focus, meta }: { districtId: string; title: string; focus: MapFocus; meta: PortalMeta | undefined }) {
  const { form } = usePortalUi();
  const [open, setOpen] = useState(() => readMapOpen(form === "phone"));
  const [built, setBuilt] = useState(open);
  useEffect(() => {
    if (open) setBuilt(true);
  }, [open]);
  const res = usePortalQuery<CollegeRow[] | Page<CollegeRow>>(built ? "colleges" : null, { query: { districts: districtId } });
  // filter client-side too: the static snapshot ignores query params
  const colleges = (res.data ? itemsOf(res.data) : []).filter((r) => r && r.district_id === districtId);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(MAP_KEY, next ? "1" : "0");
    } catch {
      /* private mode */
    }
  };
  return (
    <section className="vg-mapsec td-card" aria-label={`Map of ${title}`}>
      <div className="vg-mapsec-head">
        <div>
          <h2>Map</h2>
          <span className="vd-muted vd-small">{`Colleges in ${title}`}</span>
        </div>
        <Button size="sm" icon="map" aria-expanded={open} onClick={toggle}>
          {open ? "Hide map" : "Show map"}
        </Button>
      </div>
      <div className="vg-mapbox td-mapcard" hidden={!open}>
        {built ? (
          <CollegeMap
            colleges={res.data ? colleges : null}
            places={meta ? { districts: meta.districts ?? [], cities: meta.cities ?? [] } : null}
            focus={focus}
            style={{ height: 380 }}
            ariaLabel={`Map of ${title}`}
          />
        ) : null}
      </div>
    </section>
  );
}

/** "tenali" or "guntur--tenali" → "guntur--tenali" (old cityIdFrom). */
export function cityIdFrom(districtId: string, param: string | undefined): string {
  let s = String(param ?? "");
  try {
    s = decodeURIComponent(s);
  } catch {
    /* keep raw */
  }
  return s.includes("--") ? s : `${districtId}--${s}`;
}
