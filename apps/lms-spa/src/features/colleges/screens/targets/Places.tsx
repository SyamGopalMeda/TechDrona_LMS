/**
 * Targets & performance › Targets by place (old js/views/targets.js renderPlaces): programme target, targets that
 * do not match their parts (warn only; the programme target is protected), the target tree (lazy children,
 * ?scope=type:id deep link) and the split wizard (POST /targets/allocate dry run → edit → save).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { portalApi } from "../../lib/api";
import { fetchCached, usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { prefersReducedMotion } from "../../lib/prefs";
import { portalPath, toPortalHref } from "../../lib/routes";
import type { PortalMeta } from "../../lib/types";
import { Button, EmptyState, ErrorCard, Icon, Section, Skeleton, WriteOnly, confirm, cx, toast } from "../../ui";
import { openTargetDialog } from "./TargetDialog";
import { CHILD, LEVEL, METHOD, PerfBar, STATE_ID, TYPE_LABEL, arr, daysLeftFrom, isNum, pctText, useServerToday } from "./common";

/* eslint-disable @typescript-eslint/no-explicit-any -- API rows */
type Raw = Record<string, any>;

interface Wiz {
  parent_type: string;
  parent_id: string;
  district: string;
  college: string;
  course_id: string;
  total: string;
  method: string;
  only_targeted: boolean;
  deadline: string;
  alsoParent: boolean;
  preview: { params: Raw; rows: Raw[]; total: number } | null;
}
const smooth = (): ScrollBehavior => (prefersReducedMotion() ? "auto" : "smooth");
const errText = (e: unknown) => (e && typeof e === "object" && "message" in e ? String((e as { message: unknown }).message) : String(e));

export function scrollToWizard(): void {
  document.getElementById("tg-wizard")?.scrollIntoView?.({ behavior: smooth(), block: "start" });
}

export function Places({ scope }: { scope?: string }) {
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const state = usePortalQuery<Raw>("summary", { query: { scope: "state" } });
  const districts = usePortalQuery<unknown>("leaderboard", { query: { level: "district", scope: "state", limit: 500 } });
  const recon = usePortalQuery<unknown>("targets/unreconciled");
  const targets = usePortalQuery<unknown>("targets", { query: { limit: 5000 } });
  const colleges = usePortalQuery<unknown>("colleges");
  const today = useServerToday();

  const [open, setOpen] = useState<Set<string>>(() => new Set(["state"]));
  const [showAll, setShowAll] = useState(false);
  const [kids, setKids] = useState<Map<string, Raw[]>>(() => new Map());
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [wiz, setWiz] = useState<Wiz>({ parent_type: "state", parent_id: "", district: "", college: "", course_id: "", total: "", method: "eligible", only_targeted: true, deadline: "", alsoParent: false, preview: null });
  const revealed = useRef(false);

  const error = meta.error || state.error || districts.error || targets.error || colleges.error;
  const ready = !!(meta.data && state.data && districts.data && targets.data && colleges.data);
  const reconRows = useMemo(() => (recon.error ? [] : arr<Raw>(recon.data)), [recon.data, recon.error]);
  const collegeRows = useMemo(() => arr<Raw>(colleges.data), [colleges.data]);
  const cMap = useMemo(() => new Map(collegeRows.map((c) => [String(c.id), c])), [collegeRows]);
  const dMeta = useMemo(() => new Map((meta.data?.districts || []).map((d) => [d.id, d as Raw])), [meta.data]);
  const explicit = useMemo(
    () => new Map(arr<Raw>(targets.data).filter((t) => t.course_id == null && (!t.period || t.period === "programme")).map((t) => [`${t.scope_type}:${t.scope_id}`, t])),
    [targets.data],
  );
  const unrec = useMemo(() => new Map(reconRows.filter((r) => r.course_id == null).map((r) => [`${r.scope_type}:${r.scope_id}`, r])), [reconRows]);

  // a save refetches every query: start the tree again from fresh rollups (open rows stay open)
  useEffect(() => {
    setKids(new Map());
  }, [targets.data, state.data]);
  const allKids = useMemo(() => {
    const m = new Map(kids);
    if (districts.data) m.set("state", arr<Raw>(districts.data));
    return m;
  }, [kids, districts.data]);

  const loading = useRef(new Set<string>());
  const childrenOf = useCallback(async (key: string): Promise<Raw[]> => {
    const [type, id = ""] = key.split(/:(.*)/s);
    let rows: Raw[] = [];
    if (type === "district") rows = arr<Raw>(await fetchCached("leaderboard", { query: { level: "city", scope: `district:${id}`, limit: 500 } }));
    else if (type === "city") rows = arr<Raw>(await fetchCached("leaderboard", { query: { level: "college", scope: `city:${id}`, limit: 500 } }));
    else if (type === "college") {
      const [lb, rel] = await Promise.all([
        fetchCached("leaderboard", { query: { level: "branch", scope: `college:${id}`, limit: 500 } }).then((x) => arr<Raw>(x)),
        fetchCached("branches", { query: { college: id, relevant: 1 } })
          .then((x) => arr<Raw>(x))
          .catch(() => null),
      ]);
      const ok = rel ? new Set(rel.map((b) => String(b.id))) : null;
      rows = lb.filter((b) => !ok || ok.has(String(b.id))).map((b) => ({ ...b, label: String(b.label).split(" · ")[0] }));
    }
    return rows;
  }, []);
  const ensureKids = useCallback(
    (key: string) => {
      if (key === "state" || loading.current.has(key)) return;
      loading.current.add(key);
      childrenOf(key)
        .catch(() => [] as Raw[])
        .then((rows) => {
          loading.current.delete(key);
          setKids((m) => new Map(m).set(key, rows));
        });
    },
    [childrenOf],
  );

  // deep link: expand the tree down to `type:id`
  useEffect(() => {
    if (!ready || revealed.current || !scope) return;
    revealed.current = true;
    const [type, id = ""] = String(scope).split(":");
    const add: string[] = ["state"];
    let fk: string | null = null;
    if (type === "district") fk = `district:${id}`;
    if (type === "city") {
      const city = (meta.data!.cities || []).find((x) => x.id === id);
      if (city) {
        add.push(`district:${city.district_id}`);
        fk = `city:${id}`;
      }
    }
    const c = type === "college" ? cMap.get(id) : null;
    if (c) {
      if (!c.targeted) setShowAll(true);
      add.push(`district:${c.district_id}`);
      if (c.city_id) add.push(`city:${c.city_id}`);
      fk = `college:${id}`;
    }
    setOpen((o) => new Set([...o, ...add]));
    setFocusKey(fk);
  }, [ready, scope, cMap, meta.data]);
  useEffect(() => {
    if (!focusKey) return;
    const el = document.querySelector<HTMLElement>(`[data-key="${CSS.escape(focusKey)}"]`);
    if (el && !el.classList.contains("is-flashed")) {
      el.scrollIntoView?.({ block: "center" });
      el.classList.add("is-flash", "is-flashed");
    }
  });

  if (error && !ready) {
    return (
      <ErrorCard
        title="Could not load targets"
        error={error}
        retry={() => {
          void meta.reload();
          void state.reload();
          void districts.reload();
          void targets.reload();
          void colleges.reload();
        }}
      />
    );
  }
  if (!ready) {
    return (
      <>
        <Skeleton lines={3} />
        <Skeleton lines={5} />
      </>
    );
  }
  const m = meta.data!;
  const s = state.data!;
  const deadlineDefault = wiz.deadline || s.deadline || String((m.settings as Raw)?.state_target_deadline ?? "") || "";
  const ctx: TreeCtx = { m, s, kids: allKids, open, showAll, explicit, unrec, cMap, dMeta, colleges: collegeRows, focusKey, today, ensureKids };

  return (
    <>
      <TopSection s={s} courses={m.courses || []} today={today} />
      <ReconSection
        rows={reconRows}
        meta={m}
        explicit={explicit}
        onResplit={(r) => {
          const city = r.scope_type === "city" ? (m.cities || []).find((x) => x.id === r.scope_id) : null;
          setWiz((w) => ({ ...w, parent_type: r.scope_type, parent_id: r.scope_type === "state" ? "" : String(r.scope_id), district: city?.district_id || "", college: "", total: String(r.target), course_id: r.course_id ? String(r.course_id) : "", preview: null }));
          requestAnimationFrame(scrollToWizard);
        }}
      />
      <Section
        title="Target tree"
        sub='Open a place to see its parts. "Own" = a target set directly; "Sum" = no own target, so it adds up its parts. All courses, whole programme. Pace and status are on the Performance tab.'
        actions={
          <label className="tg-toggle">
            <input type="checkbox" className="td-check" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            <span>Show places we are not targeting</span>
          </label>
        }
      >
        <div className="tg-tree-host">
          <Tree
            ctx={ctx}
            onToggle={(key) =>
              setOpen((o) => {
                const n = new Set(o);
                if (n.has(key)) n.delete(key);
                else n.add(key);
                return n;
              })
            }
          />
        </div>
      </Section>
      <div id="tg-wizard">
        <Section title="Split a target" sub='Share one number out across the parts of a place. Nothing is saved until you press "Save these targets".'>
          <Wizard wiz={{ ...wiz, deadline: deadlineDefault }} setWiz={setWiz} meta={m} colleges={collegeRows} explicit={explicit} />
        </Section>
      </div>
    </>
  );
}

const Kpi = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) => (
  <div className={cx("tg-kpi", tone && `is-${tone}`)}>
    <span className="tg-kpi__label">{label}</span>
    <strong className="tg-kpi__value td-num">{value}</strong>
    {sub ? <span className="tg-kpi__sub">{sub}</span> : null}
  </div>
);

/* ---------- programme summary */
function TopSection({ s, courses, today }: { s: Raw; courses: Raw[]; today: string | null }) {
  const byCourse = new Map((s.by_course || []).map((c: Raw) => [String(c.course_id), c]));
  const srcLabel = ({ explicit: "set directly", sum_of_children: "adds up the district targets", none: "not set yet" } as Record<string, string>)[s.target_source] || "";
  const hasT = s.target > 0;
  return (
    <Section
      title="Programme target"
      sub={hasT ? `All courses · ${srcLabel}` : "No programme target yet"}
      actions={
        <WriteOnly>
          <Button icon="edit" size="sm" tone={hasT ? "secondary" : "primary"} onClick={() => void openTargetDialog({ scope_type: "state", scope_id: STATE_ID, label: "the programme", period: "programme" })}>
            {hasT ? "Change" : "Set programme target"}
          </Button>
        </WriteOnly>
      }
    >
      <div className="tg-top">
        <div className="tg-kpis">
          <Kpi label="Target" value={hasT ? fmt.num(s.target) : "Not set"} sub={hasT ? null : "Set it here or split one below"} />
          <Kpi label="Paid enrollments" value={fmt.num(s.enrolled ?? 0)} sub={s.reached ? `${fmt.num(s.reached)} students reached (logged activities)` : "students reached: no activity logged"} />
          <Kpi label="Still needed" value={hasT ? fmt.num(s.remaining) : "—"} />
          <Kpi label="Deadline" value={s.deadline ? fmt.date(s.deadline) : "Not set"} sub={s.deadline ? daysLeftFrom(today, s.deadline) : "set it in Settings"} />
        </div>
        {hasT ? <PerfBar r={{ actual: s.enrolled ?? 0, target: s.target }} lg /> : null}
        {hasT ? (
          <p className="tgp-muted tgp-small td-num">
            {fmt.num(s.enrolled ?? 0)} of {fmt.num(s.target)} · {pctText(isNum(s.pct) ? s.pct * 100 : null)}. Pace and status for people, colleges and districts are on the Performance tab.
          </p>
        ) : null}
        {courses.length ? (
          <div className="tg-courses">
            <span className="tg-courses__title">By course</span>
            {courses.map((c) => {
              const r: Raw = byCourse.get(String(c.id)) || {};
              return (
                <div key={c.id} className={cx("tg-course", !c.active && "is-off")}>
                  <strong>
                    {c.name}
                    {!c.active ? <span className="tgp-muted"> (inactive)</span> : null}
                  </strong>
                  <span className="tgp-muted">{fmt.inr(c.price_inr)} per student</span>
                  <span className="td-num">
                    {fmt.num(r.enrolled ?? 0)} confirmed{r.target ? ` of ${fmt.num(r.target)}` : " · no course target"}
                  </span>
                  {r.revenue_inr ? <span className="tgp-muted td-num">{fmt.inr(r.revenue_inr)} revenue</span> : null}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="tgp-muted">
            No courses yet, so targets count enrollments in any course. <Link to={portalPath.settings}>Add courses and prices in Settings</Link>.
          </p>
        )}
      </div>
    </Section>
  );
}

/* ---------- reconciliation: warn only. Never offer "use the sum of its parts" for the programme (TG-09, R11). */
function ReconSection({ rows, meta, explicit, onResplit }: { rows: Raw[]; meta: PortalMeta; explicit: Map<string, Raw>; onResplit: (r: Raw) => void }) {
  if (!rows.length)
    return (
      <div className="tg-allgood">
        <Icon name="check" size={18} />
        <span>
          <strong>Everything adds up. </strong>Every place with its own target matches the sum of its parts (or its parts have no targets yet).
        </span>
      </div>
    );
  const courseName = (id: unknown) => (meta.courses || []).find((c) => c.id === id)?.name;
  const useSum = async (r: Raw) => {
    const sum = r.children_target_sum ?? 0;
    const ok = await confirm({
      title: `Change ${r.label}'s target?`,
      text: `${r.label}: own target ${fmt.num(r.target)} → ${fmt.num(sum)} (the sum of the targets set for its ${CHILD[r.scope_type] || "parts"}). Parts without a target count as 0.`,
      confirmLabel: `Set to ${fmt.num(sum)}`,
      tone: "primary",
    });
    if (!ok) return;
    try {
      await portalApi.post("targets", { scope_type: r.scope_type, scope_id: String(r.scope_id), course_id: r.course_id ?? null, target: sum, deadline: explicit.get(`${r.scope_type}:${r.scope_id}`)?.deadline || null });
      toast(`${r.label}: target is now ${fmt.num(sum)}`, "good");
    } catch (e) {
      toast(errText(e), "bad");
    }
  };
  return (
    <Section
      title={`Targets that don't match their parts (${rows.length})`}
      sub="These places have their own target, but the targets set for their parts add up to a different number. Often that is fine (not every part has a target yet). The programme target is never changed from here."
    >
      <ul className="tg-recon">
        {rows.map((r, i) => {
          const diff = (r.children_target_sum ?? 0) - r.target;
          const protectedRow = r.scope_type === "state";
          return (
            <li key={`${r.scope_type}:${r.scope_id}:${r.course_id ?? ""}:${i}`} className="tg-recon__row">
              <div className="tg-recon__main">
                <div>
                  {r.href ? <Link to={toPortalHref(r.href)}>{protectedRow ? "Programme" : r.label}</Link> : <strong>{protectedRow ? "Programme" : r.label}</strong>} <span className="tg-pill">{TYPE_LABEL[r.scope_type] || r.scope_type}</span>
                  {r.course_id ? <span className="tg-pill">{courseName(r.course_id) || `course ${r.course_id}`}</span> : null}
                </div>
                <div className="tg-recon__nums td-num">
                  <span>
                    Own target <strong>{fmt.num(r.target)}</strong>
                  </span>
                  <span>
                    Targets set for its {CHILD[r.scope_type] || "parts"} add up to <strong>{fmt.num(r.children_target_sum ?? 0)}</strong>
                  </span>
                  <span className={diff > 0 ? "is-over" : "is-under"}>{diff > 0 ? `${fmt.num(diff)} more than the target` : `${fmt.num(-diff)} not yet given to any part`}</span>
                </div>
                {protectedRow ? <p className="tgp-muted">Protected: the programme target stays as it is. Split it below to give every district a share.</p> : null}
              </div>
              <WriteOnly>
                <div className="tg-recon__actions">
                  {!protectedRow ? (
                    <Button size="sm" title="Change this place's own target to the sum of its parts" onClick={() => void useSum(r)}>
                      Use {fmt.num(r.children_target_sum ?? 0)}
                    </Button>
                  ) : null}
                  {r.scope_type !== "person" ? (
                    <Button size="sm" tone="primary" title="Open the wizard with this target to split it across its parts again" onClick={() => onResplit(r)}>
                      Re-split {fmt.num(r.target)}
                    </Button>
                  ) : null}
                </div>
              </WriteOnly>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/* ---------- tree */
interface TreeCtx {
  m: PortalMeta;
  s: Raw;
  kids: Map<string, Raw[]>;
  open: Set<string>;
  showAll: boolean;
  explicit: Map<string, Raw>;
  unrec: Map<string, Raw>;
  cMap: Map<string, Raw>;
  dMeta: Map<string, Raw>;
  colleges: Raw[];
  focusKey: string | null;
  today: string | null;
  ensureKids: (key: string) => void;
}
type Node = { msg: string; depth: number } | { msg?: undefined; key: string; depth: number; type: string; id: string; label: string; r: Raw; href?: string; hasKids: boolean };

function visibleKids(ctx: TreeCtx, key: string): Raw[] {
  const rows = ctx.kids.get(key) || [];
  if (ctx.showAll) return rows;
  const [type] = key.split(":");
  if (type === "state") return rows.filter((d) => d.target || ctx.dMeta.get(d.id)?.targeted || ctx.explicit.has(`district:${d.id}`));
  if (type === "district") return rows.filter((c) => c.target || ((ctx.m.cities || []).some((x) => x.id === c.id) && ctx.colleges.some((k) => k.city_id === c.id && k.targeted)));
  if (type === "city") return rows.filter((c) => c.target || ctx.cMap.get(String(c.id))?.targeted);
  return rows;
}

function Tree({ ctx, onToggle }: { ctx: TreeCtx; onToggle: (key: string) => void }) {
  const out: Node[] = [];
  const pending: string[] = [];
  const walk = (key: string, depth: number) => {
    if (!ctx.open.has(key)) return;
    if (!ctx.kids.has(key)) {
      out.push({ msg: "Loading…", depth });
      pending.push(key);
      return;
    }
    const kids = visibleKids(ctx, key)
      .slice()
      .sort((a, b) => (b.target ?? -1) - (a.target ?? -1) || String(a.label).localeCompare(String(b.label)));
    const hidden = (ctx.kids.get(key) || []).length - kids.length;
    if (!kids.length) out.push({ msg: hidden ? `Nothing targeted here (${hidden} hidden — tick "Show places we are not targeting").` : `No ${CHILD[key.split(":")[0]!]} recorded.`, depth });
    for (const k of kids) {
      const type = String(k.type);
      const kk = `${type}:${k.id}`;
      const label = type === "college" ? ctx.cMap.get(String(k.id))?.name || k.label : k.label;
      out.push({ key: kk, depth, type, id: String(k.id), label, r: k, href: k.href, hasKids: type !== "branch" });
      if (type !== "branch") walk(kk, depth + 1);
    }
    if (hidden && kids.length) out.push({ msg: `${hidden} more not targeted — tick "Show places we are not targeting" to see them.`, depth });
  };
  out.push({ key: "state", depth: 0, type: "state", id: STATE_ID, label: "Programme", r: ctx.s, hasKids: true });
  walk("state", 1);
  useEffect(() => {
    pending.forEach((k) => ctx.ensureKids(k));
  });
  const s = ctx.s;
  return (
    <div className="tg-tree" role="treegrid" aria-label="Targets by place">
      <div className="tg-tr tg-tr--head" role="row">
        {["Place", "Target", "Paid enrollments", "Progress", "Deadline", ""].map((t, i) => (
          <span key={i} role="columnheader">
            {t}
          </span>
        ))}
      </div>
      {out.map((n, i) => {
        if (n.msg !== undefined)
          return (
            <div key={`msg${i}`} className="tg-tr tg-tr--msg" role="row" style={{ "--d": n.depth } as CSSProperties}>
              <span role="gridcell">{n.msg}</span>
            </div>
          );
        const r = n.r || {};
        const isOpen = ctx.open.has(n.key);
        const ex = ctx.explicit.get(`${n.type}:${n.id}`);
        const bad = ctx.unrec.get(`${n.type}:${n.id}`);
        const src =
          r.target_source === "explicit" ? (
            <span className="tg-src is-own" title="Target set directly for this place">
              Own
            </span>
          ) : r.target_source === "sum_of_children" ? (
            <span className="tg-src" title="No own target — this is the sum of its parts">
              Sum
            </span>
          ) : null;
        const deadline = ex?.deadline || (n.type === "state" ? s.deadline : null);
        const hasT = r.target != null && r.target !== 0 ? true : r.target === 0 && r.target_source === "explicit";
        const pctP = r.target > 0 && isNum(r.pct) ? r.pct * 100 : null;
        return (
          <div
            key={n.key}
            className={cx("tg-tr", `tg-d${Math.min(n.depth, 4)}`, bad && "is-unrec", ctx.focusKey === n.key && "is-focus")}
            role="row"
            aria-level={n.depth + 1}
            aria-expanded={n.hasKids ? isOpen : undefined}
            data-key={n.key}
            style={{ "--d": n.depth } as CSSProperties}
          >
            <span className="tg-name" role="gridcell">
              {n.hasKids ? (
                <button type="button" className={cx("tg-twisty", isOpen && "is-open")} aria-label={`${isOpen ? "Hide" : "Show"} parts of ${n.label}`} aria-expanded={isOpen} onClick={() => onToggle(n.key)}>
                  <Icon name="chevron" size={16} />
                </button>
              ) : (
                <span className="tg-twisty-sp" />
              )}
              <span className="tg-name__txt">
                {n.href ? <Link to={toPortalHref(n.href)}>{n.label}</Link> : <strong>{n.label}</strong>}
                <small className="tg-type">{TYPE_LABEL[n.type]}</small>
              </span>
            </span>
            <span className="tg-c-target td-num" role="gridcell" data-label="Target">
              {hasT ? fmt.num(r.target) : <span className="tgp-muted">—</span>}
              {src}
              {bad ? (
                <span className="tg-flag" title={`Its parts add up to ${fmt.num(bad.children_target_sum)}`}>
                  <Icon name="warn" size={14} />
                </span>
              ) : null}
            </span>
            <span className="tg-c-enr td-num" role="gridcell" data-label="Paid enrollments">
              {fmt.num(r.enrolled ?? 0)}
            </span>
            <span className="tg-c-prog" role="gridcell">
              {r.target > 0 ? (
                <span className="tg-bar" title={`${fmt.num(r.enrolled ?? 0)} of ${fmt.num(r.target)}`}>
                  <span className="tg-track">
                    <i className={r.pct >= 0.6 ? "is-good" : r.pct >= 0.3 ? "is-warn" : "is-bad"} style={{ width: `${Math.min(100, (r.pct || 0) * 100)}%` }} />
                  </span>
                  <span className="td-num">{pctText(pctP)}</span>
                </span>
              ) : (
                <span className="tgp-muted">{r.target === 0 && r.target_source === "explicit" ? "target is 0" : "no target"}</span>
              )}
            </span>
            <span className="tg-c-dl" role="gridcell" data-label="Deadline">
              {deadline ? (
                fmt.date(deadline)
              ) : (
                <span className="tgp-muted" title="Uses the deadline of the place above it, or the programme deadline">
                  {n.depth ? "inherited" : "—"}
                </span>
              )}
            </span>
            <span className="tg-c-act" role="gridcell">
              <WriteOnly>
                <Button
                  icon="edit"
                  tone="ghost"
                  size="sm"
                  ariaLabel={`Set target for ${n.label}`}
                  onClick={() => void openTargetDialog({ scope_type: n.type, scope_id: n.id, label: n.type === "state" ? "the programme" : n.label, period: "programme" })}
                />
              </WriteOnly>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ---------- allocation wizard */
function WField({ label, help, children, id }: { label: string; help?: string; children: ReactNode; id: string }) {
  return (
    <div className="td-field">
      <label className="td-field__label" htmlFor={id}>
        {label}
      </label>
      {children}
      {help ? <div className="td-field__help">{help}</div> : null}
    </div>
  );
}
function WSel({ id, opts, value, onChange }: { id: string; opts: [string, string][]; value: string; onChange: (v: string) => void }) {
  return (
    <select id={id} className="td-input td-select" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {opts.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
}

function Wizard({ wiz: w, setWiz, meta, colleges, explicit }: { wiz: Wiz; setWiz: (f: (w: Wiz) => Wiz) => void; meta: PortalMeta; colleges: Raw[]; explicit: Map<string, Raw> }) {
  const patch = (p: Partial<Wiz>) => setWiz((x) => ({ ...x, ...p }));
  const reset = { preview: null };
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const totalRef = useRef<HTMLInputElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const branchesQ = usePortalQuery<unknown>(w.parent_type === "branch" && w.college ? "branches" : null, { query: { college: w.college, relevant: 1 } });

  const districts = [...(meta.districts || [])].sort((a: Raw, b: Raw) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || String(a.name).localeCompare(String(b.name)));
  const dOpts: [string, string][] = [["", "Choose a district…"], ...districts.map((d: Raw) => [d.id, d.name + (d.targeted ? " — targeted" : "")] as [string, string])];
  const place: ReactNode[] = [];
  if (w.parent_type === "district")
    place.push(
      <WField key="d" id="tgw-d" label="District">
        <WSel id="tgw-d" opts={dOpts} value={w.parent_id} onChange={(v) => patch({ parent_id: v, ...reset })} />
      </WField>,
    );
  if (w.parent_type === "city") {
    const cities = (meta.cities || []).filter((c) => c.district_id === w.district).sort((a, b) => a.name.localeCompare(b.name));
    place.push(
      <WField key="d" id="tgw-d" label="District">
        <WSel id="tgw-d" opts={dOpts} value={w.district} onChange={(v) => patch({ district: v, parent_id: "", ...reset })} />
      </WField>,
      <WField key="c" id="tgw-c" label="City / town">
        <WSel
          id="tgw-c"
          opts={[["", w.district ? "Choose…" : "Choose a district first"], ...cities.map((c: Raw) => [c.id, `${c.name} (${c.colleges || 0} colleges)`] as [string, string])]}
          value={w.parent_id}
          onChange={(v) => patch({ parent_id: v, ...reset })}
        />
      </WField>,
    );
  }
  if (w.parent_type === "college" || w.parent_type === "branch") {
    const cs = [...colleges].sort((a, b) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || String(a.name).localeCompare(String(b.name)));
    const cv = w.parent_type === "college" ? w.parent_id : w.college;
    place.push(
      <WField key="col" id="tgw-col" label="College">
        <WSel
          id="tgw-col"
          opts={[["", "Choose a college…"], ...cs.map((c) => [String(c.id), c.name + (c.targeted ? " — targeted" : "")] as [string, string])]}
          value={cv}
          onChange={(v) => (w.parent_type === "college" ? patch({ parent_id: v, ...reset }) : patch({ college: v, parent_id: "", ...reset }))}
        />
      </WField>,
    );
    if (w.parent_type === "branch") {
      const bs = arr<Raw>(branchesQ.data);
      const bOpts: [string, string][] = !w.college
        ? [["", "Choose a college first"]]
        : branchesQ.error
          ? [["", "Could not load branches"]]
          : !branchesQ.data
            ? [["", "Loading branches…"]]
            : [["", bs.length ? "Choose a branch…" : "No relevant branches recorded"], ...bs.map((b) => [String(b.id), `${b.code || ""} ${b.name}`.trim()] as [string, string])];
      place.push(
        <WField key="b" id="tgw-b" label="Branch">
          <WSel id="tgw-b" opts={bOpts} value={w.parent_id} onChange={(v) => patch({ parent_id: v, ...reset })} />
        </WField>,
      );
    }
  }
  const courses = meta.courses || [];
  const params = () => ({
    parent_type: w.parent_type,
    parent_id: w.parent_type === "state" ? null : w.parent_id,
    course_id: w.course_id ? Number(w.course_id) : null,
    total: Number(w.total),
    method: w.method,
    only_targeted: w.only_targeted,
    deadline: w.deadline || null,
  });
  const preview = async () => {
    setErr(null);
    if (w.parent_type !== "state" && !w.parent_id) return setErr("Choose where the target starts first.");
    if (!(Number(w.total) > 0) || !Number.isInteger(Number(w.total))) {
      totalRef.current?.focus();
      return setErr("Enter a whole number greater than 0 for the total.");
    }
    setBusy(true);
    try {
      const res = await portalApi.post<Raw>("targets/allocate", { ...params(), dry_run: true });
      patch({ preview: { params: params(), rows: (res.rows || []).map((r: Raw) => ({ ...r, value: r.proposed })), total: res.total ?? Number(w.total) } });
      requestAnimationFrame(() => previewRef.current?.scrollIntoView?.({ behavior: smooth(), block: "nearest" }));
    } catch (e) {
      const pe = e as { message?: string; fields?: Record<string, string> };
      setErr([pe.message, ...Object.entries(pe.fields || {}).map(([k, v]) => `${k}: ${v}`)].join(" — "));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tg-wizard">
      <div className="tg-step">
        <h3 className="tg-step__title">
          <span className="tg-step__n">1</span>Where does the number start, and how big is it?
        </h3>
        <div className="td-form__grid">
          <WField id="tgw-from" label="Start from">
            <WSel
              id="tgw-from"
              opts={Object.entries(LEVEL).map(([k, l]) => [k, `${l} → split across its ${CHILD[k]}`] as [string, string])}
              value={w.parent_type}
              onChange={(v) => patch({ parent_type: v, parent_id: "", college: "", ...reset })}
            />
          </WField>
          {place}
          <WField id="tgw-total" label="Total enrollments to share out">
            <input ref={totalRef} id="tgw-total" type="number" min={1} step={1} inputMode="numeric" className="td-input td-num" value={w.total} placeholder="e.g. 500" onChange={(e) => patch({ total: e.target.value })} />
          </WField>
          <WField id="tgw-course" label="Course">
            <WSel id="tgw-course" opts={[["", "All courses"], ...courses.map((c) => [String(c.id), `${c.name} (${fmt.inr(c.price_inr)})`] as [string, string])]} value={w.course_id} onChange={(v) => patch({ course_id: v, ...reset })} />
          </WField>
          <WField id="tgw-dl" label="Deadline" help="Pre-filled with the programme deadline.">
            <input id="tgw-dl" type="date" className="td-input td-num" value={w.deadline || ""} onChange={(e) => patch({ deadline: e.target.value })} />
          </WField>
        </div>
        <div className="td-field">
          <span className="td-field__label">How to share it out</span>
          <div className="tg-methods" role="radiogroup" aria-label="How to split">
            {Object.entries(METHOD).map(([k, [l, help]]) => (
              <label key={k} className={cx("tg-method", w.method === k && "is-on")}>
                <input type="radio" name="tg-method" value={k} checked={w.method === k} onChange={() => patch({ method: k, ...reset })} />
                <span>
                  <strong>{l}</strong>
                  <small>{help}</small>
                </span>
              </label>
            ))}
          </div>
        </div>
        {["state", "district", "city"].includes(w.parent_type) ? (
          <label className="tg-toggle">
            <input type="checkbox" className="td-check" checked={w.only_targeted} onChange={(e) => patch({ only_targeted: e.target.checked, ...reset })} />
            <span>Only include colleges we are targeting</span>
          </label>
        ) : null}
        {err ? (
          <div className="td-form__error" role="alert">
            {err}
          </div>
        ) : null}
        <div className="tg-step__foot">
          <Button tone="primary" icon="chevron" busy={busy} onClick={() => void preview()}>
            Preview the split
          </Button>
        </div>
      </div>
      {w.preview ? (
        <div ref={previewRef}>
          <PreviewStep wiz={w} explicit={explicit} onDiscard={() => patch({ preview: null })} onSaved={() => patch({ preview: null })} setAlsoParent={(v) => patch({ alsoParent: v })} setRows={(rows) => patch({ preview: { ...w.preview!, rows } })} />
        </div>
      ) : null}
      <details className="tg-explain">
        <summary>How is the split worked out?</summary>
        <ul>
          <li>
            &quot;By likely prospects&quot; uses final-year students in each place × the branch relevance factors from Settings. Places whose numbers are still pending get a smaller share, shown as &quot;pending&quot;.
          </li>
          <li>Numbers are whole people. Remainders go to the places closest to the next whole number, so the parts always add up exactly to your total.</li>
          <li>You can change any number before saving; the sum is checked as you type.</li>
          <li>Every saved target is recorded in the audit log with your name.</li>
        </ul>
      </details>
    </div>
  );
}

function PreviewStep({
  wiz: w,
  explicit,
  onDiscard,
  onSaved,
  setAlsoParent,
  setRows,
}: {
  wiz: Wiz;
  explicit: Map<string, Raw>;
  onDiscard: () => void;
  onSaved: () => void;
  setAlsoParent: (v: boolean) => void;
  setRows: (rows: Raw[]) => void;
}) {
  const p = w.preview!;
  const [busy, setBusy] = useState(false);
  const typeKey = (r: Raw) => `${r.scope_type}:${r.scope_id}`;
  const replacing = p.params.course_id == null ? p.rows.filter((r) => explicit.has(typeKey(r))).length : 0;
  const basisTotal = p.rows.reduce((s, r) => s + (Number(r.basis_value) || 0), 0);
  const sum = p.rows.reduce((s, r) => s + (Number(r.value) || 0), 0);
  const isProg = p.params.parent_type === "state";
  const child = CHILD[p.params.parent_type];
  const apply = async () => {
    setBusy(true);
    const edited = p.rows.some((r) => Number(r.value) !== Number(r.proposed));
    try {
      if (!edited) await portalApi.post("targets/allocate", { ...p.params, dry_run: false });
      else
        for (const r of p.rows)
          await portalApi.post("targets", { scope_type: r.scope_type, scope_id: String(r.scope_id), course_id: p.params.course_id, target: Number(r.value) || 0, deadline: p.params.deadline });
      if (w.alsoParent && !isProg) await portalApi.post("targets", { scope_type: p.params.parent_type, scope_id: String(p.params.parent_id), course_id: p.params.course_id, target: p.total, deadline: p.params.deadline });
      toast(`Saved ${fmt.num(p.rows.length)} targets`, "good");
      onSaved();
    } catch (e) {
      toast(errText(e), "bad");
      setBusy(false);
    }
  };
  return (
    <div className="tg-step tg-preview">
      <h3 className="tg-step__title">
        <span className="tg-step__n">2</span>
        {`Check the split across ${fmt.num(p.rows.length)} ${child}`}
      </h3>
      {!p.rows.length ? (
        <EmptyState
          title="Nothing to split across"
          icon="target"
          text={`No ${child} found here${p.params.only_targeted ? ' among the colleges we are targeting. Untick "Only include colleges we are targeting" to include all.' : "."}`}
        />
      ) : (
        <p className="tg-sum">
          The parts add up to{" "}
          <strong className={`td-num ${sum === p.total ? "tg-ok" : "tg-bad"}`}>
            {fmt.num(sum)} of {fmt.num(p.total)}
          </strong>
          .
        </p>
      )}
      {p.rows.length ? (
        <div className="td-table-wrap">
          <div className="td-table-scroll">
            <table className="td-table tg-ptable">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="td-al-right">{METHOD[p.params.method]![0].replace("By ", "Based on ")}</th>
                  <th className="td-al-right" title="Target set directly for this place today, if any">
                    Own target now
                  </th>
                  <th className="td-al-right">Suggested</th>
                  <th className="td-al-right">New target</th>
                </tr>
              </thead>
              <tbody>
                {p.rows.map((r, i) => {
                  const ex = explicit.get(typeKey(r));
                  return (
                    <tr key={typeKey(r)}>
                      <td data-label="Name">{r.label}</td>
                      <td className="td-al-right td-num" data-label="Based on">
                        {r.basis_value == null ? <span className="tgp-muted">pending</span> : fmt.num(r.basis_value)}
                        {basisTotal && r.basis_value ? <small className="tgp-muted"> · {pctText((r.basis_value / basisTotal) * 100)}</small> : null}
                      </td>
                      <td className="td-al-right td-num" data-label="Current">
                        {ex && p.params.course_id == null ? fmt.num(ex.target) : <span className="tgp-muted">—</span>}
                      </td>
                      <td className="td-al-right td-num" data-label="Suggested">
                        {fmt.num(r.proposed)}
                      </td>
                      <td className="td-al-right" data-label="New target">
                        <input
                          type="number"
                          min={0}
                          step={1}
                          inputMode="numeric"
                          className="td-input td-input--sm td-num tg-num"
                          value={r.value}
                          aria-label={`Target for ${r.label}`}
                          onChange={(e) => {
                            const v = e.target.value === "" ? 0 : Math.max(0, Math.round(Number(e.target.value)));
                            setRows(p.rows.map((x, j) => (j === i ? { ...x, value: v } : x)));
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      {sum !== p.total && p.rows.length ? (
        <div className="tg-warn" role="status">
          The parts add up to {fmt.num(sum)}, not {fmt.num(p.total)} ({sum > p.total ? "+" : ""}
          {fmt.num(sum - p.total)}). You can still save, but this place will be listed under &quot;Targets that don&apos;t match their parts&quot;.
        </div>
      ) : null}
      {replacing ? (
        <p className="tg-note">
          <Icon name="warn" size={16} />
          {`${fmt.num(replacing)} of these already have their own target; saving replaces them.`}
        </p>
      ) : null}
      {p.rows.length ? (
        <label className="tg-toggle">
          <input type="checkbox" className="td-check" checked={w.alsoParent && !isProg} disabled={isProg} onChange={(e) => setAlsoParent(e.target.checked)} />
          <span>{isProg ? 'The programme target is not changed by a split (change it with "Change" above).' : `Also save ${fmt.num(p.total)} as the target for the starting place`}</span>
        </label>
      ) : null}
      <div className="tg-step__foot">
        <Button tone="ghost" onClick={onDiscard}>
          Discard
        </Button>
        {p.rows.length ? (
          <WriteOnly>
            <Button tone="primary" icon="check" busy={busy} onClick={() => void apply()}>
              Save these targets
            </Button>
          </WriteOnly>
        ) : null}
      </div>
    </div>
  );
}
