/**
 * Add / edit the exam details of one college and semester (port of exams.js editExam): POST /api/exams for a new row,
 * PATCH /api/exams/:id otherwise. End-sem dates can be an exact date or free text ("Dec 2026, no date yet"); only
 * exact dates drive the timeline and the exam status. Mid / lab windows preview the ranges found in the text.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { portalApi } from "../../lib/api";
import { fmt, today } from "../../lib/fmt";
import { Button, Modal, cx, toast } from "../../ui";
import { EVIDENCE_LABEL, EXAM_CONFIDENCE, EXAM_EVIDENCE, EXAM_STATUSES, EXAM_STATUS_LABEL } from "./labels";
import { isoOnly, textWindows, type ExamRecord } from "./model";

export interface ExamFormTarget {
  college: { college_id: string; name: string };
  row: ExamRecord;
}

function FieldBox({ label, htmlFor, help, full, children }: { label: string; htmlFor?: string; help?: ReactNode; full?: boolean; children: ReactNode }) {
  return (
    <div className={cx("td-field", full && "td-field--full")}>
      <label className="td-field__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {help ? <div className="td-field__help">{help}</div> : null}
    </div>
  );
}

function Select({ id, options, value, onChange, labels = {} }: { id: string; options: readonly string[]; value: string; onChange: (v: string) => void; labels?: Record<string, string> }) {
  const all = value && !options.includes(value) ? [value, ...options] : [...options];
  return (
    <select id={id} className="td-input td-select" value={value || all[0]} onChange={(e) => onChange(e.target.value)}>
      {all.map((o) => (
        <option key={o} value={o}>
          {labels[o] || o}
        </option>
      ))}
    </select>
  );
}

interface DateOrText {
  mode: "date" | "text";
  date: string;
  text: string;
}
const initDot = (v: string | null | undefined): DateOrText => ({ mode: v && !isoOnly(v) ? "text" : "date", date: isoOnly(v) ?? "", text: v && !isoOnly(v) ? v : "" });
const dotValue = (d: DateOrText) => (d.mode === "date" ? d.date : d.text).trim();
const dotIso = (d: DateOrText) => (d.mode === "date" ? d.date || null : isoOnly(d.text));

function DateOrTextInput({ id, value, onChange }: { id: string; value: DateOrText; onChange: (v: DateOrText) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const switched = useRef(false);
  useEffect(() => {
    if (switched.current) ref.current?.focus();
    switched.current = false;
  }, [value.mode]);
  return (
    <div>
      <div className="ex-dt">
        {value.mode === "date" ? (
          <input ref={ref} id={id} type="date" className="td-input td-num" value={value.date} onChange={(e) => onChange({ ...value, date: e.target.value })} />
        ) : (
          <input ref={ref} id={id} type="text" className="td-input" value={value.text} placeholder="e.g. Dec 2026 (no date yet)" onChange={(e) => onChange({ ...value, text: e.target.value })} />
        )}
        <button
          type="button"
          className="ex-switch"
          onClick={() => {
            switched.current = true;
            onChange({ ...value, mode: value.mode === "date" ? "text" : "date" });
          }}
        >
          {value.mode === "date" ? "Type text instead" : "Pick an exact date"}
        </button>
      </div>
      <div className="td-field__help">{value.mode === "date" ? "" : "Text is kept as a note. Only exact dates appear on the timeline and count towards the exam status."}</div>
    </div>
  );
}

function WindowPreview({ value, counts }: { value: string; counts: boolean }) {
  const v = value.trim();
  if (!v)
    return (
      <div className="td-field__help ex-preview" aria-live="polite">
        Optional. Write dates like 2026-11-16 to 2026-11-21 so they appear on the timeline.
      </div>
    );
  const ws = textWindows(v, {});
  return (
    <div className={cx("td-field__help ex-preview", ws.length ? "is-ok" : "is-warn")} aria-live="polite">
      {ws.length
        ? `On the timeline: ${ws.map((w) => (w.start === w.end ? fmt.date(w.start) : `${fmt.date(w.start)} – ${fmt.date(w.end)}`)).join(", ")}${counts ? "" : " (shown only; labs do not change the exam status)"}`
        : "No date range found — this stays a note. Use the form 2026-11-16 to 2026-11-21."}
    </div>
  );
}

const errText = (ex: unknown): string => {
  const e = ex as { message?: string; fields?: Record<string, string> };
  return [e?.message || "Could not save", ...Object.entries(e?.fields ?? {}).map(([k, v]) => `${k}: ${v}`)].join(" — ");
};

export function ExamForm({ target, onClose }: { target: ExamFormTarget | null; onClose: () => void }) {
  return target ? <ExamFormBody key={`${target.college.college_id}-${target.row.semester}-${target.row.id ?? "new"}`} target={target} onClose={onClose} /> : null;
}

function ExamFormBody({ target, onClose }: { target: ExamFormTarget; onClose: () => void }) {
  const { college: c, row: r } = target;
  const isNew = !r.id;
  const uid = useId();
  const id = (k: string) => `${uid}-${k}`;
  const [status, setStatus] = useState(r._missing ? "Unverified" : r.status || EXAM_STATUSES[0]);
  const [examBody, setExamBody] = useState(r.exam_body ?? "");
  const [start, setStart] = useState(() => initDot(r.endsem_start));
  const [end, setEnd] = useState(() => initDot(r.endsem_end));
  const [mid, setMid] = useState(r.mid_window ?? "");
  const [lab, setLab] = useState(r.lab_window ?? "");
  const [src, setSrc] = useState(r.source_url ?? "");
  const [evidence, setEvidence] = useState(r.evidence || "Unverified");
  const [conf, setConf] = useState(r.confidence || "Low");
  const [notice, setNotice] = useState(() => initDot(r.notice_date));
  const [verified, setVerified] = useState(today());
  const [notes, setNotes] = useState(r.notes ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [dateErr, setDateErr] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useMemo(() => portalApi.newKey(), []);
  const srcRef = useRef<HTMLInputElement>(null);

  const srcError = (() => {
    const v = src.trim();
    if (["In Progress", "Upcoming"].includes(status) && !v)
      return 'Needed when the status is "In progress" or "Upcoming" — paste the notice or timetable link so others can check it.';
    if (v && !/^https?:\/\/\S+$/i.test(v)) return "Start the link with https:// (or leave it empty).";
    return "";
  })();

  const save = async () => {
    setErr(null);
    setDateErr("");
    if (srcError) {
      srcRef.current?.focus();
      return;
    }
    const si = dotIso(start);
    const ei = dotIso(end);
    if (si && ei && ei < si) {
      setDateErr("The end date is before the start date.");
      return;
    }
    const payload = {
      status,
      exam_body: examBody.trim() || null,
      endsem_start: dotValue(start) || null,
      endsem_end: dotValue(end) || null,
      mid_window: mid.trim() || null,
      lab_window: lab.trim() || null,
      source_url: src.trim() || null,
      evidence,
      confidence: conf,
      notice_date: dotValue(notice) || null,
      verified_on: verified || today(),
      notes: notes.trim() || null,
    };
    setBusy(true);
    try {
      if (isNew) await portalApi.post("exams", { college_id: c.college_id, semester: r.semester, ...payload }, { idempotencyKey: key });
      else await portalApi.patch(`exams/${r.id}`, payload, { idempotencyKey: key });
    } catch (ex) {
      setErr(errText(ex));
      setBusy(false);
      return;
    }
    setBusy(false);
    toast(`${r.semester} exam details saved for ${c.name}`, "good");
    onClose();
  };

  return (
    <Modal
      open
      wide
      form
      title={isNew ? "Add exam details" : "Edit exam details"}
      onClose={onClose}
      footer={
        <>
          <Button tone="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button tone="primary" busy={busy} onClick={() => void save()}>
            Save
          </Button>
        </>
      }
    >
      <div className="v-adm ex-form">
        <p className="ex-form__who">
          <strong>{c.name}</strong>
          {` · semester ${r.semester} (${r.semester === "4-1" ? "final year" : "third year"})`}
        </p>
        {r.updated_at && !isNew ? (
          <p className="adm-muted ex-meta">{`Last changed ${fmt.date(r.updated_at)} by ${r.updated_by || "unknown"}${r.verified_on ? ` · last checked ${fmt.date(r.verified_on)}` : ""}`}</p>
        ) : null}
        {err ? (
          <div className="td-form__error" role="alert">
            {err}
          </div>
        ) : null}
        <fieldset className="ex-fs">
          <legend>Exam dates</legend>
          <div className="td-form__grid">
            <FieldBox label="Status" htmlFor={id("status")}>
              <Select id={id("status")} options={EXAM_STATUSES} value={status} onChange={setStatus} labels={EXAM_STATUS_LABEL} />
            </FieldBox>
            <FieldBox label="Exams set by" htmlFor={id("body")} help="The university, or the college itself if it is autonomous.">
              <input id={id("body")} type="text" className="td-input" value={examBody} placeholder="e.g. JNTUK, or the college (autonomous)" onChange={(e) => setExamBody(e.target.value)} />
            </FieldBox>
            <FieldBox label="End-semester exams start" htmlFor={id("start")}>
              <DateOrTextInput id={id("start")} value={start} onChange={setStart} />
            </FieldBox>
            <FieldBox label="End-semester exams end" htmlFor={id("end")}>
              <DateOrTextInput id={id("end")} value={end} onChange={setEnd} />
            </FieldBox>
            <div className="td-field__error td-field--full" aria-live="polite">
              {dateErr}
            </div>
            <FieldBox label="Mid exams" htmlFor={id("mid")} full>
              <div>
                <input id={id("mid")} type="text" className="td-input" value={mid} placeholder="e.g. Mid-II 2026-11-09 to 2026-11-14" onChange={(e) => setMid(e.target.value)} />
                <WindowPreview value={mid} counts />
              </div>
            </FieldBox>
            <FieldBox label="Labs / practicals" htmlFor={id("lab")} full>
              <div>
                <input id={id("lab")} type="text" className="td-input" value={lab} placeholder="e.g. Practicals 2026-11-23 to 2026-11-28" onChange={(e) => setLab(e.target.value)} />
                <WindowPreview value={lab} counts={false} />
              </div>
            </FieldBox>
          </div>
        </fieldset>
        <fieldset className="ex-fs">
          <legend>Where did this come from?</legend>
          <div className="td-form__grid">
            <FieldBox label="Source link" htmlFor={id("src")} full>
              <div>
                <input
                  ref={srcRef}
                  id={id("src")}
                  type="url"
                  className="td-input"
                  value={src}
                  placeholder="https://… (exam notice or timetable)"
                  aria-invalid={srcError ? "true" : "false"}
                  onChange={(e) => setSrc(e.target.value)}
                />
                <div className="td-field__error" aria-live="polite">
                  {srcError}
                </div>
              </div>
            </FieldBox>
            <FieldBox label="Kind of source" htmlFor={id("ev")}>
              <Select id={id("ev")} options={EXAM_EVIDENCE} value={evidence} onChange={setEvidence} labels={EVIDENCE_LABEL} />
            </FieldBox>
            <FieldBox label="How sure are we?" htmlFor={id("conf")}>
              <Select id={id("conf")} options={EXAM_CONFIDENCE} value={conf} onChange={setConf} />
            </FieldBox>
            <FieldBox label="Notice published on" htmlFor={id("notice")}>
              <DateOrTextInput id={id("notice")} value={notice} onChange={setNotice} />
            </FieldBox>
            <FieldBox label="Last checked on" htmlFor={id("ver")} help="Defaults to today — the day you looked at the source.">
              <input id={id("ver")} type="date" className="td-input td-num" value={verified} onChange={(e) => setVerified(e.target.value)} />
            </FieldBox>
            <FieldBox label="Notes" htmlFor={id("notes")} full>
              <textarea id={id("notes")} className="td-input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </FieldBox>
          </div>
        </fieldset>
      </div>
    </Modal>
  );
}
