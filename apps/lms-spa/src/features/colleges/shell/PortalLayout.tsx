/**
 * The Outreach Portal shell: a full-screen layout of its own (not the LMS admin shell), the same DOM and class
 * names as the old app.js, under a `.tdp` root that scopes the portal CSS (styles/*.css) and its tokens.
 *
 * Owns: theme + device attributes, top bar (brand, district scope, global search, Modules, theme, account),
 * collapsible sidebar, phone tab bar + More sheet, banners (offline / scope rejected / view-only / demo data),
 * breadcrumb + section tabs, the overlay root (modals, menus, toasts), /meta + /program loading (district
 * names and target groups for the scope), `?d=` scope sync, legacy `#/…` links, and scroll-to-top per page.
 * Screens render as `children` (inside the route segment's error boundary + Suspense skeleton).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/components.css";
import "../styles/shell.css";
import { configurePortalApi, portalApi } from "../lib/api";
import { invalidatePortalCache, usePortalQuery } from "../lib/cache";
import { districtName as scopeDistrictName, parseScopeQuery, resetDistrictScope, scopeQueryValue, setDistrictScope, setScopeContext, subscribeScope } from "../lib/scope";
import { prettySlug } from "../lib/fmt";
import { readNavCollapsed, toggleTheme, useDevice, useTheme, useThemeColorMeta, writeNavCollapsed } from "../lib/prefs";
import { PORTAL_BASE, matchPortalRoute, portalPath, toPortalHref } from "../lib/routes";
import { usePortalSession, ROLE_LABEL } from "../lib/session";
import type { PortalMeta, Program } from "../lib/types";
import { Button } from "../ui/Button";
import { PortalUiProvider, cx } from "../ui/context";
import { Menu } from "../ui/Menu";
import { OverlayHost, toast } from "../ui/Overlay";
import { AccountDialog, Banners, Brand, Crumbs, MoreSheet, SectionTabs, Sidebar, TabBar, UserButton } from "./Chrome";
import { GlobalSearch, type GlobalSearchHandle } from "./GlobalSearch";
import { useModuleLinks } from "./modules";
import { PageMetaProvider, type Crumb, type PageMeta } from "./page-context";
import { ScopeControl, scopeDistricts } from "./ScopePicker";

const ROOT_CRUMB: Crumb = { label: "Home", to: PORTAL_BASE };
const APP_TITLE = "Tech Drona Outreach Portal";

export function PortalLayout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const theme = useTheme();
  const device = useDevice();
  useThemeColorMeta(theme);
  const { user, role, canWrite } = usePortalSession();
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 5 * 60_000 }).data;
  const program = usePortalQuery<Program>("program", { ttl: 5 * 60_000 }).data;
  const modules = useModuleLinks();

  const [overlayRoot, setOverlayRoot] = useState<HTMLElement | null>(null);
  const [collapsed, setCollapsed] = useState(readNavCollapsed);
  const [navOpen, setNavOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [acctOpen, setAcctOpen] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [offline, setOffline] = useState(false);
  const [scopeRejected, setScopeRejected] = useState<string | null>(null);
  const [pageMeta, setPageMeta] = useState<PageMeta | null>(null);
  const [width, setWidth] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1280));
  const search = useRef<GlobalSearchHandle>(null);
  const panel = useRef<HTMLElement>(null);

  const match = matchPortalRoute(location.pathname);
  const route = match?.route ?? null;
  const params = match?.params ?? {};
  const compactSearch = device.form === "phone" || width < 900;
  const desktop = device.form === "desktop";

  /* ---- API hooks: offline banner, rejected district scope ---- */
  useEffect(
    () =>
      configurePortalApi({
        onNetwork: (ok) => setOffline(!ok),
        onScopeRejected: (err) => setScopeRejected(err.message),
      }),
    [],
  );
  useEffect(() => subscribeScope(() => setScopeRejected(null)), []);
  useEffect(() => {
    const on = () => setWidth(window.innerWidth);
    const off = () => setOffline(true);
    const back = () => invalidatePortalCache();
    window.addEventListener("resize", on);
    window.addEventListener("offline", off);
    window.addEventListener("online", back);
    return () => {
      window.removeEventListener("resize", on);
      window.removeEventListener("offline", off);
      window.removeEventListener("online", back);
    };
  }, []);

  /* ---- scope context (district names + target groups) ---- */
  useEffect(() => {
    if (meta || program) setScopeContext({ program: program ?? undefined, districts: meta?.districts ?? [] });
  }, [meta, program]);

  /* ---- legacy hash links (/colleges#/college/c9) → real paths ---- */
  useEffect(() => {
    if (location.hash.startsWith("#/")) void navigate(toPortalHref(location.hash), { replace: true });
  }, [location.hash, navigate]);

  /* ---- `?d=` scope in the URL: applied on arrival, kept in step when present ---- */
  const districts = useMemo(() => scopeDistricts(program, meta), [program, meta]);
  const d = new URLSearchParams(location.search).get("d");
  useEffect(() => {
    if (!d) return;
    const next = parseScopeQuery(d, new Set(districts.map((x) => x.id)));
    if (next) setDistrictScope(next);
  }, [d, districts]);
  const locRef = useRef(location);
  locRef.current = location;
  useEffect(
    () =>
      subscribeScope(() => {
        const loc = locRef.current;
        const q = new URLSearchParams(loc.search);
        if (!q.has("d") || q.get("d") === scopeQueryValue()) return;
        q.set("d", scopeQueryValue());
        void navigate({ pathname: loc.pathname, search: `?${q.toString().replace(/%2C/gi, ",")}` }, { replace: true, preventScrollReset: true });
      }),
    [navigate],
  );
  // "td:open-scope" (ScopePill in pages) opens the picker
  useEffect(() => {
    const open = () => setScopeOpen(true);
    window.addEventListener("td:open-scope", open);
    return () => window.removeEventListener("td:open-scope", open);
  }, []);

  /* ---- per-page: close chrome, scroll to top, focus ---- */
  useEffect(() => {
    setNavOpen(false);
    setMoreOpen(false);
    setSearchOpen(false);
    setScopeOpen(false);
    const sc = panel.current;
    if (sc && getComputedStyle(sc).overflowY === "auto") sc.scrollTop = 0;
    else window.scrollTo(0, 0);
  }, [location.pathname]);

  /* ---- "/" focuses search; Esc closes the nav overlay ---- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && navOpen) setNavOpen(false);
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (overlayRoot?.querySelector(".td-overlay")) return;
      e.preventDefault();
      if (compactSearch) setSearchOpen(true);
      search.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navOpen, compactSearch, overlayRoot]);
  useEffect(() => {
    if (searchOpen) setTimeout(() => search.current?.focus(), 30);
  }, [searchOpen]);

  /* ---- breadcrumb + title ---- */
  const defaultCrumbs = (): Crumb[] => {
    if (!route || route.pattern === PORTAL_BASE) return [ROOT_CRUMB];
    if (params.district && !params.city) return [ROOT_CRUMB, { label: scopeDistrictName(params.district) }];
    if (params.district && params.city) {
      const city = meta?.cities?.find((c) => c.id === params.city)?.name ?? prettySlug(String(params.city).split("--").pop());
      return [ROOT_CRUMB, { label: scopeDistrictName(params.district), to: portalPath.district(params.district) }, { label: city }];
    }
    return [ROOT_CRUMB, { label: route.title }];
  };
  const crumbs = pageMeta?.crumbs?.length ? (pageMeta.crumbs[0]?.to === PORTAL_BASE || /^home$/i.test(pageMeta.crumbs[0]?.label ?? "") ? pageMeta.crumbs : [ROOT_CRUMB, ...pageMeta.crumbs]) : defaultCrumbs();
  const here = pageMeta?.title ?? (crumbs.length > 1 ? crumbs[crumbs.length - 1]!.label : (route?.title ?? "Page not found"));
  const deep = !!(params.id || params.district);
  useEffect(() => {
    document.title = `${here} · ${APP_TITLE}`;
  });

  const toggleNav = () => {
    if (desktop) {
      const c = !collapsed;
      setCollapsed(c);
      writeNavCollapsed(c);
    } else setNavOpen((o) => !o);
  };
  const retry = useCallback(async () => {
    try {
      await portalApi.get("meta");
      setOffline(false);
      toast("Connected again", "good");
      invalidatePortalCache();
    } catch {
      toast("Still can’t reach the server. Try again in a moment.", "warn");
    }
  }, []);

  const who = user ? `${user}${role ? ` · ${ROLE_LABEL[role] ?? role}` : ""}` : "Your account";
  const ui = useMemo(() => ({ overlayRoot, form: device.form, coarse: device.coarse, canWrite }), [overlayRoot, device.form, device.coarse, canWrite]);
  const banners = { offline, scopeRejected, viewer: role === "viewer", demo: !!meta?.demo };
  const hasBanner = Object.values(banners).some(Boolean);

  return (
    <div
      className={cx("tdp", !canWrite && "td-readonly")}
      data-tdp-theme={theme}
      data-form={device.form}
      data-pointer={device.coarse ? "coarse" : "fine"}
      data-short={device.short ? "1" : undefined}
    >
      <PortalUiProvider value={ui}>
        <PageMetaProvider set={setPageMeta}>
          <div
            className={cx("td-app", collapsed && desktop && "nav-collapsed", navOpen && "nav-open", compactSearch && "search-compact", searchOpen && "search-open", hasBanner && "has-banner")}
            data-layout="full"
            data-route={route?.nav ?? "notfound"}
          >
            <header className="td-topbar">
              <Button icon="menu" tone="ghost" ariaLabel="Toggle navigation" className="td-topbar__menu" aria-expanded={navOpen} onClick={toggleNav} />
              <Brand to={PORTAL_BASE} />
              <span className="td-topbar__title" aria-hidden="true">
                {route ? here : ""}
              </span>
              <ScopeControl districts={districts} open={scopeOpen} onOpenChange={setScopeOpen} />
              <GlobalSearch ref={search} showClose={compactSearch} onClose={() => setSearchOpen(false)} />
              <div className="td-topbar__actions">
                {modules.length ? (
                  <Menu
                    label="Modules"
                    icon={null}
                    tone="secondary"
                    size="sm"
                    ariaLabel="Switch module"
                    className="td-topbar__modules"
                    onNavigate={(href) => void navigate(href)}
                    items={modules.map((m) => ({ label: m.label, icon: m.current ? "check" : m.key === "all" ? "home" : m.reload ? "external" : null, current: m.current, href: m.current ? undefined : m.href, reload: m.reload }))}
                  />
                ) : null}
                <Button icon="search" tone="ghost" ariaLabel="Search" className="td-topbar__searchbtn" onClick={() => setSearchOpen(true)} />
                <Button
                  icon={theme === "dark" ? "sun" : "moon"}
                  tone="ghost"
                  ariaLabel={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
                  title={theme === "dark" ? "Light theme" : "Dark theme"}
                  onClick={toggleTheme}
                />
                <UserButton user={user} role={role} onClick={() => setAcctOpen(true)} />
              </div>
            </header>
            <Banners
              state={banners}
              onRetry={retry}
              onResetScope={() => {
                setScopeRejected(null);
                resetDistrictScope();
              }}
            />
            <div className="td-body">
              <Sidebar activeNav={route?.nav ?? null} collapsed={collapsed && desktop} onToggleCollapse={toggleNav} onNavigate={() => setNavOpen(false)} />
              <div className="td-nav-scrim" onClick={() => setNavOpen(false)} />
              <main className="td-main" id="main" tabIndex={-1}>
                <div className="td-stage">
                  <section className="td-panel" aria-label="Page content" ref={panel}>
                    <div className="td-panel__head">
                      <div className="td-panel__crumbrow">
                        <Crumbs items={crumbs} deep={deep} />
                      </div>
                      <SectionTabs section={route?.section} />
                    </div>
                    <div id="td-view" className="td-view" tabIndex={-1}>
                      {children}
                    </div>
                  </section>
                </div>
              </main>
            </div>
            <TabBar activeNav={route?.nav ?? null} moreOpen={moreOpen} onMore={() => setMoreOpen(true)} />
          </div>
          <MoreSheet
            open={moreOpen}
            onClose={() => setMoreOpen(false)}
            activeNav={route?.nav ?? null}
            modules={modules}
            who={who}
            theme={theme}
            onToggleTheme={toggleTheme}
            onAccount={() => setAcctOpen(true)}
          />
          <AccountDialog open={acctOpen} onClose={() => setAcctOpen(false)} user={user} role={role} />
          <OverlayHost />
        </PageMetaProvider>
      </PortalUiProvider>
      <div ref={setOverlayRoot} className="td-overlays" />
    </div>
  );
}

