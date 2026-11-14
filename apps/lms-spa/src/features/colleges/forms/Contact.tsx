/**
 * College contact add / edit (old forms.addContact / forms.editContact). Edit adds the number status and a
 * "Delete contact" (only for a contact added by mistake; the server refuses one with logged calls).
 *
 *   await addContact({ college_id: "c9", onSaved })
 *   await editContact(contact, { onSaved })
 */
import "../styles/views/ops.css";
import { useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import type { CollegeDetail, Contact } from "../lib/types";
import { Button } from "../ui/Button";
import { ErrorCard, Skeleton } from "../ui/Feedback";
import { Modal, confirm, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, SelectField, TextAreaField, TextField } from "./kit";
import { CONTACT_ROLE_LABEL, CONTACT_STATUS, contactLabel, formatPhone } from "./labels";
import { EMAIL_RE, branchOpts, errMsg, num, str, validationError } from "./util";

export interface ContactOptions {
  college_id: string;
  onSaved?: (contact: Contact) => void;
}

const ROLE_OPTIONS = Object.entries(CONTACT_ROLE_LABEL).map(([value, label]) => ({ value, label }));
const BASIS_OPTIONS = [
  { value: "verified", label: "Verified — official site or confirmed by the college" },
  { value: "pending", label: "Not verified yet (listing, aggregator, word of mouth)" },
];
const STATUS_OPTIONS = Object.entries(CONTACT_STATUS).map(([value, [label]]) => ({ value, label }));

type Vals = { role: string; name: string; phone: string; email: string; basis: string; source_url: string; branch_id: string; status: string; notes: string };

function valsOf(k: Partial<Contact>): Vals {
  const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  return {
    role: k.role || "tpo",
    name: s(k.name),
    phone: k.phone ? formatPhone(k.phone) : "",
    email: s(k.email),
    basis: k.basis || "pending",
    source_url: s(k.source_url),
    branch_id: k.branch_id ? String(k.branch_id) : "",
    status: k.status || "untested",
    notes: s(k.notes),
  };
}

/** Request body (old contactBody). */
export function contactBody(v: Vals, { collegeId, withBranch, withStatus }: { collegeId?: string; withBranch: boolean; withStatus: boolean }): Record<string, unknown> {
  const b: Record<string, unknown> = { role: v.role, name: str(v.name), phone: str(v.phone), email: str(v.email), basis: v.basis, source_url: str(v.source_url), notes: str(v.notes) };
  if (collegeId) b.college_id = collegeId;
  if (withBranch) b.branch_id = num(v.branch_id);
  if (withStatus && v.status) b.status = v.status;
  return b;
}

/** Field checks (old checkContactVals): a phone or an email; a valid email. */
export function checkContact(v: { phone?: string | null; email?: string | null }): void {
  const f: Record<string, string> = {};
  if (!str(v.phone) && !str(v.email)) f.phone = "Add a phone number or an email.";
  if (v.email && !EMAIL_RE.test(String(v.email).trim())) f.email = "Enter a valid email address.";
  if (Object.keys(f).length) throw validationError(f);
}

export function ContactDialog({ open = true, collegeId, contact, onSaved, onDone }: { open?: boolean; collegeId: string; contact?: Contact | null; onSaved?: (c: Contact) => void; onDone: (r: Contact | null) => void }) {
  const { data, error, loading, reload } = usePortalQuery<CollegeDetail>(`colleges/${encodeURIComponent(collegeId)}`);
  const edit = !!contact;
  const cname = data?.college?.short_name || data?.college?.name || collegeId;
  const title = edit ? `Edit contact — ${contactLabel(contact) || formatPhone(contact?.phone)}` : `Add contact — ${cname}`;
  if (!data) {
    return (
      <Modal open={open} title={title} onClose={() => onDone(null)}>
        {loading ? <Skeleton lines={4} card={false} /> : <ErrorCard title="Could not load the college" error={error} retry={() => void reload()} />}
      </Modal>
    );
  }
  return <ContactForm open={open} collegeId={collegeId} contact={contact ?? null} branches={data.branches ?? []} title={title} onSaved={onSaved} onDone={onDone} />;
}

function ContactForm({
  open,
  collegeId,
  contact,
  branches,
  title,
  onSaved,
  onDone,
}: {
  open: boolean;
  collegeId: string;
  contact: Contact | null;
  branches: CollegeDetail["branches"];
  title: string;
  onSaved?: (c: Contact) => void;
  onDone: (r: Contact | null) => void;
}) {
  const edit = !!contact;
  const [v, setV] = useState<Vals>(() => valsOf(contact ?? {}));
  const set = (k: keyof Vals) => (x: string) => setV((p) => ({ ...p, [k]: x }));
  const [deleting, setDeleting] = useState(false);

  const del = async () => {
    if (!contact) return;
    const ok = await confirm({
      title: "Delete this contact?",
      text: "Only for a contact added by mistake. A contact with logged calls cannot be deleted. Set its number status to “Wrong number” or “Not working” instead.",
      confirmLabel: "Delete",
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await portalApi.del(`contacts/${contact.id}`);
      toast("Contact deleted", "good");
      onDone(null);
    } catch (e) {
      toast(errMsg(e), "bad");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <DialogForm<Contact>
      open={open}
      title={title}
      submitLabel={edit ? "Save contact" : "Add contact"}
      extra={
        edit ? (
          <div className="vx-danger-zone">
            <Button tone="ghost" size="sm" icon="trash" busy={deleting} onClick={() => void del()}>
              Delete contact
            </Button>
          </div>
        ) : null
      }
      onDone={onDone}
      onSubmit={async (key) => {
        checkContact(v);
        const body = contactBody(v, { collegeId: edit ? undefined : collegeId, withBranch: branches.length > 0, withStatus: edit });
        const r = edit ? await portalApi.patch<Contact>(`contacts/${contact!.id}`, body, { idempotencyKey: key }) : await portalApi.post<Contact>("contacts", body, { idempotencyKey: key });
        toast(edit ? "Contact saved" : "Contact added", "good");
        onSaved?.(r);
        return r ?? (true as unknown as Contact);
      }}
    >
      {(err) => (
        <>
          <SelectField name="role" label="Role" required options={ROLE_OPTIONS} value={v.role} onChange={set("role")} error={err.role} />
          <TextField name="name" label="Name" value={v.name} onChange={set("name")} placeholder="Optional, e.g. Dr. K. Rao" error={err.name} />
          <TextField
            name="phone"
            label="Phone"
            type="tel"
            value={v.phone}
            onChange={set("phone")}
            placeholder="98765 43210 or 0863 2344700"
            help="Saved as +91 and a 10-digit number. The same number cannot be added twice for one college."
            error={err.phone}
          />
          <TextField name="email" label="Email" type="email" value={v.email} onChange={set("email")} error={err.email} />
          <SelectField name="basis" label="Is it verified?" required options={BASIS_OPTIONS} value={v.basis} onChange={set("basis")} error={err.basis} />
          <TextField name="source_url" label="Where it was found (link)" type="url" value={v.source_url} onChange={set("source_url")} placeholder="https://…" help="Optional. The page that lists this number or email." error={err.source_url} />
          {branches.length ? (
            <SelectField name="branch_id" label="Branch (for a head of department)" placeholder="— Whole college —" options={branchOpts(branches)} value={v.branch_id} onChange={set("branch_id")} error={err.branch_id} />
          ) : null}
          {edit ? (
            <SelectField
              name="status"
              label="Number status"
              required
              options={STATUS_OPTIONS}
              value={v.status}
              onChange={set("status")}
              help="Set automatically from logged calls. Change it only if you know better; your choice then stays until you change it again."
              error={err.status}
            />
          ) : null}
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Old API: forms.addContact(ctx, {college_id, onSaved}). */
export function addContact(opts: ContactOptions): Promise<Contact | null> {
  return openDialog<Contact>((done) => <ContactDialog collegeId={opts.college_id} onSaved={opts.onSaved} onDone={done} />);
}

/** Old API: forms.editContact(ctx, contact, {onSaved}). */
export function editContact(contact: Contact, opts: { onSaved?: (c: Contact) => void } = {}): Promise<Contact | null> {
  return openDialog<Contact>((done) => <ContactDialog collegeId={contact.college_id} contact={contact} onSaved={opts.onSaved} onDone={done} />);
}
