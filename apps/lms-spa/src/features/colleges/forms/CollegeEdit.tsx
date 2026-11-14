/**
 * Quick college edit (old forms.editCollege: contact details, operating status with evidence, targeted, notes).
 * The full college form is college-form.js (the College screen's own port), not this one.
 *
 *   await editCollege("c9")   // or editCollege(collegeRow)
 */
import { useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import type { College, CollegeDetail } from "../lib/types";
import { toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { CheckField, DialogForm, SelectField, TextAreaField, TextField } from "./kit";
import { OP_OPTS } from "./labels";
import { LoadingModal } from "./loading";
import { EMAIL_RE, str, validationError } from "./util";

const YNU = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "unknown", label: "Unknown" },
];
const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export function EditCollegeDialog({ open = true, collegeId, onSaved, onDone }: { open?: boolean; collegeId: string; onSaved?: (c: College) => void; onDone: (r: College | null) => void }) {
  const { data, error, loading, reload } = usePortalQuery<CollegeDetail>(`colleges/${encodeURIComponent(collegeId)}`);
  if (!data) return <LoadingModal open={open} title="Edit college" error={error} loading={loading} retry={() => void reload()} onClose={() => onDone(null)} />;
  return <EditCollegeForm open={open} c={data.college} onSaved={onSaved} onDone={onDone} />;
}

function EditCollegeForm({ open, c, onSaved, onDone }: { open: boolean; c: College; onSaved?: (c: College) => void; onDone: (r: College | null) => void }) {
  const x = c as College & Record<string, unknown>;
  const [v, setV] = useState({
    phone: s(c.phone),
    email: s(c.email),
    website: s(c.website),
    contact_source: s(x.contact_source),
    address: s(c.address),
    op_status: s(c.op_status) || "pending",
    op_2025_26: s(x.op_2025_26) || "unknown",
    op_2026_27: s(x.op_2026_27) || "unknown",
    op_status_note: s(c.op_status_note),
    op_status_source: s(x.op_status_source),
    notes: s(c.notes),
  });
  const [targeted, setTargeted] = useState(!!c.targeted);
  const set = (k: keyof typeof v) => (val: string) => setV((p) => ({ ...p, [k]: val }));
  return (
    <DialogForm<College>
      open={open}
      title={`Edit college — ${c.short_name || c.name}`}
      submitLabel="Save college"
      onDone={onDone}
      onSubmit={async (key) => {
        const errs: Record<string, string> = {};
        if (v.phone && !/^[+\d][\d\s-]{6,}$/.test(v.phone.trim())) errs.phone = "Enter a valid phone number.";
        if (v.email && !EMAIL_RE.test(v.email.trim())) errs.email = "Enter a valid email address.";
        if (v.op_status !== (c.op_status || "pending") && !str(v.op_status_note)) errs.op_status_note = "Add the evidence for the new status.";
        if (Object.keys(errs).length) throw validationError(errs);
        const r = await portalApi.patch<College>(
          `colleges/${encodeURIComponent(c.id)}`,
          {
            phone: str(v.phone),
            email: str(v.email),
            website: str(v.website),
            contact_source: str(v.contact_source),
            address: str(v.address),
            op_status: v.op_status,
            op_2025_26: v.op_2025_26,
            op_2026_27: v.op_2026_27,
            op_status_note: str(v.op_status_note),
            op_status_source: str(v.op_status_source),
            targeted: targeted ? 1 : 0,
            notes: str(v.notes),
          },
          { idempotencyKey: key },
        );
        toast("College updated", "good");
        onSaved?.(r);
        return r ?? (true as unknown as College);
      }}
    >
      {(err) => (
        <>
          <TextField name="phone" label="Phone" type="tel" value={v.phone} onChange={set("phone")} error={err.phone} />
          <TextField name="email" label="Email" type="email" value={v.email} onChange={set("email")} error={err.email} />
          <TextField name="website" label="Website" value={v.website} onChange={set("website")} error={err.website} />
          <TextField name="contact_source" label="Contact source" value={v.contact_source} onChange={set("contact_source")} help="Where the contact details came from (URL or note)." error={err.contact_source} />
          <TextAreaField name="address" label="Address" value={v.address} onChange={set("address")} error={err.address} />
          <SelectField name="op_status" label="Operating status" options={OP_OPTS} value={v.op_status} onChange={set("op_status")} error={err.op_status} />
          <SelectField name="op_2025_26" label="Admitted students 2025-26?" options={YNU} value={v.op_2025_26} onChange={set("op_2025_26")} error={err.op_2025_26} />
          <SelectField name="op_2026_27" label="Admitted students 2026-27?" options={YNU} value={v.op_2026_27} onChange={set("op_2026_27")} error={err.op_2026_27} />
          <TextAreaField name="op_status_note" label="Evidence for status" value={v.op_status_note} onChange={set("op_status_note")} help="Required when changing the status." error={err.op_status_note} />
          <TextField name="op_status_source" label="Evidence source (URL)" value={v.op_status_source} onChange={set("op_status_source")} error={err.op_status_source} />
          <CheckField name="targeted" label="Targeted by Tech Drona (include in plans and targets)" full checked={targeted} onChange={setTargeted} />
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Old API: forms.editCollege(ctx, c | id). */
export function editCollege(c: string | { id: string }, opts: { onSaved?: (c: College) => void } = {}): Promise<College | null> {
  const id = typeof c === "object" && c ? c.id : c;
  return openDialog<College>((done) => <EditCollegeDialog collegeId={id} onSaved={opts.onSaved} onDone={done} />);
}
