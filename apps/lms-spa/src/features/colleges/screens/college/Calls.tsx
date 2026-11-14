/** Contacts & calls tab (old college.js callsTab): call status, contacts (working first), call history. */
import { Link } from "react-router";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { Badge, ContactActions, EmptyState, Section, VerifiedBadge, WriteOnly } from "../../ui";
import { logCall } from "../../forms/LogCall";
import { addContact, editContact } from "../../forms/Contact";
import { CONTACT_ROLE_LABEL, CallStatusBadge, ContactStatusBadge, OUTCOMES, contactLabel, formatPhone } from "../../forms/labels";
import type { CollegeCtx } from "./ctx";
import { collegeLabel, type ContactX } from "./model";
import { Btn, SourceLink } from "./parts";

const ROLE_ORDER = ["tpo", "principal", "admissions", "dean", "hod", "office", "other"];
const ST_ORDER: Record<string, number> = { working: 0, untested: 1, non_working: 2, invalid: 3 };

export function CallsTab({ c: cx }: { c: CollegeCtx }) {
  const { d } = cx;
  const c = d.college;
  const info = d.call_info ?? {};
  const contacts = d.contacts ?? [];
  const calls = d.calls ?? [];
  const cc = info.contact_counts ?? {};
  const label = collegeLabel(c);
  const broken = (cc.non_working || 0) + (cc.invalid || 0);
  const agreed = c.participation_confirmed_on as string | null | undefined;

  const verifiedTxt = (k: ContactX) => (k.basis === "verified" ? `verified${k.verified_on ? ` ${fmt.date(k.verified_on)}` : ""}${k.verified_by ? ` by ${k.verified_by}` : ""}` : null);
  const sorted = contacts.slice().sort((a, b) => (ST_ORDER[a.status] ?? 1) - (ST_ORDER[b.status] ?? 1) || ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role));

  return (
    <div className="vc-tab vcc">
      <div className="vcc-summary">
        <CallStatusBadge status={info.call_status || "not_called"} />
        <span className="vx-muted vx-small">
          {[
            fmt.plural(cc.total || 0, "contact"),
            cc.working ? `${fmt.num(cc.working)} working` : null,
            broken ? `${fmt.num(broken)} not working or wrong number` : null,
            fmt.plural(info.calls_total || 0, "call"),
            agreed ? `college agreed ${fmt.date(agreed)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
        <span className="vx-grow" />
        <WriteOnly>
          <Btn small icon="phone" tone="primary" onClick={() => void logCall({ college_id: c.id, contacts, college_label: label })}>
            Log call
          </Btn>
        </WriteOnly>
        <Link to={portalPath.calls} className="vx-link vx-small">
          Calling queue
        </Link>
      </div>

      <Section
        title="Contacts"
        sub="Working numbers first. Status comes from logged calls; the same number cannot be added twice."
        actions={
          <WriteOnly>
            <Btn small icon="plus" onClick={() => void addContact({ college_id: c.id })}>
              Add contact
            </Btn>
          </WriteOnly>
        }
      >
        {contacts.length ? (
          <ul className="vcc-list">
            {sorted.map((k) => (
              <li key={k.id} className="vcc-item">
                <div className="vcc-main">
                  <div className="vcc-title">
                    {contactLabel(k) || "Contact"}
                    <ContactStatusBadge status={k.status} />
                    <VerifiedBadge state={k.basis === "verified" ? "verified" : "unverified"} source={k.source_url} date={k.verified_on} by={k.verified_by} />
                  </div>
                  <div className="vcc-num">
                    {k.phone ? <span className="td-num">{formatPhone(k.phone)}</span> : null}
                    {k.email ? <span>{k.email}</span> : null}
                    <ContactActions phone={k.phone} email={k.email} compact name={contactLabel(k)} />
                  </div>
                  <div className="vx-small vx-muted">
                    {[
                      k.last_call ? `Last call ${fmt.date(k.last_call.called_at)}: ${OUTCOMES[k.last_call.outcome]?.label || k.last_call.outcome}` : "Not tried yet",
                      (k.unanswered_streak ?? 0) >= 2 && k.status !== "working" ? `${k.unanswered_streak} unanswered in a row` : null,
                      k.status_source === "manual" ? "status set by hand" : null,
                      verifiedTxt(k),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                  {k.source_url ? (
                    <div className="vx-small">
                      <SourceLink url={k.source_url} label="source" />
                    </div>
                  ) : null}
                  {k.notes ? <div className="vx-small vx-muted">{k.notes}</div> : null}
                </div>
                <WriteOnly>
                  <div className="vcc-acts">
                    <Btn small icon="phone" onClick={() => void logCall({ college_id: c.id, contacts, contact_id: k.id, college_label: label })}>
                      Log call
                    </Btn>
                    <Btn small icon="edit" tone="ghost" aria={`Edit ${contactLabel(k) || "contact"}`} onClick={() => void editContact(k)}>
                      Edit
                    </Btn>
                  </div>
                </WriteOnly>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No contacts yet"
            icon="phone"
            text={
              c.phone
                ? `The college listing has ${c.phone}. Add it (and the TPO's number when you get it) so calls can be logged against it.`
                : "Add the TPO, principal or office number so calls can be logged and tracked."
            }
            actions={[
              <WriteOnly key="add">
                <Btn small tone="primary" icon="plus" onClick={() => void addContact({ college_id: c.id })}>
                  Add contact
                </Btn>
              </WriteOnly>,
            ]}
          />
        )}
      </Section>

      <Section title={`Call history (${calls.length})`}>
        {calls.length ? (
          <ul className="vcc-list">
            {calls.map((x) => {
              const o = OUTCOMES[x.outcome];
              return (
                <li key={x.id} className="vcc-item">
                  <div className="vcc-main">
                    <div className="vcc-title">
                      <Badge tone={o?.tone || "neutral"}>{o?.label || x.outcome}</Badge>
                      <span>{x.contact_name || (x.contact_role ? CONTACT_ROLE_LABEL[x.contact_role] : x.contact_id ? "Contact" : "College number")}</span>
                      {x.confirms_participation ? <Badge tone="good">College agreed</Badge> : null}
                    </div>
                    <div className="vx-small vx-muted">
                      {[
                        `${fmt.date(x.called_at)}${/T\d{2}:\d{2}/.test(x.called_at) ? `, ${String(x.called_at).slice(11, 16)}` : ""}`,
                        x.caller ? `by ${x.caller}` : null,
                        x.followup_due ? `call-back ${fmt.date(x.followup_due)}${x.followup_status === "done" ? " (done)" : ""}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {x.notes ? <div className="vx-small">{x.notes}</div> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState title="No calls logged yet" icon="clock" text="Use “Log call” after every attempt, even when nobody answers, so the team can see who was tried and when." />
        )}
      </Section>
    </div>
  );
}
