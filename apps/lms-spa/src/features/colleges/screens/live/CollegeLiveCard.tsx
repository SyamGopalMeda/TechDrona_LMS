/**
 * College page card "Official live data" (port of live.js collegeLiveCard): presence in the official lists, values
 * that differ from our record (with "Use official value"), the EAPCET / ECET / JNTUK records and notices naming the
 * college. GET /api/live/college/:id; reloads when a live refresh finishes.
 */
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { portalApi } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import type { College } from "../../lib/types";
import { Badge, Button, DataTable, ErrorCard, Icon, Kv, Section, Skeleton, WriteOnly, confirm, toast } from "../../ui";
import { useReloadOnLiveFinish } from "./ExamNoticesCard";
import { Callout, ExtLink, NoticeList, RESEARCH_LABEL, SourceLine, UnavailableNote, When, isUnavailable, type Notice } from "./parts";
import { absTime, relTime, type LiveSource } from "./store";

interface FeedLink {
  basis?: string;
  code?: string | null;
  cc?: string | null;
  score?: number | string | null;
}
interface FeedBranch {
  code?: string | null;
  name?: string | null;
  total_seats?: number | null;
  filled?: number | null;
  left_over_seats?: number | null;
  fee?: number | string | null;
  course_type?: string | null;
}
interface FeedRecord {
  code?: string | null;
  cc?: string | null;
  name?: string | null;
  place?: string | null;
  district?: string | null;
  affiliated_to?: string | null;
  college_type?: string | null;
  aid_unaid?: string | null;
  co_educ?: string | null;
  minority?: string | null;
  year_of_estab?: string | number | null;
  phone?: string | null;
  ao_mobile?: string | null;
  email?: string | null;
  website?: string | null;
  courses?: string[] | string | null;
  branches?: FeedBranch[];
  totals?: { seats?: number | null; filled?: number | null; left_over?: number | null };
}
interface FeedPart {
  link?: FeedLink | null;
  record?: FeedRecord | null;
  source?: Partial<LiveSource> | null;
}
interface LiveDiff {
  field?: string;
  label?: string;
  ours?: unknown;
  live?: unknown;
  source_id?: string;
  source_name?: string;
  checked_at?: string;
  note?: string | null;
  note_checked_at?: string | null;
}
export interface CollegeLive {
  checked_at?: string | null;
  signal?: string;
  signal_text?: string | null;
  presence?: Record<string, boolean | null | undefined>;
  eapcet?: FeedPart | null;
  ecet?: FeedPart | null;
  jntuk?: FeedPart | null;
  website?: { ok?: boolean; checked_at?: string | null; http_status?: number | null; error?: string | null; last_ok_at?: string | null } | null;
  diffs?: LiveDiff[];
  announcements?: Notice[];
  [k: string]: unknown;
}

const PRESENCE: [key: string, label: string][] = [
  ["eapcet", "B.Tech counselling (EAPCET 2026)"],
  ["ecet", "Lateral-entry counselling (ECET 2026)"],
  ["jntuk_affiliated", "JNTUK affiliated"],
  ["website", "Website up"],
];

function PresenceItem({ k, label, d }: { k: string; label: string; d: CollegeLive }) {
  const v = d.presence?.[k];
  const part = k === "jntuk_affiliated" ? d.jntuk : k === "website" ? null : k === "eapcet" ? d.eapcet : k === "ecet" ? d.ecet : null;
  let badge: ReactNode;
  let sub: ReactNode;
  if (k === "website") {
    const w = d.website;
    if (!w) {
      badge = <Badge tone="neutral">Website: not checked</Badge>;
      sub = <span className="lv-muted">No website on record to check</span>;
    } else if (v === true || w.ok) {
      badge = <Badge tone="good">Website up</Badge>;
      sub = <When iso={w.checked_at} prefix="checked " />;
    } else {
      badge = <Badge tone="warn">Website not answering</Badge>;
      sub = (
        <span>
          {[w.http_status ? `HTTP ${w.http_status}` : null, w.error ? String(w.error).slice(0, 80) : null].filter(Boolean).join(" · ") || "No answer"}
          {" · "}
          <When iso={w.checked_at} prefix="checked " />
          {w.last_ok_at ? <span className="lv-muted">{` · last up ${relTime(w.last_ok_at)}`}</span> : null}
        </span>
      );
    }
  } else if (!part) {
    badge = <Badge tone="neutral">{`${label}: not linked`}</Badge>;
    sub = <span className="lv-muted">Not linked to this source</span>;
  } else if (v === null || v === undefined) {
    badge = <Badge tone="neutral">{`${label}: unknown`}</Badge>;
    sub = part.source?.last_success_at ? <When iso={part.source.last_success_at} prefix="checked " /> : <span className="lv-muted">Source not fetched yet</span>;
  } else {
    const yes = k === "jntuk_affiliated" ? "JNTUK affiliated" : `Listed in ${label}`;
    const no = k === "jntuk_affiliated" ? "Not matched in the JNTUK list" : `Not matched in the ${label} list`;
    badge = <Badge tone={v ? "good" : "warn"}>{v ? yes : no}</Badge>;
    sub = part.source?.using_fallback ? (
      <span className="lv-warntext">Source unreachable — last copy {part.source.last_success_at ? absTime(part.source.last_success_at) : ""}</span>
    ) : (
      <When iso={part.source?.last_success_at} prefix="checked " />
    );
  }
  return (
    <li className="lv-presence__item">
      {badge}
      <div className="lv-small">{sub}</div>
    </li>
  );
}

function LinkBasis({ link }: { link: FeedLink | null | undefined }) {
  if (!link) return null;
  if (link.basis === "research_code") return <Badge tone="good">{`Linked by college code${link.code || link.cc ? ` (${link.code || link.cc})` : ""}`}</Badge>;
  const n = Number(link.score);
  const sc = link.score !== null && link.score !== undefined && Number.isFinite(n) ? ` · ${Math.round(n * (n <= 1 ? 100 : 1))}% match` : "";
  return <Badge tone="warn">{`Linked by name — please check${sc}`}</Badge>;
}

function FeedBlock({ label, part, branches = true }: { label: string; part: FeedPart | null | undefined; branches?: boolean }) {
  if (!part)
    return (
      <div className="lv-feed">
        <h3 className="lv-h3">{label}</h3>
        <p className="lv-muted lv-small">Not linked to this source.</p>
      </div>
    );
  const rec = part.record;
  const head = (
    <div className="lv-feed__head">
      <h3 className="lv-h3">{label}</h3>
      <LinkBasis link={part.link} />
    </div>
  );
  if (!rec)
    return (
      <div className="lv-feed">
        {head}
        <SourceLine src={part.source} />
        <p className="lv-muted lv-small">Linked, but this college is not in the latest copy of the source.</p>
      </div>
    );
  const web = rec.website ? <ExtLink url={/^https?:/i.test(rec.website) ? rec.website : `http://${rec.website}`} label={rec.website} /> : null;
  const br = Array.isArray(rec.branches) ? rec.branches : [];
  const tt = rec.totals ?? {};
  return (
    <div className="lv-feed">
      {head}
      <SourceLine src={part.source} />
      <Kv
        pairs={[
          rec.code ? ["Counselling college code", rec.code] : null,
          rec.cc ? ["JNTUK college code", rec.cc] : null,
          rec.name ? ["Name in this list", rec.name] : null,
          rec.place || rec.district ? ["Place", [rec.place, rec.district].filter(Boolean).join(", ")] : null,
          rec.affiliated_to ? ["Affiliated to", rec.affiliated_to] : null,
          rec.college_type || rec.aid_unaid || rec.co_educ ? ["Type", [rec.college_type, rec.aid_unaid, rec.co_educ, rec.minority].filter(Boolean).join(" · ")] : null,
          rec.year_of_estab ? ["Established", String(rec.year_of_estab)] : null,
          rec.phone ? ["Office phone", rec.phone] : null,
          rec.ao_mobile ? ["Admissions officer (mobile)", rec.ao_mobile] : null,
          rec.email ? ["Office email", rec.email] : null,
          web ? ["Website", web] : null,
          // rec.entry_date (the feed's own bookkeeping date) is not shown: it says nothing about the college
          rec.courses ? ["Courses", Array.isArray(rec.courses) ? rec.courses.join(", ") : String(rec.courses)] : null,
        ]}
      />
      {branches && br.length ? (
        <>
          <h4 className="lv-h4">
            {`Branches in ${label}`}
            {tt.seats !== null && tt.seats !== undefined ? (
              <span className="lv-muted lv-small">{` · ${fmt.num(tt.seats)} seats, ${fmt.num(tt.filled)} filled, ${fmt.num(tt.left_over)} still empty`}</span>
            ) : null}
          </h4>
          <DataTable<FeedBranch>
            caption={`${label} branches`}
            rowKey={(r) => String(r.code || r.name)}
            dense
            rows={br}
            columns={[
              {
                key: "name",
                label: "Branch",
                primary: true,
                minWidth: 180,
                render: (r) => (
                  <span>
                    {r.name || r.code || "—"}
                    {r.code && r.name ? <span className="lv-muted lv-small">{` (${r.code})`}</span> : null}
                  </span>
                ),
              },
              { key: "total_seats", label: "Seats", align: "right", minWidth: 70, render: (r) => fmt.num(r.total_seats) },
              { key: "filled", label: "Filled", align: "right", minWidth: 70, render: (r) => fmt.num(r.filled) },
              { key: "left_over_seats", label: "Still empty", align: "right", minWidth: 80, render: (r) => fmt.num(r.left_over_seats) },
              {
                key: "fee",
                label: "Fee / year",
                align: "right",
                minWidth: 90,
                render: (r) => (r.fee === null || r.fee === undefined || r.fee === "" ? "—" : Number.isFinite(Number(r.fee)) ? fmt.inr(Number(r.fee)) : String(r.fee)),
              },
              { key: "course_type", label: "Programme", priority: 3, minWidth: 90, render: (r) => r.course_type || "—" },
            ]}
          />
        </>
      ) : null}
    </div>
  );
}

const shown = (v: unknown): string => (v === null || v === undefined || v === "" ? "—" : String(v));

function DiffItem({ x, collegeId }: { x: LiveDiff; collegeId: string }) {
  const [busy, setBusy] = useState(false);
  const canUse = !!x.field && x.live !== null && x.live !== undefined && x.live !== "";
  const name = x.label || x.field || "";
  const use = async () => {
    const ok = await confirm({
      title: `Replace ${String(name).toLowerCase()}?`,
      text: `“${x.ours ?? "—"}” becomes “${String(x.live)}”. The change is recorded as verified from ${x.source_name || "the official source"}, fetched ${absTime(x.checked_at)}.`,
      confirmLabel: "Use official value",
      tone: "primary",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await portalApi.patch(`colleges/${encodeURIComponent(collegeId)}`, {
        [x.field!]: x.live,
        sources: { [x.field!]: `${x.source_name || x.source_id || "Official source"}, fetched ${fmt.date(String(x.checked_at ?? "").slice(0, 10))}` },
      });
      toast(`${name} updated from the official source`, "good");
      // the write clears the read cache: the college page and this card refetch
    } catch (err) {
      toast(err instanceof Error && err.message ? err.message : "Could not save", "bad");
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="lv-diff">
      <div className="lv-diff__label">{name}</div>
      <div className="lv-diff__vals">
        <div>
          <span className="lv-diff__k">Our record: </span>
          <span className="lv-diff__ours">{shown(x.ours)}</span>
        </div>
        <div>
          <span className="lv-diff__k">Official list: </span>
          <strong>{shown(x.live)}</strong>
        </div>
      </div>
      <div className="lv-small lv-muted">
        {`${x.source_name || x.source_id || "source"} · checked `}
        <When iso={x.checked_at} />
      </div>
      {x.note ? (
        <div className="lv-diff__note">
          <Icon name="info" size={14} />
          <span>
            {String(x.note)}
            {x.note_checked_at ? (
              <span className="lv-muted">
                {" (checked "}
                <When iso={x.note_checked_at} />)
              </span>
            ) : null}
          </span>
        </div>
      ) : null}
      {canUse ? (
        <WriteOnly>
          <Button size="sm" tone={x.note ? "secondary" : "primary"} icon="check" busy={busy} onClick={() => void use()}>
            Use official value
          </Button>
        </WriteOnly>
      ) : null}
    </li>
  );
}

function DiffList({ d, collegeId }: { d: CollegeLive; collegeId: string }) {
  const diffs = Array.isArray(d.diffs) ? d.diffs : [];
  if (!diffs.length) return null;
  return (
    <div className="lv-diffs">
      <h3 className="lv-h3">
        <Icon name="warn" size={16} />
        {` ${diffs.length === 1 ? "One value differs" : `${diffs.length} values differ`} from the official source`}
      </h3>
      <ul className="lv-difflist">
        {diffs.map((x, i) => (
          <DiffItem key={`${x.field ?? ""}-${i}`} x={x} collegeId={collegeId} />
        ))}
      </ul>
    </div>
  );
}

function CollegeLiveBody({ d, collegeId, college }: { d: CollegeLive; collegeId: string; college: College }) {
  const tone = d.signal === "listed" ? "good" : d.signal === "not_found_anywhere" ? "warn" : "info";
  const ann = Array.isArray(d.announcements) ? d.announcements : [];
  return (
    <>
      {d.signal_text ? <Callout tone={tone}>{d.signal_text}</Callout> : null}
      <ul className="lv-presence" aria-label="Presence in official sources">
        {PRESENCE.map(([k, l]) => (
          <PresenceItem key={k} k={k} label={l} d={d} />
        ))}
      </ul>
      <DiffList d={d} collegeId={collegeId} />
      <FeedBlock label="B.Tech counselling list (AP EAPCET 2026)" part={d.eapcet} />
      <details className="lv-more-details">
        <summary>Lateral-entry (ECET) and JNTUK details</summary>
        <FeedBlock label="Lateral-entry counselling list (AP ECET 2026)" part={d.ecet} />
        <FeedBlock label="JNTUK affiliation list" part={d.jntuk} branches={false} />
      </details>
      {ann.length ? (
        <div className="lv-feed">
          <h3 className="lv-h3">Official notices mentioning this college</h3>
          <NoticeList items={ann.slice(0, 5)} />
          {ann.length > 5 ? (
            <Link to={`${portalPath.notices}?q=${encodeURIComponent(college.short_name || college.name || "")}`} className="lv-more">
              {`All ${ann.length} notices`}
            </Link>
          ) : null}
        </div>
      ) : null}
      <p className="lv-small lv-muted lv-foot">
        Everything else on this page — and the fields under “College information” — is <Badge tone="neutral">{RESEARCH_LABEL}</Badge>.
      </p>
    </>
  );
}

export function CollegeLiveCard({ collegeId, college }: { collegeId: string; college: College }) {
  const { data, error, loading, reload } = usePortalQuery<CollegeLive>(`live/college/${encodeURIComponent(collegeId)}`);
  useReloadOnLiveFinish(reload);
  const unavailable = !!error && isUnavailable(error);
  return (
    <div className="v-live lv-section lv-collegecard">
      <Section
        title={
          <span className="lv-title">
            <span className="lv-livedot" aria-hidden="true" />
            Official live data
          </span>
        }
        sub={
          data && !unavailable ? (
            <span>
              <span>Fetched from official sources each time the portal opens · checked </span>
              <When iso={data.checked_at} />
            </span>
          ) : null
        }
        actions={
          <Link to={portalPath.live} className="lv-more">
            Sources
            <Icon name="chevron" size={14} />
          </Link>
        }
      >
        <div className="lv-college">
          {unavailable ? (
            <UnavailableNote what="college checks" />
          ) : error && !data ? (
            <ErrorCard title="Could not load the official live data" error={error} retry={() => void reload()} />
          ) : loading || !data ? (
            <Skeleton lines={3} card={false} />
          ) : (
            <CollegeLiveBody d={data} collegeId={collegeId} college={college} />
          )}
        </div>
      </Section>
    </div>
  );
}

export { ResearchBadge } from "./parts";
