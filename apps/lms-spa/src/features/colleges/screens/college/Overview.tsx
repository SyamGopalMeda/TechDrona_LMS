/** College page header + Overview tab (old college.js header / overviewTab / collegeInfo / researchBlock). */
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { fmt, today } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import type { College } from "../../lib/types";
import { Badge, Button, ContactActions, Icon, Kpi, Kv, Menu, Provenance, Section, StatusBadge, WriteOnly } from "../../ui";
import { logCall } from "../../forms/LogCall";
import { recordEnrollment } from "../../forms/Enrollment";
import { addFollowup } from "../../forms/Followup";
import { logActivity } from "../../forms/Activity";
import { addContact } from "../../forms/Contact";
import { ROLE_LABEL } from "../../forms/labels";
import { CollegeLiveCard, ResearchBadge } from "../live/CollegeLiveCard";
import { PERF_STATUS, PerfChip, Progress, VerifiedStateBadge, pLevelOf, pctText, remainingText, type PlanCollege } from "../shared/dashboard";
import { VERIFY_FIELDS, FieldVerificationBadge, editCollegeFull, fieldVerification, tracksVerification, verifyFields } from "./CollegeForm";
import { addPerson, setCollegeTarget, type CollegeCtx } from "./ctx";
import { autonomyText, collegeLabel, isActive, naacGrade, nirfText, ownershipText } from "./model";
import { Btn, Callout, SourceLink, Txt, branchLabel } from "./parts";

/* ------------------------------------------------------------------ header */

export function CollegeHeader({ c: cx }: { c: CollegeCtx }) {
  const navigate = useNavigate();
  const { d, s, meta, research } = cx;
  const c = d.college;
  const r = d.rollup;
  const district = meta?.districts.find((x) => x.id === c.district_id) ?? null;
  const city = meta?.cities.find((x) => x.id === c.city_id) ?? null;
  const p = pLevelOf(c, research ? new Map([[c.id, research]]) : null);
  const lead = s.lead;
  const label = collegeLabel(c);
  const hasT = (r.target ?? 0) > 0;
  const placeText = [city?.name, district?.name || c.district_id].filter(Boolean).join(", ");

  return (
    <header className="vc-head">
      <div className="vc-head-main">
        <div className="vc-kicker">
          {p ? (
            <span title="Research priority: P1 = approach first, Hold = not now">
              <Badge tone={p === "P1" ? "brand" : p === "Hold" ? "neutral" : "info"}>{p === "Hold" ? "Priority: on hold" : `Priority ${p}`}</Badge>
            </span>
          ) : null}
          {c.targeted ? <Badge tone="brand">Targeted</Badge> : <Badge tone="neutral">Not targeted</Badge>}
          <StatusBadge kind="op_status" value={c.op_status || "pending"} />
          {c.is_demo ? <Badge tone="bad">DEMO</Badge> : null}
        </div>
        <h1 className="vc-title">{c.name || c.short_name || c.id}</h1>
        <div className="vc-loc">
          <Icon name="map" size={14} />
          {c.short_name && c.short_name !== c.name ? <span className="vc-short">{c.short_name}</span> : null}
          <span>
            {city ? <Link to={portalPath.city(c.district_id, city.id)}>{city.name}</Link> : null}
            {city && district ? ", " : null}
            {district ? <Link to={portalPath.district(district.id)}>{district.name}</Link> : city ? null : placeText || "—"}
          </span>
        </div>
        {lead ? (
          <div className="vc-leadline">
            <Icon name="lead" size={16} />
            <span className="vx-muted">College lead</span>
            <Link to={portalPath.person(lead.id)} className="vc-leadname">
              {lead.full_name}
            </Link>
            {lead.status === "onboarding" ? <Badge tone="warn">Onboarding</Badge> : null}
            <ContactActions phone={lead.phone} email={lead.email} compact name={lead.full_name} />
          </div>
        ) : (
          <div className="vc-leadline is-missing">
            <Icon name="warn" size={16} />
            <span>No college lead yet</span>
            <WriteOnly>
              <Btn small tone="primary" onClick={() => addPerson(cx, "college_lead")}>
                Appoint
              </Btn>
            </WriteOnly>
          </div>
        )}
      </div>
      <div className="vc-head-side">
        {hasT ? (
          <button type="button" className="vc-tgt" title="Open targets & performance" onClick={() => cx.go("performance")}>
            <span className="vc-tgt-top">
              <strong className="td-num">{`${fmt.num(r.enrolled ?? 0)} / ${fmt.num(r.target)}`}</strong>
              <span className="vx-muted vx-small">confirmed</span>
              <span className="vc-tgt-pct td-num">{pctText(r.pct)}</span>
            </span>
            <Progress target={r.target} done={r.enrolled ?? 0} size="sm" />
            <span className="vc-tgt-sub vx-small">
              {remainingText(r) || ""}
              {r.pace_status && PERF_STATUS[r.pace_status] ? <PerfChip status={r.pace_status} /> : r.on_track != null ? <StatusBadge kind="on_track" value={r.on_track} /> : null}
            </span>
          </button>
        ) : (
          <div className="vc-tgt is-empty">
            <span className="vx-small">{r.target === 0 ? "Target 0" : "No college target"}</span>
            <span className="vx-muted vx-small">{`${fmt.num(r.enrolled ?? 0)} confirmed`}</span>
            <WriteOnly>
              <Btn small icon="target" onClick={() => setCollegeTarget(cx)}>
                Set target
              </Btn>
            </WriteOnly>
          </div>
        )}
        <div className="vc-head-acts" role="toolbar" aria-label="College actions">
          <WriteOnly>
            <Button icon="phone" tone="primary" onClick={() => void logCall({ college_id: c.id, contacts: d.contacts, college_label: label })}>
              Log call
            </Button>
            <Button icon="plus" className="vc-act-enrol" onClick={() => void recordEnrollment({ college_id: c.id })}>
              Record enrollment
            </Button>
          </WriteOnly>
          <Menu
            label="More"
            icon="more"
            tone="secondary"
            ariaLabel="More actions for this college"
            items={[
              { label: "Add follow-up", icon: "followup", writeOnly: true, onClick: () => void addFollowup({ scope_type: "college", scope_id: c.id, college_id: c.id, label }) },
              { label: "Log activity", icon: "clock", writeOnly: true, onClick: () => void logActivity({ college_id: c.id }) },
              { label: "Add person to the team", icon: "people", writeOnly: true, onClick: () => addPerson(cx, lead ? "ambassador" : "college_lead") },
              { label: hasT ? "Change college target" : "Set college target", icon: "target", writeOnly: true, onClick: () => setCollegeTarget(cx) },
              { label: "Edit college details", icon: "edit", writeOnly: true, onClick: () => void editCollegeFull(c.id) },
              { label: "Research plan for this college", icon: "analytics", onClick: () => void navigate(`${portalPath.plan}?college=${encodeURIComponent(c.id)}`) },
              { label: "Change history", icon: "audit", onClick: () => cx.go("activity") },
            ]}
          />
        </div>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ overview */

export function OverviewTab({ c: cx }: { c: CollegeCtx }) {
  const { d, s, ex, research } = cx;
  const c = d.college;
  const r = d.rollup;
  const relevant = s.branches.filter((b) => b.is_relevant);
  const gaps = s.branches.filter((b) => b._gap);
  const ambs = s.people.filter((p) => isActive(p) && (p.role === "ambassador" || p.role === "ambassador_lead"));
  const cc = d.call_info?.contact_counts ?? {};
  const contacts = d.contacts ?? [];
  const hasT = (r.target ?? 0) > 0;

  const steps: ReactNode[] = [];
  if (!s.lead)
    steps.push(
      <Callout key="lead" tone="bad" title="No college lead appointed" action={<WriteOnly><Btn small tone="primary" onClick={() => addPerson(cx, "college_lead")}>Appoint college lead</Btn></WriteOnly>}>
        One student is accountable for the whole college; ambassadors report to them.
      </Callout>,
    );
  if (s.unassigned.size)
    steps.push(
      <Callout key="un" tone="warn" title={`${fmt.plural(s.unassigned.size, "person", "people")} without a valid lead`} action={<Btn small onClick={() => cx.go("team")}>Assign in Team</Btn>}>
        They need a lead in this college to report to.
      </Callout>,
    );
  if (gaps.length)
    steps.push(
      <Callout
        key="gaps"
        tone="warn"
        title={`${fmt.plural(gaps.length, "target branch has", "target branches have")} no ambassador`}
        action={<WriteOnly><Btn small onClick={() => addPerson(cx, "ambassador", { branch_ids: [gaps[0]!.id] })}>Recruit</Btn></WriteOnly>}
      >
        {gaps.map(branchLabel).join(", ")}
      </Callout>,
    );
  if (!contacts.length)
    steps.push(
      <Callout key="contacts" tone="info" title="No contact numbers yet" action={<WriteOnly><Btn small onClick={() => void addContact({ college_id: c.id })}>Add contact</Btn></WriteOnly>}>
        {c.phone ? "The college office number is under “College information”. Add it as a contact so calls can be logged." : "Add the TPO, principal or office number."}
      </Callout>,
    );
  if (!hasT && r.target !== 0) {
    const rt = research?.research_target;
    steps.push(
      <Callout key="target" tone="info" title="No college target" action={<WriteOnly><Btn small onClick={() => setCollegeTarget(cx)}>Set target</Btn></WriteOnly>}>
        {rt ? `Research suggests ${fmt.num(rt.min)}–${fmt.num(rt.max)} (average ${fmt.num(rt.avg)}).` : "Set one to track pace."}
      </Callout>,
    );
  }

  return (
    <div className="vc-tab vc-overview">
      <div className="vc-kpis">
        <Kpi
          label="College lead"
          value={
            <span className="vc-kpi-text" title={s.lead?.full_name}>
              {s.lead ? s.lead.full_name : "None"}
            </span>
          }
          sub={s.lead ? ROLE_LABEL.college_lead : "Appoint one"}
          tone={s.lead ? "good" : "bad"}
          icon="lead"
          onClick={() => cx.go("team")}
        />
        <Kpi
          label="Ambassadors"
          value={fmt.num(ambs.length)}
          sub={
            [research && research.ambassadors_research != null ? `${fmt.num(research.ambassadors_research)} suggested` : null, s.unassigned.size ? `${fmt.num(s.unassigned.size)} unassigned` : null]
              .filter(Boolean)
              .join(" · ") || undefined
          }
          tone={s.unassigned.size ? "warn" : undefined}
          icon="ambassador"
          onClick={() => cx.go("team")}
        />
        <Kpi
          label="Confirmed"
          value={hasT ? `${fmt.num(r.enrolled ?? 0)} / ${fmt.num(r.target)}` : fmt.num(r.enrolled ?? 0)}
          sub={hasT ? `${pctText(r.pct)} · ${remainingText(r) || ""}` : "No target yet"}
          icon="target"
          onClick={() => cx.go("performance")}
        />
        <Kpi
          label="Target branches with an ambassador"
          value={relevant.length ? `${fmt.num(relevant.length - gaps.length)} / ${fmt.num(relevant.length)}` : "—"}
          sub={gaps.length ? `${fmt.plural(gaps.length, "branch", "branches")} without ambassador` : relevant.length ? "all covered" : "no target branches recorded"}
          tone={gaps.length ? "warn" : undefined}
          icon="branch"
          onClick={() => cx.go("branches")}
        />
        <Kpi label="Contacts" value={fmt.num(cc.total ?? contacts.length)} sub={cc.working ? `${fmt.num(cc.working)} working` : "none confirmed working"} icon="phone" onClick={() => cx.go("calls")} />
        <Kpi
          label="Exams"
          value={
            <span className="vc-kpi-text">
              <StatusBadge kind="exam_state" value={ex.state || "unknown"} />
            </span>
          }
          sub={ex.outreachFrom && ex.outreachFrom > today() ? `outreach from ${fmt.date(ex.outreachFrom)}` : undefined}
          icon="exam"
          onClick={() => cx.go("exams")}
        />
      </div>
      <CollegeLiveCard collegeId={c.id} college={c} />
      {steps.length ? (
        <Section title="Next steps">
          <div className="vc-steps">{steps}</div>
        </Section>
      ) : null}
      <Section
        title="College information"
        sub={
          <span>
            <ResearchBadge />
            {tracksVerification(c) ? " Each value shows whether it is verified (with source and date) or unverified." : null}
          </span>
        }
        actions={
          <WriteOnly>
            <Btn small icon="edit" onClick={() => void editCollegeFull(c.id)}>
              Edit details
            </Btn>
          </WriteOnly>
        }
      >
        <CollegeInfo c={c} />
      </Section>
      {research ? <ResearchBlock p={research} cx={cx} /> : null}
    </div>
  );
}

const linkBtn = "vx-linkbtn td-linkbtn vx-small";

/** College facts; tracked fields carry their verification state and a "Mark verified" action. */
export function CollegeInfo({ c }: { c: College }) {
  const track = tracksVerification(c);
  const cr = c as College & Record<string, unknown>;
  const vrow = (field: string, labelText: string, value: ReactNode): [ReactNode, ReactNode] => {
    const v = track ? fieldVerification(c, field) : null;
    const actions =
      track && value ? (
        <WriteOnly>
          {v?.state === "verified" ? (
            <button type="button" className={linkBtn} onClick={() => void verifyFields(c, [field], { clear: true })}>
              Mark unverified
            </button>
          ) : (
            <button type="button" className={linkBtn} onClick={() => void verifyFields(c, [field])}>
              Mark verified
            </button>
          )}
        </WriteOnly>
      ) : null;
    return [
      labelText,
      <div className="vc-vval">
        <span className="vc-vval-v">{value || (track ? <span className="vx-muted">—</span> : <Txt v={null} />)}</span>
        {track ? <FieldVerificationBadge c={c} field={field} /> : null}
        {actions}
      </div>,
    ];
  };
  const contactNode = (k: "phone" | "email" | "website", v: unknown): ReactNode => {
    if (!v) return null;
    const sv = String(v);
    if (k === "phone")
      return (
        <span className="vc-cphone">
          {sv}
          <ContactActions phone={(sv.split(/[/,;]/)[0] ?? "").trim()} compact />
        </span>
      );
    if (k === "email") return <a href={`mailto:${sv}`}>{sv}</a>;
    return /^https?:\/\//i.test(sv) ? (
      <a href={sv} target="_blank" rel="noopener noreferrer">
        {sv.replace(/^https?:\/\//, "").slice(0, 60)}
      </a>
    ) : (
      sv
    );
  };
  const unverified = track ? VERIFY_FIELDS.filter(([f]) => cr[f] && fieldVerification(c, f).state !== "verified").map(([f]) => f) : [];
  const yn = (v: unknown) => (v === "yes" ? <Badge tone="good">Yes</Badge> : v === "no" ? <Badge tone="bad">No</Badge> : <span className="vx-muted">not known</span>);
  const titled = (text: string, full: unknown) => (full && full !== text ? <span title={String(full)}>{text}</span> : text);
  const naac = naacGrade(c.naac);
  const nirf = nirfText(c.nirf);
  const dataState = c.data_status === ("partly_verified" as string) ? "partly" : c.data_status;
  const aka = [c.short_name, ...(Array.isArray(c.aliases) ? c.aliases : [])].filter((x, i, a) => x && a.indexOf(x) === i && x !== c.name).join(", ");
  const totalIntake = cr.total_intake as number | null | undefined;
  const opSource = cr.op_status_source as string | null | undefined;

  const main: ([ReactNode, ReactNode] | null)[] = [
    vrow("phone", "Office phone", contactNode("phone", c.phone)),
    vrow("email", "Office email", contactNode("email", c.email)),
    vrow("website", "Website", contactNode("website", c.website)),
    ["Address", c.address || <Txt v={null} />],
    vrow("ownership", "Type of institution", ownershipText(c.ownership)),
    ["NAAC grade", naac ? titled(naac, c.naac) : <span className="vx-muted">Not found</span>],
    ["NIRF ranking (2025)", nirf ? titled(nirf, c.nirf) : <span className="vx-muted">Not found</span>],
    vrow(
      "op_status",
      "Operating status",
      <span className="vx-row">
        <StatusBadge kind="op_status" value={c.op_status || "pending"} />
        {opSource ? <SourceLink url={opSource} label="evidence" /> : null}
      </span>,
    ),
    totalIntake
      ? [
          "Seats per year (all branches)",
          <span>
            {fmt.num(totalIntake)}
            {cr.total_intake_source ? (
              <span className="vx-small">
                {" · "}
                <SourceLink url={String(cr.total_intake_source).split(/\s+/)[0]} label="source" />
              </span>
            ) : null}
          </span>,
        ]
      : null,
  ];
  const auto = autonomyText(c.autonomous);
  const more: ([ReactNode, ReactNode] | null)[] = [
    vrow("name", "Official name", c.name),
    aka ? ["Also known as", aka] : null,
    vrow("district_id", "District", String(cr.district_name || c.district_id || "")),
    vrow("city_id", "City / town", String(cr.city_name || c.city_id || "")),
    c.affiliation ? vrow("affiliation", "Affiliated university", c.affiliation) : null,
    auto ? ["Autonomous?", auto] : null,
    c.tier ? ["Research tier", <span title="Research grouping: Tier 1 = strongest colleges, Tier 3 = the rest. Used in the calling priority.">{c.tier}</span>] : null,
    [
      "Admitting new students",
      <span className="vx-row">
        <span>2025-26</span>
        {yn(cr.op_2025_26)}
        <span>2026-27</span>
        {yn(cr.op_2026_27)}
      </span>,
    ],
    c.op_status_note ? ["Why this status", <span className="vx-small">{c.op_status_note}</span>] : null,
    c.naac && c.naac !== naac ? ["NAAC (research detail)", <span className="vx-small">{c.naac}</span>] : null,
    c.nirf && c.nirf !== nirf ? ["NIRF (research detail)", <span className="vx-small">{c.nirf}</span>] : null,
    c.geo_precision
      ? ["Map pin", c.geo_precision === "exact" ? "Exact location" : c.geo_precision === "pending" ? "Not placed yet" : c.geo_precision === "town" ? "Approximate (town centre)" : "Approximate (district centre)"]
      : null,
    c.sno ? ["Master list no.", String(c.sno)] : null,
    dataState ? ["Checked against sources", <VerifiedStateBadge state={dataState} />] : null,
    c.notes ? ["Research notes", <span className="vx-small">{c.notes}</span>] : null,
    c.updated_at ? ["Last updated", `${fmt.date(c.updated_at)}${c.updated_by ? ` by ${c.updated_by}` : ""}`] : null,
  ];
  return (
    <div>
      {track && unverified.length ? (
        <div className="vc-vbar">
          <span>{`${fmt.plural(unverified.length, "value")} not verified yet.`}</span>
          <WriteOnly>
            <button type="button" className="vx-linkbtn td-linkbtn" onClick={() => void verifyFields(c, unverified)}>
              Verify them with one source
            </button>
          </WriteOnly>
        </div>
      ) : null}
      <Kv pairs={main} />
      <details className="vc-more" style={{ marginTop: "var(--sp-3, 12px)" }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>More details</summary>
        <Kv pairs={more} />
      </details>
    </div>
  );
}

function ResearchBlock({ p, cx }: { p: PlanCollege; cx: CollegeCtx }) {
  const rt = p.research_target ?? null;
  const recruited = cx.s.people.filter((x) => isActive(x) && x.role !== "college_lead").length;
  return (
    <Section
      title="Research plan"
      sub="From the research import. Estimates, not live data."
      actions={
        <Link to={`${portalPath.plan}?college=${encodeURIComponent(p.college_id)}`} className="vx-link vx-small">
          Open in planner
        </Link>
      }
    >
      <Kv
        pairs={[
          [
            "Research priority",
            <span className="vx-row">
              {p.p_level ? <Badge tone={p.p_level === "P1" ? "brand" : "info"}>{p.p_level === "Hold" ? "On hold" : p.p_level}</Badge> : "—"}
              {p.targeted ? <Badge tone="brand">Recommended to target</Badge> : <Badge tone="neutral">Not recommended now</Badge>}
              {p.hold_reason ? <span className="vx-small vx-muted">{p.hold_reason}</span> : null}
            </span>,
          ],
          rt && rt.avg != null
            ? [
                "Expected enrollments",
                <span>
                  {`${fmt.num(rt.min)}–${fmt.num(rt.max)} (average ${fmt.num(rt.avg)}) `}
                  <Provenance basis="estimated" />
                </span>,
              ]
            : null,
          p.ambassadors_research != null
            ? [
                "Ambassadors suggested",
                <span>
                  {`${fmt.num(p.ambassadors_research)} `}
                  <Provenance basis="estimated" />
                  <span className="vx-muted vx-small">{` · ${fmt.num(recruited)} recruited`}</span>
                </span>,
              ]
            : null,
          p.college_leads_research != null
            ? ["College lead", p.college_leads_research === 0.5 ? "One lead shared with a nearby college" : p.college_leads_research ? "One for this college" : "None planned"]
            : null,
        ]}
      />
    </Section>
  );
}
