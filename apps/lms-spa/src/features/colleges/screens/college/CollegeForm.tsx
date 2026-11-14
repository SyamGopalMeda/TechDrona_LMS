/**
 * Create / edit a college (port of js/views/college-form.js): one dialog for both, with a per-field source +
 * verification block and a live duplicate warning; plus the "Mark verified / unverified" flow of the college page.
 *
 *   POST  colleges {name, district_id, city_id | city_name, …, sources?}   (409 duplicate_college)
 *   PATCH colleges/:id {changed fields…, sources:{field: source}}          a changed field WITHOUT a source becomes unverified
 *   POST  colleges/:id/verify {fields, source, note?, verified?}           stamp (or clear) verification
 *
 *   <CollegeFormDialog open collegeId={null} defaults={{ district_id }} onDone={(saved) => …} />
 *   await editCollegeFull("c9")    // imperative (needs a <FormsHost/>)
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { isPortalApiError, portalApi } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { portalPath } from "../../lib/routes";
import type { College, CollegeDetail, CollegeRow, PortalMeta } from "../../lib/types";
import { Icon, VerifiedBadge, confirm, toast } from "../../ui";
import { openDialog } from "../../forms/host";
import { CheckField, DialogForm, KEEP_OPEN, SelectField, TextAreaField, TextField, type Opt } from "../../forms/kit";
import { normAnyPhone } from "../../forms/labels";
import { LoadingModal } from "../../forms/loading";
import { validationError } from "../../forms/util";

const OP: Opt[] = [
  { value: "operational", label: "Operational" },
  { value: "possibly_closed", label: "Possibly closed" },
  { value: "closed", label: "Closed" },
  { value: "pending", label: "Not checked yet" },
];
const YNU: Opt[] = [
  { value: "unknown", label: "Unknown" },
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];
const AUTONOMY: Opt[] = [
  { value: "", label: "Not known" },
  { value: "Yes", label: "Autonomous (sets its own exams)" },
  { value: "No", label: "Not autonomous" },
  { value: "Unclear", label: "Unclear" },
];
const TIERS: Opt[] = [
  { value: "", label: "Not known" },
  { value: "Tier 1", label: "Tier 1 (strongest)" },
  { value: "Tier 2", label: "Tier 2" },
  { value: "Tier 3", label: "Tier 3" },
];
const OWNERSHIP_HINTS = ["Pvt autonomous", "Pvt affiliated", "State pvt univ", "Deemed (pvt)", "Govt – State univ/constituent", "Govt – National", "Private self-financing"];

/** Fields whose provenance is tracked (server field_status keys). */
export const VERIFY_FIELDS: readonly (readonly [string, string])[] = [
  ["name", "Official name"],
  ["district_id", "District"],
  ["city_id", "City / town"],
  ["phone", "Office phone"],
  ["email", "Office email"],
  ["website", "Website"],
  ["ownership", "Type of institution"],
  ["affiliation", "Affiliated university"],
  ["op_status", "Operating status"],
];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const str = (v: unknown): string | null => {
  const s = v === undefined || v === null ? "" : String(v).trim();
  return s || null;
};
const sv = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
const norm = (s: unknown) =>
  String(s || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/** "0863-2399999 / 98765 43210" → null when every number is a valid Indian number, else a message. */
export function phoneError(v: string | null): string | null {
  if (!v) return null;
  const parts = String(v)
    .split(/[/,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  for (const p of parts) {
    const main = p.split(/\s*(?:ext|x)\.?\s*\d*$/i)[0] ?? "";
    if (/[a-wyz]/i.test(main.replace(/ext/i, ""))) return "Use digits only (several numbers can be separated by / or ,).";
    if (!normAnyPhone(main)) return `“${p}” is not a 10-digit Indian number (mobile, or STD code + landline).`;
  }
  return null;
}
/** Source: an http(s) link or a plain note; other schemes (javascript:, data:…) are refused, as on the server. */
export function sourceError(v: string | null): string | null {
  if (!v) return null;
  if (/^[a-z][a-z0-9+.-]*:/i.test(v) && !/^https?:\/\//i.test(v)) return "Use an http(s) link or a plain note.";
  return null;
}
function urlError(v: string | null): string | null {
  if (!v) return null;
  return /^https?:\/\/[^\s]+\.[^\s]+/i.test(v) ? null : "Enter a full link starting with http:// or https://";
}

export interface Verification {
  state: "verified" | "unverified" | "missing" | string;
  source: string | null;
  date: string | null;
  by: string | null;
}
/** A college's verification entry → {state, source, date, by}. */
export function fieldVerification(c: Partial<College> | null | undefined, field: string): Verification {
  const vf = (c?.verified_fields && typeof c.verified_fields === "object" ? c.verified_fields : {}) as Record<string, { source?: string; verified_on?: string; verified_by?: string } | undefined>;
  const fs = c?.field_status ? c.field_status[field] : null;
  const e = vf[field];
  if (e && (e.verified_on || e.source)) return { state: "verified", source: e.source ?? null, date: e.verified_on ?? null, by: e.verified_by ?? null };
  if (fs) return { state: fs, source: null, date: null, by: null };
  const v = c ? (c as Record<string, unknown>)[field] : null;
  return { state: v === null || v === undefined || v === "" ? "missing" : "unverified", source: null, date: null, by: null };
}
export function FieldVerificationBadge({ c, field }: { c: Partial<College>; field: string }) {
  return <VerifiedBadge {...fieldVerification(c, field)} />;
}
/** true when the server tracks per-field verification (v4). */
export const tracksVerification = (c: object | null | undefined): boolean => !!c && ("verified_fields" in c || "field_status" in c);

/* ------------------------------------------------------------------ the dialog */

export interface CollegeFormProps {
  open: boolean;
  /** null / undefined = add a college */
  collegeId?: string | null;
  defaults?: { district_id?: string; city_id?: string };
  onDone: (saved: { id: string } | null) => void;
}

export function CollegeFormDialog({ open, collegeId, defaults, onDone }: CollegeFormProps) {
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const det = usePortalQuery<CollegeDetail>(open && collegeId ? `colleges/${encodeURIComponent(collegeId)}` : null);
  if (!open) return null;
  const waiting = (collegeId && !det.data) || (!meta.data && !meta.error);
  if (waiting)
    return (
      <LoadingModal
        open
        title={collegeId ? "Edit college" : "Add a college"}
        error={det.error}
        loading={det.loading || meta.loading}
        retry={() => void det.reload()}
        onClose={() => onDone(null)}
      />
    );
  return <CollegeFormBody c={collegeId ? (det.data?.college ?? null) : null} meta={meta.data ?? null} defaults={defaults} onDone={onDone} />;
}

function initial(c: College | null, defaults: CollegeFormProps["defaults"]) {
  const v0 = (c ?? {}) as Record<string, unknown>;
  const isNew = !c;
  return {
    name: sv(v0.name),
    short_name: sv(v0.short_name),
    aliases: Array.isArray(v0.aliases) ? (v0.aliases as string[]).join(", ") : "",
    district_id: sv(v0.district_id ?? defaults?.district_id),
    city_id: sv(v0.city_id ?? defaults?.city_id),
    city_name: "",
    address: sv(v0.address),
    phone: sv(v0.phone),
    email: sv(v0.email),
    website: sv(v0.website),
    ownership: sv(v0.ownership),
    affiliation: sv(v0.affiliation),
    autonomous: sv(v0.autonomous),
    tier: sv(v0.tier),
    naac: sv(v0.naac),
    op_status: sv(v0.op_status) || (isNew ? "operational" : "pending"),
    op_2025_26: sv(v0.op_2025_26) || "unknown",
    op_2026_27: sv(v0.op_2026_27) || "unknown",
    op_status_note: sv(v0.op_status_note),
    op_status_source: sv(v0.op_status_source),
    notes: sv(v0.notes),
  };
}
type Vals = ReturnType<typeof initial>;

function CollegeFormBody({ c, meta, defaults, onDone }: { c: College | null; meta: PortalMeta | null; defaults: CollegeFormProps["defaults"]; onDone: CollegeFormProps["onDone"] }) {
  const isNew = !c;
  const track = isNew ? true : tracksVerification(c);
  const [v, setV] = useState<Vals>(() => initial(c, defaults));
  const [targeted, setTargeted] = useState<boolean>(isNew ? true : !!c?.targeted);
  const [src, setSrc] = useState<Record<string, string>>({});
  const [dup, setDup] = useState<{ same: boolean; rows: CollegeRow[] } | null>(null);
  const [existing, setExisting] = useState<{ id: string; message: string } | null>(null);
  const set = (k: keyof Vals) => (val: string) => setV((o) => ({ ...o, [k]: val }));

  const districts = useMemo(() => [...(meta?.districts ?? [])].sort((a, b) => String(a.name).localeCompare(String(b.name))), [meta]);
  const cities = useMemo(
    () => (meta?.cities ?? []).filter((x) => x.district_id === v.district_id).sort((a, b) => String(a.name).localeCompare(String(b.name))),
    [meta, v.district_id],
  );
  // keep the chosen city only while it belongs to the district
  const cityValue = v.city_id === "__new" || cities.some((x) => x.id === v.city_id) ? v.city_id : "";
  const dName = (did: string) => meta?.districts.find((d) => d.id === did)?.name ?? did;

  // live duplicate warning while typing the name
  const dupSeq = useRef(0);
  useEffect(() => {
    const q = str(v.name);
    const my = ++dupSeq.current;
    if (!q || q.length < 4 || (!isNew && norm(q) === norm(c?.name))) {
      setDup(null);
      return;
    }
    const t = setTimeout(() => {
      portalApi
        .get<CollegeRow[] | { items?: CollegeRow[] }>("colleges", { query: { q, districts: "all" } })
        .then((res) => {
          if (my !== dupSeq.current) return;
          const rows = (Array.isArray(res) ? res : (res.items ?? [])).filter((r) => !c || r.id !== c.id);
          const same = rows.filter((r) => norm(r.name) === norm(q) || norm(r.short_name) === norm(q));
          const show = (same.length ? same : rows).slice(0, 4);
          setDup(show.length ? { same: !!same.length, rows: show } : null);
        })
        .catch(() => undefined); // advisory
    }, 350);
    return () => clearTimeout(t);
  }, [v.name, isNew, c]);

  const read = () => {
    const email = str(v.email);
    const o: Record<string, unknown> = {
      name: str(v.name),
      short_name: str(v.short_name),
      aliases: (str(v.aliases) || "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      district_id: str(v.district_id),
      city_id: cityValue && cityValue !== "__new" ? cityValue : null,
      city_name: cityValue === "__new" ? str(v.city_name) : null,
      address: str(v.address),
      phone: str(v.phone),
      email: email ? email.toLowerCase() : null,
      website: str(v.website),
      ownership: str(v.ownership),
      affiliation: str(v.affiliation),
      autonomous: str(v.autonomous),
      tier: str(v.tier),
      naac: str(v.naac),
      op_status: v.op_status,
      op_2025_26: v.op_2025_26,
      op_2026_27: v.op_2026_27,
      op_status_note: str(v.op_status_note),
      op_status_source: str(v.op_status_source),
      targeted: targeted ? 1 : 0,
      notes: str(v.notes),
    };
    const sources: Record<string, string> = {};
    for (const [f] of VERIFY_FIELDS) {
      const s = str(src[f]);
      if (s) sources[f] = s;
    }
    return { o, sources };
  };

  const validate = (o: Record<string, unknown>, sources: Record<string, string>) => {
    const e: Record<string, string> = {};
    if (!o.name) e.name = "Required";
    if (!o.district_id) e.district_id = "Choose the district";
    if (!o.city_id && !o.city_name) e.city_id = cityValue === "__new" ? "Type the town name" : "Choose the city or town";
    if (cityValue === "__new" && !o.city_name) e.city_name = "Type the town name";
    const pe = phoneError(o.phone as string | null);
    if (pe) e.phone = pe;
    if (o.email && !EMAIL_RE.test(String(o.email))) e.email = "Enter a valid email address";
    const we = urlError(o.website as string | null);
    if (we) e.website = we;
    const s0 = o.op_status_source as string | null;
    const se = sourceError(s0) || (s0 && urlError(s0));
    if (se) e.op_status_source = se;
    if (!isNew && o.op_status !== (c?.op_status || "pending") && !o.op_status_note) e.op_status_note = "Add the evidence for the new status";
    for (const [f, s] of Object.entries(sources)) {
      const m = sourceError(s);
      if (m) e[`src_${f}`] = m;
    }
    return e;
  };

  /** changed fields only (edit): the server stamps / clears verification per changed field */
  const diff = (o: Record<string, unknown>): Record<string, unknown> => {
    if (!c) return o;
    const cur = c as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    for (const [k, val] of Object.entries(o)) {
      if (k === "city_name") {
        if (val) out.city_name = val;
        continue;
      }
      if (k === "aliases") {
        if (!same(val, Array.isArray(c.aliases) ? c.aliases : [])) out.aliases = val;
        continue;
      }
      if (k === "targeted") {
        if (Number(val) !== Number(c.targeted ? 1 : 0)) out.targeted = val;
        continue;
      }
      if (k === "op_2025_26" || k === "op_2026_27") {
        if ((val || "unknown") !== (cur[k] || "unknown")) out[k] = val;
        continue;
      }
      if (!same(val, cur[k] === "" ? null : cur[k])) out[k] = val;
    }
    return out;
  };

  const submit = async (idempotencyKey: string): Promise<{ id: string } | typeof KEEP_OPEN> => {
    setExisting(null);
    const { o, sources } = read();
    const errs = validate(o, sources);
    if (Object.keys(errs).length) throw validationError(errs);
    try {
      if (isNew) {
        const body: Record<string, unknown> = { ...o };
        if (!body.city_name) delete body.city_name;
        else delete body.city_id;
        if (!(body.aliases as string[]).length) delete body.aliases;
        if (Object.keys(sources).length) body.sources = sources;
        const saved = await portalApi.post<{ id?: string; college?: { id?: string } }>("colleges", body, { idempotencyKey });
        const nid = saved?.id ?? saved?.college?.id ?? "";
        toast(`${String(body.short_name || body.name)} added`, "good");
        return { id: String(nid) };
      }
      const changes = diff(o);
      // changed fields carry their source in the PATCH; unchanged fields with a new source are stamped via /verify
      const patchSources: Record<string, string> = {};
      const verifyOnly: Record<string, string> = {};
      for (const [f, s] of Object.entries(sources)) {
        const changed = f in changes || (f === "city_id" && "city_name" in changes);
        (changed ? patchSources : verifyOnly)[f] = s;
      }
      let did = false;
      const id = encodeURIComponent(c!.id);
      if (Object.keys(changes).length) {
        if (Object.keys(patchSources).length) changes.sources = patchSources;
        await portalApi.patch(`colleges/${id}`, changes, { idempotencyKey });
        did = true;
      }
      const bySource = new Map<string, string[]>();
      for (const [f, s] of Object.entries(verifyOnly)) bySource.set(s, [...(bySource.get(s) ?? []), f]);
      for (const [s, fields] of bySource) {
        await portalApi.post(`colleges/${id}/verify`, { fields, source: s });
        did = true;
      }
      toast(did ? `${c!.short_name || c!.name} updated` : "Nothing changed", did ? "good" : "info");
      return { id: c!.id };
    } catch (e) {
      const d = isPortalApiError(e) ? (e.data ?? {}) : {};
      if (isPortalApiError(e) && e.status === 409 && (d.code === "duplicate_college" || d.existing_id)) {
        if (d.existing_id) setExisting({ id: String(d.existing_id), message: e.message || "This college already exists." });
        throw validationError({ name: "Already in the portal" });
      }
      throw e;
    }
  };

  const vrow = ([f, label]: readonly [string, string]) => {
    const cur = c ? fieldVerification(c, f) : null;
    return (
      <div className="vcf-vrow" key={f} data-field={`src_${f}`}>
        <div className="vcf-vlabel">
          <strong>{label}</strong>
          {c && track ? <FieldVerificationBadge c={c} field={f} /> : null}
          {cur?.state === "verified" && cur.source ? (
            <span className="vx-muted vx-small vcf-vsrc" title={cur.source}>
              {cur.source.replace(/^https?:\/\//, "").slice(0, 48)}
            </span>
          ) : null}
        </div>
        <div className="vcf-vin">
          <input
            type="text"
            className="td-input"
            autoComplete="off"
            value={src[f] ?? ""}
            placeholder="Link (https://…) or note, e.g. “AICTE approval 2025-26”"
            aria-label={`Source for ${label}`}
            onChange={(e) => setSrc((o) => ({ ...o, [f]: e.target.value }))}
          />
        </div>
      </div>
    );
  };

  return (
    <DialogForm<{ id: string }>
      open
      wide
      bare
      className="vcf"
      title={isNew ? "Add a college" : `Edit college — ${c?.short_name || c?.name}`}
      submitLabel={isNew ? "Add college" : "Save changes"}
      fieldMap={Object.fromEntries(VERIFY_FIELDS.flatMap(([f]) => [[`sources.${f}`, `src_${f}`], [`sources${f}`, `src_${f}`]]))}
      onSubmit={submit}
      onDone={onDone}
    >
      {(err) => (
        <>
          <datalist id="cf-ownership-list">
            {OWNERSHIP_HINTS.map((o) => (
              <option key={o} value={o} />
            ))}
          </datalist>
          <fieldset className="vcf-group">
            <legend>Identity</legend>
            {isNew ? (
              <p className="vx-muted vx-small">Add a college that is missing from the master list. Check the duplicate warning before saving.</p>
            ) : c?.sno ? (
              <p className="vx-muted vx-small">{`Master list no. ${c.sno} (fixed)`}</p>
            ) : null}
            <div className="td-form__grid">
              <TextField name="name" label="Official name" required full maxLength={300} value={v.name} onChange={set("name")} error={err.name} />
              {existing ? (
                <div className="td-field td-field--full">
                  <div className="vcf-dup is-bad" role="alert">
                    <Icon name="warn" size={16} />
                    <div>
                      {`${existing.message} `}
                      <Link to={portalPath.college(existing.id)} onClick={() => onDone(null)}>
                        Open the existing college
                      </Link>
                    </div>
                  </div>
                </div>
              ) : null}
              {dup ? (
                <div className="td-field td-field--full">
                  <div className={dup.same ? "vcf-dup is-bad" : "vcf-dup is-warn"} role="status" aria-live="polite">
                    <Icon name="warn" size={16} />
                    <div>
                      <strong>{dup.same ? "A college with this name is already in the portal" : "Similar colleges already in the portal"}</strong>
                      <ul>
                        {dup.rows.map((r) => (
                          <li key={r.id}>
                            <a href={portalPath.college(r.id)} target="_blank" rel="noopener noreferrer">
                              {r.name}
                            </a>
                            {` · ${dName(r.district_id)}`}
                          </li>
                        ))}
                      </ul>
                      <span className="vx-muted vx-small">Open it instead of adding a duplicate. The server refuses the same name in the same district.</span>
                    </div>
                  </div>
                </div>
              ) : null}
              <TextField name="short_name" label="Short name" maxLength={80} value={v.short_name} onChange={set("short_name")} error={err.short_name} help="How people refer to it, e.g. “VVIT”." />
              <TextField name="aliases" label="Other names" value={v.aliases} onChange={set("aliases")} error={err.aliases} help="Comma separated. Used by search." />
              <SelectField
                name="district_id"
                label="District"
                required
                value={v.district_id}
                placeholder="Choose a district…"
                options={districts.map((d) => ({ value: d.id, label: d.name }))}
                onChange={(val) => setV((o) => ({ ...o, district_id: val, city_id: "" }))}
                error={err.district_id}
              />
              <SelectField
                name="city_id"
                label="City / town"
                required
                value={cityValue}
                placeholder={v.district_id ? "Choose a city or town…" : "Choose the district first"}
                options={[...cities.map((x) => ({ value: x.id, label: x.name })), ...(v.district_id ? [{ value: "__new", label: "+ Town not in the list…" }] : [])]}
                onChange={set("city_id")}
                error={err.city_id}
              />
              <TextField name="city_name" label="New town name" hidden={cityValue !== "__new"} placeholder="Name of the town" value={v.city_name} onChange={set("city_name")} error={err.city_name} help="Only when the town is not in the list." />
              <TextAreaField name="address" label="Address" rows={2} value={v.address} onChange={set("address")} error={err.address} />
            </div>
          </fieldset>
          <fieldset className="vcf-group">
            <legend>Contact</legend>
            <p className="vx-muted vx-small">The college office line, email and website as officially listed. Add TPO and staff numbers under “Contacts &amp; calls”.</p>
            <div className="td-form__grid">
              <TextField name="phone" label="Office phone" type="tel" value={v.phone} onChange={set("phone")} error={err.phone} help="10-digit numbers; several allowed, separated by / or ," />
              <TextField name="email" label="Office email" type="email" value={v.email} onChange={set("email")} error={err.email} />
              <TextField name="website" label="Website" type="url" full placeholder="https://" value={v.website} onChange={set("website")} error={err.website} />
            </div>
          </fieldset>
          <fieldset className="vcf-group">
            <legend>Institution</legend>
            <div className="td-form__grid">
              <TextField name="ownership" label="Type of institution" list="cf-ownership-list" value={v.ownership} onChange={set("ownership")} error={err.ownership} help="e.g. Pvt autonomous, Pvt affiliated, Govt – National." />
              <TextField name="affiliation" label="Affiliated university" value={v.affiliation} onChange={set("affiliation")} error={err.affiliation} help="University it is affiliated to, e.g. JNTUK." />
              <SelectField name="autonomous" label="Autonomous?" value={v.autonomous} options={AUTONOMY} onChange={set("autonomous")} error={err.autonomous} />
              <SelectField name="tier" label="Research tier" value={v.tier} options={TIERS} onChange={set("tier")} error={err.tier} help="Used in the calling priority." />
              <TextField name="naac" label="NAAC grade" value={v.naac} onChange={set("naac")} error={err.naac} help="The grade first, e.g. “A+”. Anything after a ; is kept as a note." />
            </div>
          </fieldset>
          <fieldset className="vcf-group">
            <legend>Status</legend>
            <p className="vx-muted vx-small">Changing the operating status needs evidence.</p>
            <div className="td-form__grid">
              <SelectField name="op_status" label="Operating status" value={v.op_status} options={OP} onChange={set("op_status")} error={err.op_status} />
              <CheckField name="targeted" label="Targeted by Tech Drona (in the outreach plan)" checked={targeted} onChange={setTargeted} />
              <SelectField name="op_2025_26" label="Admitting new students in 2025-26?" value={v.op_2025_26} options={YNU} onChange={set("op_2025_26")} />
              <SelectField name="op_2026_27" label="Admitting new students in 2026-27?" value={v.op_2026_27} options={YNU} onChange={set("op_2026_27")} />
              <TextAreaField name="op_status_note" label="Why this status" rows={2} value={v.op_status_note} onChange={set("op_status_note")} error={err.op_status_note} />
              <TextField name="op_status_source" label="Link to the evidence" full placeholder="https://" value={v.op_status_source} onChange={set("op_status_source")} error={err.op_status_source} />
              <TextAreaField name="notes" label="Notes" rows={3} value={v.notes} onChange={set("notes")} error={err.notes} help="Shown as “Research notes” under More details on the college page." />
            </div>
          </fieldset>
          {track ? (
            <fieldset className="vcf-group">
              <legend>Sources &amp; verification</legend>
              <p className="vx-muted vx-small">
                {isNew
                  ? "Give a source for each value you can back up. Values saved with a source are marked Verified; the rest stay Unverified."
                  : "Type a source to mark a value Verified (today, by you). Changing a value without a source marks it Unverified."}
              </p>
              <div className="vcf-vlist">
                {VERIFY_FIELDS.map((f) => (
                  <div key={f[0]}>
                    {vrow(f)}
                    {err[`src_${f[0]}`] ? (
                      <div className="td-field__error" role="alert">
                        {err[`src_${f[0]}`]}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="vcf-note vx-muted vx-small">This server does not record per-field verification yet; values are saved as typed (unverified).</p>
          )}
        </>
      )}
    </DialogForm>
  );
}

/** Imperative edit (needs a <FormsHost/> mounted). */
export function editCollegeFull(id: string): Promise<{ id: string } | null> {
  return openDialog<{ id: string }>((done) => <CollegeFormDialog open collegeId={id} onDone={done} />);
}
/** Imperative create (needs a <FormsHost/> mounted). */
export function createCollege(defaults: CollegeFormProps["defaults"] = {}): Promise<{ id: string } | null> {
  return openDialog<{ id: string }>((done) => <CollegeFormDialog open collegeId={null} defaults={defaults} onDone={done} />);
}

/* ------------------------------------------------------------------ mark verified / unverified */

export function VerifyDialog({ college, fields, onDone }: { college: Pick<College, "id" | "name" | "short_name">; fields: string[]; onDone: (ok: boolean | null) => void }) {
  const labels = Object.fromEntries(VERIFY_FIELDS) as Record<string, string>;
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  return (
    <DialogForm<boolean>
      open
      title="Mark as verified"
      submitLabel="Mark verified"
      intro={`Confirm ${fields.map((f) => labels[f] ?? f).join(", ")} of ${college.short_name || college.name}. You and today's date are recorded with the source.`}
      onSubmit={async () => {
        const s = str(source);
        if (!s) throw validationError({ source: "Give the source you checked." });
        const se = sourceError(s);
        if (se) throw validationError({ source: se });
        await portalApi.post(`colleges/${encodeURIComponent(college.id)}/verify`, { fields, source: s, note: str(note) || undefined });
        toast("Marked verified", "good");
        return true;
      }}
      onDone={onDone}
    >
      {(err) => (
        <>
          <TextField name="source" label="Source" required full value={source} onChange={setSource} placeholder="https://… or a note, e.g. “Called the office on 7 Nov”" error={err.source} />
          <TextField name="note" label="Note" full value={note} onChange={setNote} placeholder="Optional note" error={err.note} />
        </>
      )}
    </DialogForm>
  );
}

/** Mark fields verified (with one source) or clear their verification (old college-form.js verifyFields). */
export async function verifyFields(college: Pick<College, "id" | "name" | "short_name">, fields: string[], { clear = false } = {}): Promise<boolean | null> {
  if (clear) {
    const ok = await confirm({
      title: "Mark as unverified?",
      text: `The ${fields.length === 1 ? "value stays, but it" : "values stay, but they"} will show as Unverified until someone confirms ${fields.length === 1 ? "it" : "them"} with a source.`,
      confirmLabel: "Mark unverified",
    });
    if (!ok) return null;
    try {
      await portalApi.post(`colleges/${encodeURIComponent(college.id)}/verify`, { fields, verified: false, source: "cleared" });
      toast("Marked unverified", "good");
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "bad");
      return null;
    }
  }
  return openDialog<boolean>((done) => <VerifyDialog college={college} fields={fields} onDone={done} />);
}

