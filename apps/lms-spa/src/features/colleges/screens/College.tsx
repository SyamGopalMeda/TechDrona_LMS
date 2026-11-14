/**
 * College page (/colleges/college/:id) — port of js/views/college.js (+ college-form.js, branch.js).
 * Tabs: Overview · Team · Contacts & calls · Targets & performance · Branches · Exams · Activity (`?tab=`; old ids
 * enrollment / followups / history / contacts still work). `?branch=<id>` opens the branch drawer (Back closes it).
 */
import "@/features/colleges/styles/views/college.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { isPortalApiError } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import type { Person, PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { EmptyState, LinkButton, Skeleton, Tabs } from "../ui";
import { itemsOf, usePlanIndex } from "./shared/dashboard";
import { BranchDrawer } from "./college/BranchDrawer";
import { BranchesTab } from "./college/Branches";
import { CallsTab } from "./college/Calls";
import type { CollegeCtx } from "./college/ctx";
import { ActivityTab, ExamsTab } from "./college/ExamsActivity";
import { examInfo, isActive, loadPrefs, periods as periodList, resolveTab, savePrefs, shape, TAB_ALIAS, type CollegeData, type CollegeUiPrefs, type TabId } from "./college/model";
import { CollegeHeader, OverviewTab } from "./college/Overview";
import { PerformanceTab } from "./college/Performance";
import { TeamTab } from "./college/Team";

export function CollegePage() {
  const { id = "" } = useParams();
  const [q, setQuery] = useQueryState();
  const navigate = useNavigate();
  const tab = resolveTab(q.tab);
  const branchParam = q.branch || null;

  const det = usePortalQuery<CollegeData>(id ? `colleges/${encodeURIComponent(id)}` : null);
  const metaQ = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const plistQ = usePortalQuery<Person[] | { items?: Person[] }>(id ? "people" : null, { query: { college: id } });
  const plan = usePlanIndex();

  // old tab aliases (enrollment, followups, history, contacts) → canonical, without a Back step
  useEffect(() => {
    if (q.tab && TAB_ALIAS[q.tab]) setQuery({ tab: TAB_ALIAS[q.tab] }, { history: "replace" });
  }, [q.tab, setQuery]);

  const [prefs, setPrefsState] = useState<CollegeUiPrefs>(loadPrefs);
  const setPrefs = useCallback((p: Partial<CollegeUiPrefs>) => {
    setPrefsState((old) => {
      const next = { ...old, ...p };
      savePrefs(next);
      return next;
    });
  }, []);
  const periods = useMemo(() => periodList(), []);
  const period = periods.some(([k]) => k === prefs.period) ? prefs.period : "programme";

  const pushedBranch = useRef(false);
  const showBranch = useCallback(
    (bid: number | string) => {
      if (String(q.branch ?? "") === String(bid)) return;
      pushedBranch.current = true;
      setQuery({ branch: String(bid) }, { history: "push" });
    },
    [q.branch, setQuery],
  );
  const closeBranch = useCallback(() => {
    if (pushedBranch.current) {
      pushedBranch.current = false;
      void navigate(-1);
    } else setQuery({ branch: null }, { history: "replace" });
  }, [navigate, setQuery]);
  const go = useCallback((t: TabId) => setQuery({ tab: t === "overview" ? null : t, branch: null }, { history: "push" }), [setQuery]);

  const d = det.data;
  const meta = metaQ.data ?? null;
  const plist = plistQ.error ? null : plistQ.data ? itemsOf(plistQ.data) : null;
  const c = d?.college;
  const district = c ? (meta?.districts.find((x) => x.id === c.district_id) ?? null) : null;
  const city = c ? (meta?.cities.find((x) => x.id === c.city_id) ?? null) : null;

  usePortalPage({
    title: c ? c.short_name || c.name : "College",
    crumbs: [
      { label: "Colleges", to: portalPath.colleges },
      ...(district ? [{ label: district.name, to: portalPath.district(district.id) }] : []),
      ...(city && c ? [{ label: city.name, to: portalPath.city(c.district_id, city.id) }] : []),
      { label: c ? c.short_name || c.name : "College" },
    ],
  });

  const cx: CollegeCtx | null = useMemo(() => {
    if (!d) return null;
    const s = shape(d, plist);
    return { d, s, ex: examInfo(d), meta, research: plan.get(d.college.id) ?? null, go, showBranch };
  }, [d, plist, meta, plan, go, showBranch]);

  const drawer = branchParam ? <BranchDrawer key={branchParam} branchId={branchParam} inCollege onClose={closeBranch} /> : null;

  if (!cx) {
    if (det.error) {
      const nf = isPortalApiError(det.error) && det.error.status === 404;
      return (
        <div className="v-college">
          <EmptyState
            title={nf ? "College not found" : "Could not load this college"}
            text={nf ? "This link points to a college that is not in the portal. Pick one from the list instead." : det.error instanceof Error && det.error.message ? det.error.message : "Check your connection and try again."}
            icon="warn"
            actions={[
              nf ? null : { label: "Try again", icon: "refresh", onClick: () => void det.reload() },
              <LinkButton key="all" to={portalPath.colleges} tone={nf ? "primary" : "secondary"}>
                Browse all colleges
              </LinkButton>,
            ]}
          />
        </div>
      );
    }
    return (
      <div className="v-college" aria-busy="true">
        <div className="vc-head vc-head--skel">
          <div className="vc-head-main">
            <div className="td-skel" style={{ width: "30%" }} />
            <div className="td-skel td-skel--title" style={{ width: "70%", height: 26 }} />
            <div className="td-skel" style={{ width: "45%" }} />
          </div>
        </div>
        <Skeleton lines={4} />
        {drawer}
      </div>
    );
  }

  const openFu = (cx.d.followups ?? []).filter((f) => f.status === "open").length;
  const activeN = cx.s.people.filter(isActive).length;
  const nContacts = (cx.d.contacts ?? []).length;
  return (
    <div className="v-college">
      <CollegeHeader c={cx} />
      <div className="vc-tabs">
        <Tabs
          active={tab}
          onChange={(t) => go(t as TabId)}
          tabs={[
            { id: "overview", label: "Overview", render: () => <OverviewTab c={cx} /> },
            { id: "team", label: "Team", count: activeN || undefined, render: () => <TeamTab c={cx} /> },
            { id: "calls", label: "Contacts & calls", count: nContacts || undefined, render: () => <CallsTab c={cx} /> },
            {
              id: "performance",
              label: "Targets & performance",
              render: () => <PerformanceTab c={cx} period={period} periods={periods} onPeriod={(p) => setPrefs({ period: p })} />,
            },
            { id: "branches", label: "Branches", count: cx.s.branches.length || undefined, render: () => <BranchesTab c={cx} prefs={prefs} setPrefs={setPrefs} /> },
            { id: "exams", label: "Exams", render: () => <ExamsTab c={cx} /> },
            { id: "activity", label: "Activity", count: openFu || undefined, render: () => <ActivityTab c={cx} /> },
          ]}
        />
      </div>
      {drawer}
    </div>
  );
}
