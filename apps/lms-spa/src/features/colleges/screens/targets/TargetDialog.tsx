/**
 * THE "Set target" dialog (old js/views/targets.js openTargetDialog; forms.js targetDialog / setTarget delegate
 * to it): min / target / max + period (programme | month | week) + deadline + notes, Remove target, and the
 * programme-target warning + confirmation. Writes PUT /api/targets (v4) through forms/targets.ts saveTargetRow
 * (POST on older servers). Never derives a target from children (R11).
 *
 *   await openTargetDialog({ scope_type: "person", scope_id: "12", label: "Ravi", period: "programme" });
 *   // or declaratively: <TargetDialog scope_type="college" scope_id="c9" label="KLU" onDone={…} />
 * Needs a <FormsHost/> mounted (forms/host.tsx) for the imperative form.
 */
import "@/features/colleges/styles/views/targets.css";
import { useEffect, useId, useMemo, useRef, useState, type RefObject } from "react";
import { portalApi, type PortalApiError } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { openDialog } from "../../forms";
import { saveTargetRow } from "../../forms/targets";
import { Button, Icon, Kv, Modal, confirm, toast, usePortalUi } from "../../ui";
import { CHILD, STATE_ID, TYPE_LABEL, arr, mondayOf, periodKey, periodLabel, useServerToday } from "./common";

export interface TargetDialogOptions {
  scope_type: string;
  scope_id?: string | number | null;
  label?: string;
  period?: string;
  /** the performance row the dialog was opened from (shows "Confirmed so far") */
  row?: { level?: string; actual?: number | null } | null;
  /** false = the server has no /api/performance (programme target only); undefined = detect */
  v4?: boolean;
  onSaved?: () => void;
}

type TRow = Record<string, unknown> & { id?: number; target?: number; min?: number | null; max?: number | null; target_min?: number | null; target_max?: number | null };

export function openTargetDialog(opts: TargetDialogOptions): Promise<boolean | null> {
  return openDialog<boolean>((done) => <TargetDialog {...opts} onDone={done} />);
}
/** forms.js entry point name. */
export const targetDialog = openTargetDialog;

export function TargetDialog({ onDone, ...opts }: TargetDialogOptions & { onDone: (saved: boolean | null) => void }) {
  const st = opts.scope_type;
  const sid = String(opts.scope_id ?? (st === "state" ? STATE_ID : ""));
  const isProgramme = st === "state";
  const serverToday = useServerToday();
  const today = serverToday || new Date().toISOString().slice(0, 10);
  const existingQ = usePortalQuery<unknown>("targets", { query: { scope: `${st}:${sid}` }, ttl: 0 });
  const health = usePortalQuery<{ version?: string }>(opts.v4 === undefined ? "health" : null, { ttl: 300_000 });
  const existing = useMemo(() => arr<TRow>(existingQ.data).filter((t) => t.course_id == null), [existingQ.data]);
  const v4 = opts.v4 ?? (existing.some((t) => "period" in t || "target_min" in t) || health.data?.version === "v4");
  const { coarse } = usePortalUi();
  const uid = useId();

  const p0 = v4 ? opts.period || "programme" : "programme";
  const [kind, setKind] = useState(String(p0).split(":")[0]!);
  const [month, setMonth] = useState(p0.startsWith("month:") ? p0.slice(6) : today.slice(0, 7));
  const [week, setWeek] = useState(p0.startsWith("week:") ? p0.slice(5) : mondayOf(today));
  const curPeriod = kind === "programme" ? "programme" : kind === "month" ? `month:${month}` : `week:${week ? mondayOf(week) : ""}`;
  const rowFor = (p: string) => existing.find((t) => (t.period ? periodKey(t) === p : p === "programme")) || null;
  const ex = rowFor(curPeriod);

  const [vals, setVals] = useState({ min: "", target: "", max: "", deadline: "", notes: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const targetRef = useRef<HTMLInputElement>(null);
  const minRef = useRef<HTMLInputElement>(null);
  const maxRef = useRef<HTMLInputElement>(null);

  // fill the inputs from the stored row of the chosen period (a late answer never wipes what was typed)
  const dirty = useRef(false);
  const filledFor = useRef<string | null>(null);
  const loaded = existingQ.data !== undefined;
  useEffect(() => {
    const periodChanged = filledFor.current !== null && !filledFor.current.startsWith(`${curPeriod}|`);
    if (!periodChanged && dirty.current) return;
    filledFor.current = `${curPeriod}|${loaded ? "1" : "0"}`;
    const e = rowFor(curPeriod);
    setVals({
      min: String(e?.min ?? e?.target_min ?? ""),
      target: e ? String(e.target ?? "") : "",
      max: String(e?.max ?? e?.target_max ?? ""),
      deadline: String(e?.deadline ?? ""),
      notes: String(e?.notes ?? ""),
    });
    if (periodChanged) dirty.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curPeriod, loaded]);
  useEffect(() => {
    // T17: on touch screens do not pop the keyboard before the user has read the dialog
    if (!coarse) setTimeout(() => targetRef.current?.focus(), 50);
  }, [coarse]);

  const r = opts.row && opts.row.level === st && (opts.period || "programme") === curPeriod ? opts.row : null;
  const read = (v: string) => (v.trim() === "" ? null : Number(v.trim()));
  const okInt = (v: number | null) => v === null || (Number.isInteger(v) && v >= 0 && v <= 1_000_000);

  const save = async () => {
    setFormErr(null);
    setErrs({});
    const mn = v4 ? read(vals.min) : null;
    const t = read(vals.target);
    const mx = v4 ? read(vals.max) : null;
    const bad = (f: "min" | "target" | "max", m: string) => {
      setErrs({ [f]: m });
      ({ min: minRef, target: targetRef, max: maxRef })[f].current?.focus();
    };
    if (t === null) return bad("target", "Enter the target (0 or more).");
    if (!okInt(t)) return bad("target", "Enter a whole number, 0 or more.");
    if (!okInt(mn)) return bad("min", "Enter a whole number, 0 or more, or leave it empty.");
    if (!okInt(mx)) return bad("max", "Enter a whole number, 0 or more, or leave it empty.");
    if (mn !== null && mn > t) return bad("min", "The minimum cannot be more than the target.");
    if (mx !== null && mx < t) return bad("max", "The maximum must be at least the target.");
    if (kind === "month" && !/^\d{4}-\d{2}$/.test(month)) return setFormErr("Choose a month.");
    if (kind === "week" && !week) return setFormErr("Choose a day in the week.");
    if (isProgramme) {
      const exP = rowFor("programme");
      const okGo = await confirm({
        title: "Change the programme target?",
        text: `The programme target changes from ${exP ? fmt.num(exP.target) : "none"} to ${fmt.num(t)}. Every page, pace and planner uses this number.`,
        confirmLabel: `Set to ${fmt.num(t)}`,
        tone: "primary",
      });
      if (!okGo) return;
    }
    setBusy(true);
    try {
      const base = { scope_type: st, scope_id: sid, course_id: null, target: t, deadline: kind === "programme" ? vals.deadline || null : null, notes: vals.notes.trim() || null };
      if (v4) await saveTargetRow({ ...base, period: curPeriod, min: mn, max: mx, confirm_programme: isProgramme || undefined });
      else await portalApi.post("targets", base);
    } catch (e) {
      const pe = e as PortalApiError;
      const f = pe.fields || {};
      const shown: Record<string, string> = {};
      for (const [k, m] of Object.entries(f)) {
        const key = k === "target_min" ? "min" : k === "target_max" ? "max" : k;
        if (key === "min" || key === "target" || key === "max") shown[key] = m;
      }
      setErrs(shown);
      setFormErr(`${pe.message}${Object.keys(shown).length ? "" : Object.entries(f).map(([k, m]) => ` — ${k}: ${m}`).join("")}`);
      setBusy(false);
      return;
    }
    toast(`${opts.label || "Target"}: ${periodLabel(curPeriod)} target ${fmt.num(t)}`, "good");
    opts.onSaved?.();
    onDone(true);
  };

  const remove = async () => {
    const e = rowFor(curPeriod);
    if (!e) return toast("There is no target for this period to remove.", "warn");
    if (isProgramme && curPeriod === "programme") return toast("The programme target cannot be removed — change it instead.", "warn");
    setBusy(true);
    try {
      await portalApi.del(`targets/${e.id}`);
    } catch (err) {
      toast((err as Error).message, "bad");
      setBusy(false);
      return;
    }
    toast(`${opts.label || "Target"}: ${periodLabel(curPeriod)} target removed`, "good");
    opts.onSaved?.();
    onDone(true);
  };

  const num = (name: "min" | "target" | "max", label: string, help: string, ref: RefObject<HTMLInputElement | null>) => (
    <div className="td-field" data-field={name}>
      <label className="td-field__label" htmlFor={`${uid}-${name}`}>
        {label}
      </label>
      <input
        ref={ref}
        type="number"
        min={0}
        step={1}
        inputMode="numeric"
        className="td-input td-num"
        id={`${uid}-${name}`}
        name={name}
        value={vals[name]}
        aria-invalid={errs[name] ? true : undefined}
        onChange={(e) => {
          dirty.current = true;
          setVals((v) => ({ ...v, [name]: e.target.value }));
        }}
      />
      <div className="td-field__help">{help}</div>
      <div className="td-field__error" aria-live="polite">
        {errs[name] ?? ""}
      </div>
    </div>
  );
  const showRemove = existing.length > 0 && !(isProgramme && !v4);

  return (
    <Modal
      open
      form
      title={`Target — ${opts.label || TYPE_LABEL[st] || st}`}
      onClose={() => onDone(null)}
      footer={
        <>
          {showRemove ? (
            <Button tone="danger" disabled={busy} onClick={() => void remove()}>
              Remove target
            </Button>
          ) : null}
          <Button tone="ghost" onClick={() => onDone(null)}>
            Cancel
          </Button>
          <Button tone="primary" busy={busy} onClick={() => void save()}>
            Save target
          </Button>
        </>
      }
    >
      <form
        className="tgd"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        {isProgramme ? (
          <div className="tgp-note is-warn" role="note">
            <Icon name="warn" size={16} />
            <span>
              <strong>This is the programme target. </strong>
              It is the goal everyone works towards (400 confirmed enrollments by the programme deadline unless changed here). It is never replaced by the sum of district or college targets.
            </span>
          </div>
        ) : null}
        <div className="tgd-facts">
          <Kv
            pairs={[
              ["Period", periodLabel(curPeriod)],
              ["Current target", ex ? `${ex.min ?? ex.target_min ?? "—"} · ${fmt.num(ex.target)} · ${ex.max ?? ex.target_max ?? "—"} (min · target · max)` : existingQ.loading ? "Loading…" : "none for this period"],
              r ? ["Confirmed so far", fmt.num(r.actual ?? 0)] : null,
              ex ? ["Last set", `${fmt.date(String(ex.updated_at ?? ""))} by ${ex.updated_by || "unknown"}`] : null,
            ]}
          />
        </div>
        {v4 ? (
          <div className="td-field">
            <label className="td-field__label" htmlFor={`${uid}-period`}>
              Period
            </label>
            <div className="tgd-period">
              <select className="td-input td-select" id={`${uid}-period`} value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="programme">Whole programme</option>
                <option value="month">A month</option>
                <option value="week">A week (Mon–Sun)</option>
              </select>
              <input type="month" className="td-input td-num" aria-label="Month" hidden={kind !== "month"} value={month} onChange={(e) => setMonth(e.target.value)} />
              <input type="date" className="td-input td-num" aria-label="Any day in the week" hidden={kind !== "week"} value={week} onChange={(e) => setWeek(e.target.value)} />
            </div>
            <span className="td-field__help" hidden={kind !== "week"}>
              {week ? periodLabel(`week:${mondayOf(week)}`) : ""}
            </span>
          </div>
        ) : null}
        <div className={`tgd-grid${v4 ? "" : " is-single"}`}>
          {v4 ? num("min", "Minimum (optional)", "The least that is acceptable.", minRef) : null}
          {num("target", "Target", "Required. Whole number, 0 or more.", targetRef)}
          {v4 ? num("max", "Stretch / maximum (optional)", "Must be at least the target.", maxRef) : null}
        </div>
        {!v4 ? <p className="tgp-muted tgp-small">Minimum / maximum and month or week targets need the server update; only the programme target can be set on this server.</p> : null}
        <div className="td-field" hidden={kind !== "programme"}>
          <label className="td-field__label" htmlFor={`${uid}-deadline`}>
            Deadline (optional)
          </label>
          <input type="date" className="td-input td-num" id={`${uid}-deadline`} value={vals.deadline} onChange={(e) => {
              dirty.current = true;
              setVals((v) => ({ ...v, deadline: e.target.value }));
            }} />
          <div className="td-field__help">Empty = the deadline of the place above, or the programme deadline.</div>
        </div>
        <div className="td-field">
          <label className="td-field__label" htmlFor={`${uid}-notes`}>
            Notes (optional)
          </label>
          <textarea className="td-input" id={`${uid}-notes`} rows={2} maxLength={500} value={vals.notes} onChange={(e) => {
              dirty.current = true;
              setVals((v) => ({ ...v, notes: e.target.value }));
            }} />
        </div>
        {st !== "person" && st !== "branch" ? <p className="tgp-muted tgp-small">This does not change the targets of its {CHILD[st] || "parts"}.</p> : null}
        {formErr ? (
          <div className="td-form__error" role="alert">
            {formErr}
          </div>
        ) : null}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
    </Modal>
  );
}
