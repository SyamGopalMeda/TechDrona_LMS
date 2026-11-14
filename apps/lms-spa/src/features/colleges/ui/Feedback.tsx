/**
 * Page furniture and states (components.js emptyState / listEmpty / errorCard / skeleton / spinner / section /
 * kv / pageHeader): use these for every loading, empty and error state so the screens read the same.
 *
 *   if (error) return <ErrorCard error={error} retry={reload} title="Colleges could not load" />;
 *   if (loading) return <Skeleton lines={4} />;
 *   <PageHeader title="Colleges" sub="…" actions={<Button tone="primary">Add</Button>} scope />
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { isPortalApiError } from "../lib/api";
import { useScopeLabel, useDistrictScope } from "../lib/scope";
import { Button } from "./Button";
import { cx, usePortalUi } from "./context";
import { Icon, type IconName } from "./Icon";
import { LinkTabs, type LinkTab } from "./Tabs";

export interface EmptyAction {
  label: string;
  icon?: IconName | null;
  tone?: "primary" | "secondary" | "ghost" | "danger";
  onClick: () => void;
}

export function EmptyState({
  title = "Nothing here yet",
  text,
  icon = "sparkle",
  tone,
  actions,
}: {
  title?: ReactNode;
  text?: ReactNode;
  icon?: IconName;
  tone?: string;
  /** buttons (objects) or any nodes */
  actions?: (EmptyAction | ReactNode)[];
}) {
  const acts = (actions ?? []).filter(Boolean).map((a, i) =>
    a && typeof a === "object" && "label" in (a as object) && "onClick" in (a as object) ? (
      <Button key={i} tone={(a as EmptyAction).tone ?? "primary"} icon={(a as EmptyAction).icon === undefined ? "plus" : ((a as EmptyAction).icon ?? undefined)} onClick={(a as EmptyAction).onClick}>
        {(a as EmptyAction).label}
      </Button>
    ) : (
      <span key={i}>{a as ReactNode}</span>
    ),
  );
  return (
    <div className={cx("td-empty", tone && `td-empty--${tone}`)}>
      <div className="td-empty__icon">
        <Icon name={icon} size={22} />
      </div>
      <div className="td-empty__title">{title}</div>
      {text ? <p className="td-empty__text">{text}</p> : null}
      {acts.length ? <div className="td-empty__action">{acts}</div> : null}
    </div>
  );
}

/** true when any filter / search value is set (ignores false, '', null, [] and the listed keys). */
export function hasFilters(values: Record<string, unknown> = {}, ignore: string[] = []): boolean {
  return Object.entries(values).some(([k, v]) => !ignore.includes(k) && !(v === null || v === undefined || v === "" || v === false || (Array.isArray(v) && !v.length)));
}

/**
 * THE empty-list wording rule:
 *   filtered=false → "No <noun> yet" + "Add the first …" (+ add button, writers only)
 *   filtered=true  → "Nobody matches these filters" (people) / "No <noun> match these filters" + "Clear filters"
 */
export function ListEmpty({
  filtered = false,
  noun = "records",
  people,
  addLabel,
  onAdd,
  onClear,
  text,
  icon,
  first,
}: {
  filtered?: boolean;
  noun?: string;
  people?: boolean;
  addLabel?: string;
  onAdd?: () => void;
  onClear?: () => void;
  text?: ReactNode;
  icon?: IconName;
  first?: string;
}) {
  const { canWrite } = usePortalUi();
  const isPeople = people ?? /people|person|team|lead|ambassador/i.test(noun);
  if (filtered) {
    return (
      <EmptyState
        icon={icon ?? "filter"}
        title={isPeople ? "Nobody matches these filters" : `No ${noun} match these filters`}
        text={text ?? "Try a different search, or clear the filters to see everything."}
        actions={onClear ? [{ label: "Clear filters", icon: "close", tone: "secondary", onClick: onClear }] : []}
      />
    );
  }
  const add = onAdd && addLabel && canWrite ? [{ label: addLabel, icon: "plus" as const, tone: "primary" as const, onClick: onAdd }] : [];
  return (
    <EmptyState
      icon={icon ?? "sparkle"}
      title={`No ${noun} yet`}
      text={text ?? (first ? `Add the first ${first}.` : addLabel ? `${addLabel.replace(/^Add (an? |the )?/i, "Add the first ")}.` : "")}
      actions={add}
    />
  );
}

/** Friendly failure panel; offline (status 0) and "admins only" get their own wording. */
export function ErrorCard({ title = "Something went wrong", text, error, retry }: { title?: ReactNode; text?: ReactNode; error?: unknown; retry?: () => void }) {
  const offline = isPortalApiError(error) && error.status === 0;
  const message = error instanceof Error ? error.message : null;
  return (
    <div className="td-error td-card" role="alert">
      <div className="td-error__icon">
        <Icon name={offline ? "offline" : "warn"} size={22} />
      </div>
      <div className="td-error__main">
        <div className="td-error__title">{offline ? "Server unreachable" : title}</div>
        <p className="td-muted">
          {text ?? (offline ? "The portal server is not responding. Check your connection, then try again." : "This part of the portal could not be shown right now. Other sections still work.")}
        </p>
        {message ? (
          <details className="td-error__details">
            <summary>Technical details</summary>
            <code>{message}</code>
          </details>
        ) : null}
        {retry ? (
          <div className="td-error__actions">
            <Button icon="refresh" onClick={retry}>
              Try again
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Loading placeholder (lines of shimmer, in a card by default). */
export function Skeleton({ lines = 3, card = true }: { lines?: number; card?: boolean }) {
  return (
    <div className={cx("td-skeleton", card && "td-card")} aria-busy="true" aria-label="Loading">
      <div className="td-skel td-skel--title" />
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="td-skel" style={{ width: `${92 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  );
}

/** Page-level skeleton (title, three cards, a list) — the shell's loading state. */
export function ViewSkeleton() {
  return (
    <div className="td-viewskel" aria-hidden="true">
      <div className="td-skel td-skel--title" style={{ width: "45%", height: 28 }} />
      <div className="td-viewskel__row">
        {[0, 1, 2].map((i) => (
          <div key={i} className="td-viewskel__card">
            <div className="td-skel" style={{ width: "50%" }} />
            <div className="td-skel" style={{ width: "70%", height: 22 }} />
          </div>
        ))}
      </div>
      <Skeleton lines={4} />
    </div>
  );
}

export function Spinner({ label = "Loading…", size = "md" }: { label?: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={cx("td-spinner", `td-spinner--${size}`)} role="status">
      <span className="td-spinner__ring" aria-hidden="true" />
      <span className="td-spinner__label">{label}</span>
    </span>
  );
}

/** Card with a title row and actions. */
export function Section({ title, sub, actions, children }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <section className="td-section td-card">
      {title || actions ? (
        <header className="td-section__head">
          <div>
            {title ? <h2 className="td-section__title">{title}</h2> : null}
            {sub ? <div className="td-section__sub">{sub}</div> : null}
          </div>
          {actions ? <div className="td-section__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="td-section__body">{children}</div>
    </section>
  );
}

/** Definition list; empty values show "—". */
export function Kv({ pairs }: { pairs: ([ReactNode, ReactNode] | null | false | undefined)[] }) {
  return (
    <dl className="td-kv">
      {pairs.filter((p): p is [ReactNode, ReactNode] => !!p).map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v === null || v === undefined || v === "" ? <span className="td-muted">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Scope pill ("Districts: Guntur · Krishna ▾"): opens the global district picker. */
export function ScopePill({ onOpen }: { onOpen?: () => void }) {
  const scope = useDistrictScope();
  const label = useScopeLabel(3);
  const full = useScopeLabel();
  return (
    <button
      type="button"
      className={cx("td-scopepill", !scope.isDefault && "is-custom")}
      aria-label={`Showing ${full}. Change districts`}
      onClick={() => (onOpen ? onOpen() : window.dispatchEvent(new CustomEvent("td:open-scope")))}
    >
      <Icon name="map" size={14} />
      <span className="td-scopepill__k">Districts:</span>
      <span className="td-scopepill__v">{label}</span>
      <Icon name="chevron-down" size={14} />
    </button>
  );
}

/** One consistent page title block: h1 + supporting line + actions; optional scope pill, meta row and link tabs. */
export function PageHeader({
  title,
  sub,
  eyebrow,
  actions,
  back,
  scope,
  meta,
  tabs,
}: {
  title: ReactNode;
  sub?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label?: string };
  /** show the district scope pill */
  scope?: boolean;
  meta?: ReactNode;
  tabs?: LinkTab[];
}) {
  return (
    <header className={cx("td-page-head", tabs?.length && "td-page-head--tabs")}>
      <div className="td-page-head__row">
        <div className="td-page-head__main">
          {back ? (
            <Link className="td-page-head__back" to={back.to}>
              <Icon name="chevron-left" size={16} />
              <span>{back.label ?? "Back"}</span>
            </Link>
          ) : null}
          {eyebrow ? <div className="td-page-head__eyebrow">{eyebrow}</div> : null}
          <h1 className="td-page-head__title" tabIndex={-1}>
            {title}
          </h1>
          {sub ? <p className="td-page-head__sub">{sub}</p> : null}
          {scope || meta ? (
            <div className="td-page-head__meta">
              {scope ? <ScopePill /> : null}
              {meta}
            </div>
          ) : null}
        </div>
        {actions ? <div className="td-page-head__actions">{actions}</div> : null}
      </div>
      {tabs?.length ? <LinkTabs items={tabs} /> : null}
    </header>
  );
}
