/**
 * Presentational pieces of the portal shell (same DOM + class names as app.js buildShell, so styles/shell.css
 * applies unchanged): brand, sidebar, phone tab bar, More sheet, breadcrumb, section tabs, banners, account dialog.
 */
import { Link, useLocation, useNavigate } from "react-router";
import { initials } from "../lib/fmt";
import { NAV, PRIMARY, SECONDARY, SECTIONS, TAB_COUNT, type NavItem } from "../lib/routes";
import { ROLE_LABEL } from "../lib/session";
import type { Theme } from "../lib/prefs";
import { Button } from "../ui/Button";
import { cx } from "../ui/context";
import { Icon } from "../ui/Icon";
import { Drawer, Modal } from "../ui/Overlay";
import { LinkTabs } from "../ui/Tabs";
import markNavy from "./brand/mark-navy.svg";
import markWhite from "./brand/mark-white.svg";
import wordNavy from "./brand/wordmark-navy.svg";
import wordWhite from "./brand/wordmark-white.svg";
import type { Crumb } from "./page-context";
import type { ModuleLink } from "./modules";

const LOGOS = { mark: [markNavy, markWhite], wordmark: [wordNavy, wordWhite] } as const;

/** Official logo as a theme-aware pair (navy on light, white on dark; CSS picks via --td-logo-*). */
export function BrandLogo({ kind, className, width, height }: { kind: keyof typeof LOGOS; className?: string; width: number; height: number }) {
  const [navy, white] = LOGOS[kind];
  return (
    <span className={cx("td-logo", className)}>
      <img className="td-logo-navy" src={navy} alt="" width={width} height={height} decoding="async" />
      <img className="td-logo-white" src={white} alt="" width={width} height={height} decoding="async" />
    </span>
  );
}

export function Brand({ to }: { to: string }) {
  return (
    <Link to={to} className="td-brand" aria-label="Tech Drona Outreach Portal — home">
      <BrandLogo kind="mark" className="td-brand__mark" width={36} height={36} />
      <span className="td-brand__text">
        <BrandLogo kind="wordmark" className="td-brand__word" width={118} height={15} />
        <span className="td-brand__sub">Outreach Portal</span>
      </span>
    </Link>
  );
}

function NavLink({ n, active, onNavigate }: { n: NavItem; active: boolean; onNavigate?: () => void }) {
  return (
    <Link to={n.href} className={cx("td-nav__link", active && "is-active")} data-nav={n.id} title={n.tip ?? n.label} aria-label={n.label} aria-current={active ? "page" : undefined} onClick={onNavigate}>
      <Icon name={n.icon} size={20} />
      <span className="td-nav__label">{n.label}</span>
    </Link>
  );
}

export function Sidebar({ activeNav, collapsed, onToggleCollapse, onNavigate }: { activeNav: string | null; collapsed: boolean; onToggleCollapse: () => void; onNavigate: () => void }) {
  return (
    <nav className="td-nav" aria-label="Main">
      <div className="td-nav__group">
        {PRIMARY.map((n) => (
          <NavLink key={n.id} n={n} active={n.id === activeNav} onNavigate={onNavigate} />
        ))}
      </div>
      <div className="td-nav__group">
        <div className="td-nav__heading">More</div>
        {SECONDARY.map((n) => (
          <NavLink key={n.id} n={n} active={n.id === activeNav} onNavigate={onNavigate} />
        ))}
      </div>
      <div className="td-nav__foot">
        <button type="button" className="td-nav__collapse" onClick={onToggleCollapse} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
          <Icon name="chevron-left" size={18} />
          <span className="td-nav__label">Collapse</span>
        </button>
      </div>
    </nav>
  );
}

export function TabBar({ activeNav, onMore, moreOpen }: { activeNav: string | null; onMore: () => void; moreOpen: boolean }) {
  const onTab = PRIMARY.slice(0, TAB_COUNT).some((n) => n.id === activeNav);
  const inMore = !!activeNav && !onTab;
  return (
    <nav className="td-tabbar" aria-label="Main">
      {PRIMARY.slice(0, TAB_COUNT).map((n) => (
        <Link key={n.id} to={n.href} className={cx("td-tabbar__item", n.id === activeNav && "is-active")} data-nav={n.id} aria-label={n.label} aria-current={n.id === activeNav ? "page" : undefined}>
          <Icon name={n.icon} size={22} />
          <span>{n.short ?? n.label}</span>
        </Link>
      ))}
      <button type="button" className={cx("td-tabbar__item", inMore && "is-active")} onClick={onMore} data-nav="more" aria-haspopup="dialog" aria-expanded={moreOpen} aria-current={inMore ? "page" : undefined}>
        <Icon name="more" size={22} />
        <span>More</span>
      </button>
    </nav>
  );
}

/** Phone "More" sheet: Switch module (inside the LMS), the rest of the nav, account and theme. */
export function MoreSheet({
  open,
  onClose,
  activeNav,
  modules,
  who,
  theme,
  onToggleTheme,
  onAccount,
}: {
  open: boolean;
  onClose: () => void;
  activeNav: string | null;
  modules: ModuleLink[];
  who: string;
  theme: Theme;
  onToggleTheme: () => void;
  onAccount: () => void;
}) {
  const navigate = useNavigate();
  const item = (n: NavItem) => (
    <Link key={n.id} to={n.href} className={cx("td-more__item", n.id === activeNav && "is-active")} onClick={onClose}>
      <span className="td-more__icon">
        <Icon name={n.icon} size={20} />
      </span>
      <span>{n.label}</span>
      <Icon name="chevron" size={16} />
    </Link>
  );
  return (
    <Drawer open={open} title="More" onClose={onClose}>
      <div className="td-more">
        {modules.length ? (
          <>
            <div className="td-more__label td-muted">Switch module</div>
            {modules.map((m) => (
              <button
                key={m.key}
                type="button"
                className="td-more__item"
                aria-current={m.current ? "true" : undefined}
                onClick={() => {
                  onClose();
                  if (m.current) return;
                  if (m.reload) window.location.assign(m.href);
                  else void navigate(m.href);
                }}
              >
                <span className="td-more__icon">
                  <Icon name={m.current ? "check" : m.key === "all" ? "home" : "external"} size={20} />
                </span>
                <span>{m.label}</span>
                <Icon name="chevron" size={16} />
              </button>
            ))}
            <div className="td-more__sep" />
          </>
        ) : null}
        {PRIMARY.slice(TAB_COUNT).map(item)}
        <div className="td-more__sep" />
        {SECONDARY.map(item)}
        <div className="td-more__sep" />
        <button
          type="button"
          className="td-more__item"
          onClick={() => {
            onClose();
            onAccount();
          }}
        >
          <span className="td-more__icon">
            <Icon name="user" size={20} />
          </span>
          <span>{who}</span>
          <Icon name="chevron" size={16} />
        </button>
        <button
          type="button"
          className="td-more__item"
          onClick={() => {
            onToggleTheme();
            onClose();
          }}
        >
          <span className="td-more__icon">
            <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
          </span>
          <span>{theme === "dark" ? "Light theme" : "Dark theme"}</span>
          <Icon name="chevron" size={16} />
        </button>
      </div>
    </Drawer>
  );
}

/** Breadcrumb trail; on phones a single "‹ parent" link below the top-level pages. */
export function Crumbs({ items, deep }: { items: Crumb[]; deep: boolean }) {
  const parent = [...items.slice(0, -1)].reverse().find((it) => it.to);
  return (
    <nav className={cx("td-crumbs", items.length < 2 && "is-single")} aria-label="Breadcrumb">
      {parent && deep ? (
        <Link to={parent.to!} className="td-crumbs__up">
          <Icon name="chevron-left" size={18} />
          <span>{parent.label}</span>
        </Link>
      ) : null}
      <ol>
        {items.map((it, i) => {
          const last = i === items.length - 1;
          return (
            <li key={`${it.label}-${i}`}>
              {i > 0 ? <Icon name="chevron" size={14} className="td-crumbs__sep" /> : null}
              {!last && it.to ? <Link to={it.to}>{it.label}</Link> : <span aria-current={last ? "page" : undefined}>{it.label}</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Shell-level sub-section tabs (Targets › Performance | Targets by place | Planner; Calls › Call queue | Follow-ups). */
export function SectionTabs({ section }: { section: keyof typeof SECTIONS | undefined }) {
  const loc = useLocation();
  if (!section) return <div className="td-sectiontabs" hidden />;
  const q = new URLSearchParams(loc.search);
  const items = SECTIONS[section].map((t) => ({ label: t.label, to: t.href, active: t.is ? t.is(loc.pathname, q) : loc.pathname === t.href.split("?")[0] }));
  return (
    <div className="td-sectiontabs">
      <LinkTabs items={items} />
    </div>
  );
}

export interface BannerState {
  offline: boolean;
  scopeRejected: string | null;
  viewer: boolean;
  demo: boolean;
}

export function Banners({ state, onRetry, onResetScope }: { state: BannerState; onRetry: () => void; onResetScope: () => void }) {
  return (
    <div className="td-banners">
      {state.offline ? (
        <div className="td-banner td-banner--offline" role="alert">
          <Icon name="offline" size={18} />
          <span>
            <span className="td-banner__full">
              <strong>Can’t reach the server. </strong>
              You may be offline or the portal server is not running. What you see may be out of date, and changes won’t save until the connection is back.
            </span>
            <span className="td-banner__short">
              <strong>Offline</strong> — changes won’t save until you’re back online.
            </span>
          </span>
          <button type="button" className="td-banner__btn" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : null}
      {state.scopeRejected ? (
        <div className="td-banner td-banner--warn" role="alert">
          <Icon name="warn" size={18} />
          <span>
            <strong>District filter not applied. </strong>
            <span className="td-banner__long">{state.scopeRejected} </span>
            Numbers on this page are not shown until the districts are chosen again.
          </span>
          <button type="button" className="td-banner__btn" onClick={onResetScope}>
            Reset districts
          </button>
        </div>
      ) : null}
      {state.viewer ? (
        <div className="td-banner td-banner--info" role="status">
          <Icon name="info" size={18} />
          <span>
            <strong>View-only access. </strong>
            <span className="td-banner__long">You can browse everything; editing needs edit access.</span>
          </span>
        </div>
      ) : null}
      {state.demo ? (
        <div className="td-banner td-banner--demo" role="status">
          <Icon name="warn" size={18} />
          <span>
            <strong>Demo data present. </strong>
            Some records are test data, not real. <span className="td-banner__long">Ask an admin to remove the demo records before these numbers are used.</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function UserButton({ user, role, onClick }: { user: string | null; role: string | null; onClick: () => void }) {
  const roleLabel = role ? (ROLE_LABEL[role] ?? role) : null;
  const title = `Signed in as ${user || "—"}${roleLabel ? ` (${roleLabel})` : ""} through Tech Drona LMS`;
  return (
    <button type="button" className="td-user" onClick={onClick} aria-label={title} title={title}>
      <span className={cx("td-user__avatar", !user && "is-empty")}>{user ? initials(user) : <Icon name="user" size={16} />}</span>
      <span className="td-user__name">{user || "Signed in"}</span>
      {roleLabel ? <span className={cx("td-user__role", role === "viewer" && "is-viewer")}>{roleLabel}</span> : null}
    </button>
  );
}

/** "Your account": who, role, signed in through the LMS, back to the LMS admin (SSO: no portal sign-out). */
export function AccountDialog({ open, onClose, user, role }: { open: boolean; onClose: () => void; user: string | null; role: string | null }) {
  return (
    <Modal open={open} title="Your account" onClose={onClose} compact>
      <div className="td-acct">
        <div className="td-acct__who">
          <span className="td-user__avatar">{initials(user)}</span>
          <div>
            <strong>{user || "—"}</strong>
            <div className="td-muted">{role ? (ROLE_LABEL[role] ?? role) : "Signed in"}</div>
          </div>
        </div>
        <p className="td-muted">Signed in through Tech Drona LMS</p>
        {role === "viewer" ? <p className="td-muted">You can look at everything but cannot make changes. Ask an LMS super admin for edit access.</p> : null}
        <div className="td-acct__actions">
          <Button icon="chevron-left" onClick={() => window.location.assign("/admin")}>
            Back to LMS admin
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export { NAV };
