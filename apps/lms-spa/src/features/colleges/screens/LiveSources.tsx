/**
 * /colleges/live — Official sources (port of js/views/live.js renderSources): source status table with "Check now",
 * coverage KPIs, what updates automatically, recent changes in the official data. Calls GET /api/live?refresh=1 once
 * on mount (the old shell's per-visit background re-check) and polls while the server is checking.
 */
import "@/features/colleges/styles/views/live.css";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { fmt } from "../lib/fmt";
import { portalPath, toPortalHref } from "../lib/routes";
import { usePortalPage } from "../shell/page-context";
import { Badge, Button, DataTable, EmptyState, ErrorCard, Icon, Kpi, KpiRow, PageHeader, Section, Skeleton, WriteOnly, buttonClass, cx, toast, usePortalUi, type Tone } from "../ui";
import { Callout, ExtLink, UnavailableNote, When, useTick } from "./live/parts";
import { RESEARCH_LABEL, fetchLive, forceRefresh, liveSummary, refreshOnMount, useLiveStatus, type LiveData, type LiveSource } from "./live/store";

const STATUS_ORDER: Record<string, number> = { error: 0, never: 1, running: 2, ok: 3 };
const AUTO_ORDER: Record<string, number> = { automatic: 0, partial: 1, manual: 2 };
const AUTO: Record<string, [string, Tone]> = { automatic: ["Automatic", "good"], partial: ["Partly automatic", "warn"], manual: ["Manual (research)", "neutral"] };

function SourcePill({ s }: { s: LiveSource }) {
  if (s.last_status === "running") return <Badge tone="info">Checking now…</Badge>;
  if (s.last_status === "error") return s.last_success_at ? <Badge tone="warn">Unreachable — showing last copy</Badge> : <Badge tone="bad">Unreachable — no copy yet</Badge>;
  if (s.last_status === "never" || !s.last_success_at) return <Badge tone="neutral">Not checked yet</Badge>;
  return s.fresh ? <Badge tone="good">Up to date</Badge> : <Badge tone="neutral">Due for a re-check</Badge>;
}

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

function RecentChanges({ d, sources }: { d: LiveData; sources: LiveSource[] }) {
  const [limit, setLimit] = useState(10);
  const changes = Array.isArray(d.recent_changes) ? d.recent_changes : [];
  const srcName = new Map(sources.map((x) => [x.id, x.name || x.id]));
  return (
    <Section title="Recent changes in official data" sub="Newest first. A change is recorded when a source’s content differs from the previous check.">
      {changes.length ? (
        <ul className="lv-changes">
          {changes.slice(0, limit).map((c, i) => (
            <li key={`${c.at}-${i}`} className="lv-change">
              <div className="lv-change__meta">
                <When iso={c.at} />
                <span className="lv-muted">
                  {" · "}
                  {(c.source && srcName.get(c.source)) || c.source || "source"}
                </span>
              </div>
              <div className="lv-change__text">
                {c.college_id ? (
                  <>
                    <Link to={toPortalHref(`#/college/${c.college_id}`)} className="lv-change__college">
                      {c.college_name || c.college_id}
                    </Link>
                    {": "}
                  </>
                ) : null}
                {c.summary || ""}
              </div>
            </li>
          ))}
          {changes.length > limit ? (
            <li>
              <Button tone="ghost" size="sm" onClick={() => setLimit(changes.length)}>
                {`Show all ${changes.length}`}
              </Button>
            </li>
          ) : null}
        </ul>
      ) : (
        <EmptyState icon="clock" title="No changes seen yet" text="Changes appear here once a source differs from its previous check." />
      )}
    </Section>
  );
}

export function LiveSources() {
  usePortalPage({ crumbs: [{ label: "Official sources" }] });
  useTick(30_000);
  const live = useLiveStatus();
  const { canWrite } = usePortalUi();
  const [starting, setStarting] = useState(false);

  // once on mount: ask the server to re-check stale sources (the first visit also starts the visibility re-check)
  useEffect(() => {
    refreshOnMount();
  }, []);

  const d = live.data;
  const s = liveSummary(live);
  const busy = !!(d?.refreshing && !live.gaveUp);

  const checkAll = async () => {
    setStarting(true);
    try {
      await forceRefresh();
      toast("Checking every official source now. This page updates by itself.", "info");
    } catch (err) {
      toast(errMsg(err, "Could not start the check"), "bad");
    } finally {
      setStarting(false);
    }
  };

  const head = (
    <PageHeader
      title="Official sources"
      sub={`Each time the portal opens it re-checks the official sources the research used (AP EAPCET / ECET counselling, JNTUK, college websites). Values from here are marked live with the time they were checked; everything else is research data, labelled “${RESEARCH_LABEL}”.`}
      meta={
        s ? (
          <span className={cx("lv-sumchip", `lv-sumchip--${s.tone}`)}>
            {s.tone === "busy" ? <span className="td-livechip__spin" aria-hidden="true" /> : <span className="td-livechip__dot" aria-hidden="true" />}
            {s.text}
          </span>
        ) : null
      }
      actions={
        <>
          <WriteOnly>
            <Button tone="primary" icon="refresh" disabled={busy || starting} busy={starting} onClick={() => void checkAll()}>
              {busy ? "Checking…" : "Check sources now"}
            </Button>
          </WriteOnly>
          <Link to={portalPath.notices} className={buttonClass({ tone: "secondary" })}>
            <Icon name="list" size={18} />
            <span>Official notices</span>
          </Link>
        </>
      }
    />
  );

  let body;
  if (live.unavailable) {
    body = (
      <div className="td-card">
        <UnavailableNote what="source checks" />
      </div>
    );
  } else if (!d) {
    body = live.error ? (
      <ErrorCard title="Could not load the official source status" error={live.error} retry={() => void fetchLive({ refresh: true })} />
    ) : (
      <Skeleton lines={5} />
    );
  } else {
    const sources = Array.isArray(d.sources) ? d.sources : [];
    const cov = d.coverage ?? null;
    const of = cov?.colleges ? `of ${fmt.num(cov.colleges)} colleges` : undefined;
    const auto = Array.isArray(d.automation) ? d.automation : [];
    body = (
      <>
        {live.gaveUp && d.refreshing ? (
          <Callout tone="warn" title="Still checking after 90 seconds">
            Some sources are slow. The table shows the latest result for each source; reload the page later to see the rest.
          </Callout>
        ) : null}
        <Section
          title="Sources"
          sub="Each source is re-checked when its copy is older than its refresh interval. “Unreachable” means the last attempt failed; the last good copy is still used and is labelled with its date."
        >
          <DataTable<LiveSource>
            caption="Official sources and their status"
            rowKey={(r) => r.id}
            rows={sources}
            columns={[
              {
                key: "name",
                label: "Source",
                primary: true,
                minWidth: 210,
                render: (r) => (
                  <div className="lv-srccell">
                    <strong>{r.name || r.id}</strong>
                    {r.url ? (
                      <div className="lv-small">
                        <ExtLink url={r.url} />
                      </div>
                    ) : null}
                  </div>
                ),
              },
              {
                key: "last_status",
                label: "Status",
                minWidth: 170,
                sortValue: (r) => STATUS_ORDER[String(r.last_status)] ?? 4,
                render: (r) => (
                  <div className="lv-statcell">
                    <SourcePill s={r} />
                    {r.last_status === "error" && r.last_error ? <div className="lv-small lv-err">{String(r.last_error).slice(0, 200)}</div> : null}
                  </div>
                ),
              },
              { key: "last_attempt_at", label: "Last checked", minWidth: 150, render: (r) => <When iso={r.last_attempt_at} /> },
              { key: "last_success_at", label: "Last good copy", minWidth: 150, render: (r) => <When iso={r.last_success_at} /> },
              { key: "provides", label: "Provides", priority: 3, minWidth: 200, render: (r) => <span className="lv-small">{r.provides || "—"}</span> },
              {
                key: "item_count",
                label: "Records",
                priority: 3,
                align: "right",
                minWidth: 70,
                render: (r) => (r.item_count === null || r.item_count === undefined ? "—" : fmt.num(r.item_count)),
              },
              {
                key: "changed_at",
                label: "Content last changed",
                priority: 3,
                minWidth: 150,
                render: (r) => (r.changed_at ? <When iso={r.changed_at} /> : <span className="lv-muted">—</span>),
              },
            ]}
            rowActions={
              canWrite
                ? (r) => [
                    {
                      label: "Check now",
                      icon: "refresh",
                      writeOnly: true,
                      onClick: () => {
                        forceRefresh(r.id).then(
                          () => toast(`Checking ${r.name || r.id} now.`, "info"),
                          (err: unknown) => toast(errMsg(err, "Could not start the check"), "bad"),
                        );
                      },
                    },
                  ]
                : undefined
            }
            empty={<EmptyState title="No official sources configured" text="The server has no live sources set up." />}
          />
        </Section>
        {cov ? (
          <Section title="Coverage" sub="How many portal colleges could be linked to each official list.">
            <KpiRow>
              <Kpi label="Colleges in the portal" value={cov.colleges ?? null} icon="college" />
              <Kpi label="In B.Tech counselling (EAPCET)" value={cov.linked_eapcet ?? null} sub={of} icon="link" />
              <Kpi label="In lateral-entry counselling (ECET)" value={cov.linked_ecet ?? null} sub={of} icon="link" />
              <Kpi label="In JNTUK affiliated list" value={cov.linked_jntuk ?? null} sub={of} icon="link" />
              <Kpi
                label="Websites checked"
                value={cov.website_checked ?? null}
                sub={cov.website_ok !== null && cov.website_ok !== undefined ? `${fmt.num(cov.website_ok)} answered` : undefined}
                icon="external"
              />
            </KpiRow>
          </Section>
        ) : null}
        {auto.length ? (
          <Section
            title="What updates automatically"
            sub="Automatic = refreshed from an official source with no one involved. Partly = some colleges or fields only. Manual = still from the November 2026 research and edits by the team."
          >
            <DataTable
              caption="Automation by topic"
              rowKey={(r) => r.topic}
              rows={auto}
              columns={[
                { key: "topic", label: "Topic", primary: true, minWidth: 170 },
                {
                  key: "status",
                  label: "Updates",
                  minWidth: 150,
                  sortValue: (r) => AUTO_ORDER[String(r.status)] ?? 3,
                  render: (r) => {
                    const a = AUTO[String(r.status)] ?? [r.status || "—", "neutral" as Tone];
                    return <Badge tone={a[1]}>{a[0]}</Badge>;
                  },
                },
                { key: "source", label: "Source", minWidth: 150, render: (r) => <span className="lv-small">{r.source || "—"}</span> },
                { key: "how", label: "How", priority: 3, minWidth: 200, render: (r) => <span className="lv-small">{r.how || "—"}</span> },
                { key: "note", label: "Note", priority: 3, minWidth: 200, render: (r) => <span className="lv-small lv-muted">{r.note || "—"}</span> },
              ]}
            />
          </Section>
        ) : null}
        <RecentChanges d={d} sources={sources} />
      </>
    );
  }

  return (
    <div className="v-live v-live-sources">
      {head}
      {body}
    </div>
  );
}
