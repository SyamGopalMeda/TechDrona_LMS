/**
 * Fast "Log call" dialog (old forms.logCall): who did you call, what happened (outcome buttons with hints),
 * call back on (quick dates, suggested from the outcome), notes and "the college agreed to take part".
 *
 *   await logCall({ college_id: "c9", college_label: "KLU", onSaved })      // imperative (needs <FormsHost/>)
 *   <LogCallDialog collegeId="c9" onDone={…} />                            // declarative
 */
import "../styles/views/calls.css";
import { useRef, useState, type ReactNode } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import type { Call, Contact, CollegeDetail, Followup } from "../lib/types";
import { Chip } from "../ui/Badges";
import { cx } from "../ui/context";
import { ErrorCard, Skeleton } from "../ui/Feedback";
import { Modal, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, KEEP_OPEN } from "./kit";
import { CONTACT_STATUS, ContactStatusBadge, OUTCOMES, contactLabel, formatPhone } from "./labels";
import { addDays, str, today } from "./util";

export interface LogCallOptions {
  college_id: string;
  contact_id?: number | null;
  /** the college's contacts when the caller has them (else loaded) */
  contacts?: Contact[];
  college_label?: string | null;
  onSaved?: (result: LogCallResult) => void;
}

export interface LogCallResult {
  call?: Call;
  contact?: Contact | null;
  followup?: Followup | null;
  [k: string]: unknown;
}

const GROUPS: [string, string][] = [
  ["connected", "Spoke to someone"],
  ["unanswered", "Did not connect"],
  ["bad", "Number problem"],
];
const QUICK: [string, number | null][] = [
  ["No call-back", null],
  ["Today", 0],
  ["Tomorrow", 1],
  ["In 3 days", 3],
  ["Next week", 7],
];

export function LogCallDialog({ open = true, onDone, ...opts }: LogCallOptions & { open?: boolean; onDone: (r: LogCallResult | null) => void }) {
  const need = !opts.contacts;
  const { data, error, loading, reload } = usePortalQuery<CollegeDetail>(need ? `colleges/${encodeURIComponent(opts.college_id)}` : null);
  const contacts = opts.contacts ?? ((data?.contacts as Contact[] | undefined) || []);
  const label = opts.college_label || data?.college?.short_name || data?.college?.name || opts.college_id;
  const title = `Log call — ${label}`;
  if (need && !data) {
    return (
      <Modal open={open} title={title} onClose={() => onDone(null)}>
        {loading ? <Skeleton lines={4} card={false} /> : <ErrorCard title="Could not load the college" error={error} retry={() => void reload()} />}
      </Modal>
    );
  }
  return <LogCallForm open={open} onDone={onDone} {...opts} contacts={contacts} title={title} />;
}

function LogCallForm({ open, onDone, contacts, title, ...opts }: LogCallOptions & { contacts: Contact[]; title: string; open: boolean; onDone: (r: LogCallResult | null) => void }) {
  const t0 = today();
  const initial = opts.contact_id ?? (contacts.find((k) => k.status === "working") ?? contacts.find((k) => k.status === "untested") ?? contacts[0])?.id ?? null;
  const [contact, setContact] = useState<number | null>(initial);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [nextTouched, setNextTouched] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const outBox = useRef<HTMLDivElement>(null);
  const connected = !!outcome && OUTCOMES[outcome]?.group === "connected";

  const pickOutcome = (k: string) => {
    setOutcome(k);
    setErr(null);
    if (!nextTouched) {
      const n = OUTCOMES[k]?.next;
      setNext(n === null || n === undefined ? null : addDays(t0, n));
    }
    if (OUTCOMES[k]?.group !== "connected") setConfirmed(false);
  };

  const contactBtn = (id: number | null, name: string, sub: string, badge?: ReactNode) => {
    const on = contact === id;
    return (
      <button key={String(id)} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} className={cx("vcl-contact", on && "is-on")} onClick={() => setContact(id)}>
        <span className="vcl-contact-main">
          <strong>{name}</strong>
          <span className="vx-muted vx-small">{sub}</span>
        </span>
        {badge ?? null}
      </button>
    );
  };

  return (
    <DialogForm<LogCallResult>
      open={open}
      title={title}
      submitLabel="Save call"
      bare
      onDone={onDone}
      onSubmit={async (key) => {
        if (!outcome) {
          setErr("Choose what happened on the call.");
          outBox.current?.querySelector<HTMLElement>(".vcl-out")?.focus();
          return KEEP_OPEN;
        }
        const payload = { college_id: opts.college_id, contact_id: contact, outcome, notes: str(notes), next_action_at: next, confirms_participation: confirmed || undefined };
        try {
          const r = (await portalApi.post<LogCallResult>("calls", payload, { idempotencyKey: key })) ?? {};
          const k = r.contact;
          toast(
            `Call logged${k && k.status !== "untested" ? ` · number: ${(CONTACT_STATUS[k.status]?.[0] ?? k.status).toLowerCase()}` : ""}${r.followup ? ` · call-back ${fmt.date(r.followup.due_date)}` : ""}`,
            "good",
          );
          opts.onSaved?.(r);
          return r;
        } catch (e) {
          setErr(e instanceof Error && e.message ? e.message : "Could not save the call");
          return KEEP_OPEN;
        }
      }}
    >
      {() => (
        <div className="vcl">
          <section>
            <h3 className="vcl-h">Who did you call?</h3>
            <div className="vcl-contacts" role="radiogroup" aria-label="Who did you call?">
              {contacts.map((k) => contactBtn(k.id, contactLabel(k) || "Contact", k.phone ? formatPhone(k.phone) : k.email || "", <ContactStatusBadge status={k.status} />))}
              {contactBtn(null, contacts.length ? "A number not listed here" : "College number (not in contacts)", "Logged for the college only")}
            </div>
          </section>
          <section>
            <h3 className="vcl-h">What happened?</h3>
            <div className="vcl-outcomes" role="radiogroup" aria-label="What happened?" aria-required="true" aria-invalid={err && !outcome ? true : undefined} ref={outBox}>
              {GROUPS.map(([g, gl]) => (
                <fieldset className="vcl-group" key={g}>
                  <legend>{gl}</legend>
                  <div className="vcl-grid">
                    {Object.entries(OUTCOMES)
                      .filter(([, o]) => o.group === g)
                      .map(([k, o]) => (
                        <button key={k} type="button" role="radio" aria-checked={outcome === k} data-k={k} title={o.hint} className={cx("vcl-out", `vcl-out--${o.tone}`, outcome === k && "is-on")} onClick={() => pickOutcome(k)}>
                          {o.label}
                        </button>
                      ))}
                  </div>
                </fieldset>
              ))}
            </div>
          </section>
          <section>
            <h3 className="vcl-h">Call back on</h3>
            <div className="vcl-next" role="group" aria-label="Call back on">
              {QUICK.map(([l, n]) => {
                const v = n === null ? null : addDays(t0, n);
                return (
                  <Chip
                    key={l}
                    label={l}
                    active={next === v}
                    onClick={() => {
                      setNext(v);
                      setNextTouched(true);
                    }}
                  />
                );
              })}
              <input
                type="date"
                className="td-input td-num vcl-date"
                min={t0}
                aria-label="Pick a call-back date"
                value={next ?? ""}
                onChange={(e) => {
                  setNext(e.target.value || null);
                  setNextTouched(true);
                }}
              />
            </div>
            <p className="vx-muted vx-small vcl-help">A date adds a call-back to Follow-ups, assigned to you. It is suggested from what happened; change it if needed.</p>
          </section>
          <section>
            <h3 className="vcl-h">Notes</h3>
            <textarea className="td-input vcl-notes" rows={2} placeholder="What was said? Who to ask for next time?" aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <label className={cx("vcl-confirm", !connected && "is-disabled")}>
              <input type="checkbox" disabled={!connected} checked={confirmed && connected} onChange={(e) => setConfirmed(e.target.checked)} />
              <span>The college agreed to take part (only after speaking to someone)</span>
            </label>
          </section>
          {err ? (
            <div className="vcl-err" role="alert">
              {err}
            </div>
          ) : null}
        </div>
      )}
    </DialogForm>
  );
}

/** Old API: forms.logCall(ctx, opts). Resolves with the saved call (null when cancelled). */
export function logCall(opts: LogCallOptions): Promise<LogCallResult | null> {
  return openDialog<LogCallResult>((done) => <LogCallDialog {...opts} onDone={done} />);
}
