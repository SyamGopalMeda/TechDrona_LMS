/**
 * /colleges/notices — Official notices (port of js/views/live.js renderNotices): JNTUK circulars, timetables, results
 * and calendars, fetched live. Filters in the URL: ?category=&q=. GET /api/live/announcements.
 */
import "@/features/colleges/styles/views/live.css";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { debounce, fmt } from "../lib/fmt";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { usePortalPage } from "../shell/page-context";
import { DataTable, EmptyState, Icon, PageHeader, Segmented, buttonClass } from "../ui";
import { useReloadOnLiveFinish } from "./live/ExamNoticesCard";
import { CatBadge, NoticeMain, NoticeStatus, UnavailableNote, dateOnly, isUnavailable, type Notice, type NoticesAnswer } from "./live/parts";
import { startLive } from "./live/store";

export function Notices() {
  usePortalPage({ crumbs: [{ label: "Official notices" }] });
  const [query, setQuery] = useQueryState();
  const category = query.category ?? "";
  const q = (query.q ?? "").trim();
  const [text, setText] = useState(query.q ?? "");
  useEffect(() => setText(query.q ?? ""), [query.q]);
  const push = useMemo(() => debounce((v: string) => setQuery({ q: v.trim() || null }, { history: "replace" }), 250), [setQuery]);
  useEffect(() => () => push.cancel(), [push]);
  useEffect(() => startLive(), []);

  const { data, error, loading, reload } = usePortalQuery<NoticesAnswer>("live/announcements", {
    query: { category: category || undefined, q: q || undefined, limit: 200 },
    keepPrevious: true,
  });
  useReloadOnLiveFinish(reload);

  const unavailable = !!error && isUnavailable(error);
  const cats = Array.isArray(data?.categories) ? data.categories : [];
  const items = Array.isArray(data?.items) ? data.items : [];
  const total = cats.reduce((n, c) => n + (Number(c.count) || 0), 0);
  const src = data?.source ?? {};
  const empty =
    !items.length && !src.last_success_at ? (
      <EmptyState icon="clock" title="Notices have not been fetched yet" text="The JNTUK notifications page has not been read successfully yet. Check the official sources page." />
    ) : q || category ? (
      <EmptyState icon="filter" title="No notices match" text="Try another type or clear the search." />
    ) : (
      <EmptyState title="No notices found" />
    );

  return (
    <div className="v-live v-live-notices">
      <PageHeader
        title="Official notices"
        sub="Circulars, exam timetables, results and calendars from the JNTUK notifications page, fetched live. Attachments open on the official site in a new tab."
        actions={
          <Link to={portalPath.live} className={buttonClass({ tone: "secondary" })}>
            <Icon name="data" size={18} />
            <span>Official sources</span>
          </Link>
        }
      />
      {unavailable ? (
        <div className="td-card">
          <UnavailableNote what="notices" />
        </div>
      ) : (
        <>
          <div className="lv-notice-meta" aria-live="polite">
            {data ? <NoticeStatus r={data} /> : null}
          </div>
          <div className="lv-toolbar">
            <div className="lv-seghost">
              {data ? (
                <Segmented
                  ariaLabel="Notice type"
                  value={category}
                  options={[{ value: "", label: "All", count: total || undefined }, ...cats.map((c) => ({ value: c.id, label: c.label || c.id, count: c.count ?? undefined }))]}
                  onChange={(v) => setQuery({ category: v || null }, { history: "auto" })}
                />
              ) : null}
            </div>
            <div className="lv-toolbar__row">
              <input
                type="search"
                className="td-input lv-search"
                placeholder="Search notices…"
                aria-label="Search notices"
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  push(e.target.value);
                }}
              />
              <span className="lv-muted lv-small" aria-live="polite">
                {data ? `${fmt.num(items.length)} ${items.length === 1 ? "notice" : "notices"}${q ? ` matching “${q}”` : ""}` : ""}
              </span>
            </div>
          </div>
          <div className="lv-notices">
            <DataTable<Notice>
              caption="Official notices"
              rowKey={(r) => String(r.uid ?? `${r.date}-${r.title}`)}
              pageSize={25}
              pageLabel="notices"
              cardSort={false}
              loading={loading}
              error={error}
              onRetry={() => void reload()}
              rows={items}
              columns={[
                { key: "date", label: "Date", minWidth: 110, cardHidden: true, render: (r) => <span className="lv-nowrap">{dateOnly(r.date)}</span> },
                { key: "title", label: "Notice", primary: true, minWidth: 280, render: (r) => <NoticeMain r={r} /> },
                { key: "category", label: "Type", minWidth: 120, cardHidden: true, render: (r) => <CatBadge id={r.category} cats={cats} /> },
                { key: "dept", label: "Department", priority: 3, minWidth: 140, cardHidden: true, render: (r) => <span className="lv-small">{r.dept || r.section || "—"}</span> },
              ]}
              cardTitle={(r) => <NoticeMain r={r} />}
              cardSubtitle={(r) => <span className="lv-small lv-muted">{[dateOnly(r.date), r.dept || r.section].filter(Boolean).join(" · ")}</span>}
              cardMeta={(r) => [<CatBadge key="c" id={r.category} cats={cats} />]}
              empty={empty}
            />
          </div>
        </>
      )}
    </div>
  );
}
