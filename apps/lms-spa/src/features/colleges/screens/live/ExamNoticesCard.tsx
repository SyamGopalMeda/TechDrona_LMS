/** Exams page card "Latest official exam notices" (port of live.js examNoticesCard): top 5 of category exam. */
import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../../lib/cache";
import { portalPath } from "../../lib/routes";
import { ErrorCard, Icon, Section, Skeleton } from "../../ui";
import { NoticeList, NoticeStatus, isUnavailable, type NoticesAnswer } from "./parts";
import { useLiveStatus } from "./store";

/** Reload `reload` whenever a live refresh finishes (the old LIVE_EVENT `finished`). */
export function useReloadOnLiveFinish(reload: () => unknown): void {
  const { finished } = useLiveStatus();
  const first = useRef(finished);
  useEffect(() => {
    if (finished !== first.current) {
      first.current = finished;
      void reload();
    }
  }, [finished, reload]);
}

export function ExamNoticesCard() {
  const { data, error, loading, reload } = usePortalQuery<NoticesAnswer>("live/announcements", { query: { category: "exam", limit: 5 }, ttl: 60_000 });
  useReloadOnLiveFinish(reload);
  if (error && isUnavailable(error)) return null;
  const items = (Array.isArray(data?.items) ? data.items : []).slice(0, 5);
  return (
    <div className="v-live lv-section">
      <Section
        title="Latest official exam notices"
        sub="Live from the JNTUK notifications page."
        actions={
          <Link to={`${portalPath.notices}?category=exam`} className="lv-more">
            All exam notices
            <Icon name="chevron" size={14} />
          </Link>
        }
      >
        <div className="lv-examcard">
          {error && !data ? (
            <ErrorCard title="Could not load official exam notices" error={error} retry={() => void reload()} />
          ) : loading || !data ? (
            <Skeleton lines={3} card={false} />
          ) : (
            <>
              <NoticeStatus r={data} />
              {items.length ? <NoticeList items={items} /> : <p className="lv-muted">No exam notices in the latest copy of the JNTUK page.</p>}
            </>
          )}
        </div>
      </Section>
    </div>
  );
}
