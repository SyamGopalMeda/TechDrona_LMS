"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import { ErrorSummary, FormAlert, Notice, ReferenceChip } from "@/features/auth/components/shared";
import { problemFieldErrors, retryAfterSeconds, toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import { deviceName, type DevicesResponse, type Me } from "@/features/account/lib/types";
import { DECLARATION, EXPLANATION_MAX, EXPLANATION_MIN, NO_SECRETS_HINT, SEC_REF, WHAT_HAPPENED, looksLikeSecret } from "../lib/copy";
import { clearDraft, loadDraft, saveDraft } from "../lib/draft";
import type { SecurityStatus, UnblockCreateBody, UnblockCreated } from "../lib/types";
import { UnblockStatusCard } from "./UnblockStatus";
import { formatCountdown, formatDate, formatRelative } from "@/lib/format";
import { useResource } from "@/lib/api/use-resource";

type Field = "what_happened" | "explanation" | "devices" | "preferred_contact" | "declaration";
type Contact = "in_app" | "email" | "sms";

const API_FIELDS: Record<string, Field> = {
  what_happened: "what_happened",
  explanation: "explanation",
  recognised_user_device_ids: "devices",
  none_recognised: "devices",
  preferred_contact: "preferred_contact",
  declaration: "declaration",
};

/**
 * Unblock request form (account-unblock-workflow §3; UNB-01). Never asks for passwords, OTPs,
 * recovery codes, payment details, Aadhaar or PAN. No CAPTCHA (WCAG 2.2 SC 3.3.8).
 * Drafts autosave on this device (7 days, cleared on send). Supporting documents (UNB-03) are not
 * offered: the api endpoint answers 503 until the S3 presign adapter exists.
 */
export function UnblockRequestForm({ caseRef: caseRefProp }: { caseRef?: string | null }) {
  const status = useResource<SecurityStatus>("me/security/status", { handle: { restriction: false } });
  const devices = useResource<DevicesResponse>("me/devices", { handle: { restriction: false } });
  const me = useResource<Me>("me", { handle: { restriction: false } });

  if (status.error || devices.error || me.error) {
    const err = status.error ?? devices.error ?? me.error;
    return <ErrorState error={err} onRetry={() => void Promise.all([status.reload(), devices.reload(), me.reload()])} />;
  }
  if (!status.data || !devices.data || !me.data) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading the form…</span>
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const caseRef = status.data.case_ref ?? (caseRefProp && SEC_REF.test(caseRefProp) ? caseRefProp : null);
  if (!caseRef || status.data.level === 0) {
    return (
      <Notice title="There's nothing to review">
        Your account has no open case. If something isn&apos;t working,{" "}
        <Link href="/help" className="text-fg-link underline">
          contact support
        </Link>
        .
      </Notice>
    );
  }
  const existing = status.data.unblock_request?.reference;
  if (existing) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-fg-secondary">You already have a review request for this case. You can follow it here.</p>
        <UnblockStatusCard reference={existing} />
      </div>
    );
  }

  return <RequestForm caseRef={caseRef} devices={devices.data} me={me.data} />;
}

function RequestForm({ caseRef, devices, me }: { caseRef: string; devices: DevicesResponse; me: Me }) {
  const base = useId();
  const idemKey = useRef(uuid7());
  const [initial] = useState(() => loadDraft(caseRef));
  const knownDevices = new Set(devices.data.map((d) => d.user_device_id));
  const [what, setWhat] = useState<string[]>(() => (initial?.what_happened ?? []).filter((c) => WHAT_HAPPENED.some((o) => o.code === c)));
  const [explanation, setExplanation] = useState(initial?.explanation ?? "");
  const [recognised, setRecognised] = useState<string[]>(() => (initial?.recognised ?? []).filter((id) => knownDevices.has(id)));
  const [noneRecognised, setNoneRecognised] = useState(initial?.none_recognised ?? false);
  const [contact, setContact] = useState<Contact>(initial?.contact ?? "in_app");
  const [draftSavedAt, setDraftSavedAt] = useState<number | null>(initial?.saved_at ?? null);
  const [declaration, setDeclaration] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<UnblockCreated | null>(null);
  const [openRef, setOpenRef] = useState<string | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const successRef = useRef<HTMLHeadingElement>(null);

  // Debounced local autosave of everything except the declaration.
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    const t = window.setTimeout(() => {
      const draft = { what_happened: what, explanation, recognised, none_recognised: noneRecognised, contact };
      if (saveDraft(caseRef, draft)) setDraftSavedAt(explanation.trim() || what.length || recognised.length || noneRecognised ? Date.now() : null);
    }, 800);
    return () => window.clearTimeout(t);
  }, [caseRef, what, explanation, recognised, noneRecognised, contact]);

  const discardDraft = () => {
    clearDraft(caseRef);
    setWhat([]);
    setExplanation("");
    setRecognised([]);
    setNoneRecognised(false);
    setContact("in_app");
    setDraftSavedAt(null);
  };

  // me/devices lists trusted + pending_otp devices: the same set the server revokes from on submit.
  const deviceList = devices.data;
  const contacts: { value: Contact; label: string; enabled: boolean }[] = [
    { value: "in_app", label: "In-app", enabled: true },
    { value: "email", label: `Email${me.user.email ? ` ${me.user.email}` : ""}`, enabled: !!me.user.email && !!me.user.email_verified },
    { value: "sms", label: `SMS${me.user.mobile_masked ? ` ${me.user.mobile_masked}` : ""}`, enabled: !!me.user.mobile_masked && !!me.user.mobile_verified },
  ];

  const ids: Record<Field, string> = {
    what_happened: `${base}-what-0`,
    explanation: `${base}-explanation`,
    devices: `${base}-dev-0`,
    preferred_contact: `${base}-contact-in_app`,
    declaration: `${base}-declaration`,
  };

  const validate = () => {
    const e: Partial<Record<Field, string>> = {};
    if (what.length === 0) e.what_happened = "Choose at least one option for what happened.";
    const t = explanation.trim();
    if (t.length < EXPLANATION_MIN) e.explanation = `Your explanation needs at least ${EXPLANATION_MIN} characters.`;
    else if (t.length > EXPLANATION_MAX) e.explanation = `Your explanation can be at most ${EXPLANATION_MAX.toLocaleString("en-IN")} characters.`;
    else if (looksLikeSecret(t)) e.explanation = NO_SECRETS_HINT;
    if (recognised.length === 0 && !noneRecognised) e.devices = "Tick the devices you recognise, or choose “None of these”.";
    if (!contacts.find((c) => c.value === contact)?.enabled) e.preferred_contact = "Choose a verified contact method.";
    if (!declaration) e.declaration = "Please confirm the declaration.";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    setError(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const body: UnblockCreateBody = {
        case_ref: caseRef,
          submit: true,
          what_happened: what,
          explanation: explanation.trim(),
          recognised_user_device_ids: noneRecognised ? [] : recognised,
          none_recognised: noneRecognised,
          attachment_ids: [],
          preferred_contact: contact,
          declaration: true,
          guardian_assisted: false,
      };
      const res = await api.post<UnblockCreated>(
        "security/unblock-requests",
        body,
        { idempotencyKey: idemKey.current, handle: { restriction: false } },
      );
      if (res.kind === "ok") {
        sent.current = true;
        clearDraft(caseRef);
        setCreated(res.data);
        setTimeout(() => successRef.current?.focus(), 0);
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "unblock_request_open") {
        const r = err.problem?.reference;
        setOpenRef(typeof r === "string" ? r : null);
        if (typeof r !== "string") setError(toFormError(err));
      } else if (err instanceof ApiError && err.code === "dlp_rejected") {
        setErrors({ explanation: NO_SECRETS_HINT });
      } else if (err instanceof ApiError && err.code === "unblock_rate_limited") {
        const s = retryAfterSeconds(err);
        setError({ title: "You can send 3 requests in 30 days", detail: s ? `Next available in ${formatCountdown(s, "short")}.` : err.detail, requestId: err.requestId, code: err.code });
      } else {
        const f = problemFieldErrors(err);
        const mapped: Partial<Record<Field, string>> = {};
        for (const [k, v] of Object.entries(f)) if (API_FIELDS[k]) mapped[API_FIELDS[k]] = v;
        if (Object.keys(mapped).length) setErrors(mapped);
        else setError(toFormError(err));
      }
      // A failed attempt may be retried with the same key only for the identical body; start fresh.
      idemKey.current = uuid7();
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  if (openRef) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-fg-secondary">You already have an open request for this case.</p>
        <UnblockStatusCard reference={openRef} />
      </div>
    );
  }

  if (created) {
    const via = (created.acknowledgement_sent_via ?? []).filter((c) => c !== "in_app");
    const channel = via.length ? via.map((c) => (c === "sms" ? "SMS" : c)).join(" and ") : "in-app message";
    return (
      <div className="space-y-4">
        <div role="status" className="rounded-lg border border-success-border bg-success-subtle p-4">
          <h2 ref={successRef} tabIndex={-1} className="font-display text-lg font-semibold text-success-fg focus:outline-none">
            Request sent
          </h2>
          <p className="mt-1 text-sm text-fg-secondary">
            Reference <ReferenceChip value={created.reference} />. We&apos;ll update you here and by {channel}.
          </p>
          {created.devices_revoked?.length ? (
            <p className="mt-2 text-sm text-fg-secondary">We signed out the devices you didn&apos;t recognise: {created.devices_revoked.map((d) => d.label || "Unnamed device").join(", ")}.</p>
          ) : null}
        </div>
        <UnblockStatusCard reference={created.reference} requestId={created.request_id} sla={created.sla} />
      </div>
    );
  }

  const errorId = (f: Field) => (errors[f] ? `${base}-${f}-err` : undefined);
  const fieldError = (f: Field) =>
    errors[f] ? (
      <p id={`${base}-${f}-err`} role="alert" className="text-xs font-medium text-danger-fg">
        {errors[f]}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      <ErrorSummary errors={errors as Record<string, string>} fieldIds={ids} />
      <FormAlert ref={alertRef} error={error} />

      <p className="text-sm text-fg-secondary">
        Case <ReferenceChip value={caseRef} />
      </p>

      <fieldset className="space-y-2" aria-describedby={errorId("what_happened")}>
        <legend className="text-sm font-medium text-fg">
          What happened? (choose all that apply)<span className="text-danger-fg" aria-hidden="true"> *</span>
        </legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {WHAT_HAPPENED.map((o, i) => (
            <Checkbox
              key={o.code}
              id={`${base}-what-${i}`}
              label={o.label}
              checked={what.includes(o.code)}
              onChange={(e) => setWhat((w) => (e.target.checked ? [...w, o.code] : w.filter((x) => x !== o.code)))}
              className="min-h-[48px] items-center"
            />
          ))}
        </div>
        {fieldError("what_happened")}
      </fieldset>

      <div className="space-y-1.5">
        <label htmlFor={ids.explanation} className="block text-sm font-medium text-fg">
          Your explanation ({EXPLANATION_MIN}–{EXPLANATION_MAX.toLocaleString("en-IN")} characters)<span className="text-danger-fg" aria-hidden="true"> *</span>
        </label>
        <textarea
          id={ids.explanation}
          rows={6}
          maxLength={EXPLANATION_MAX}
          aria-required="true"
          aria-invalid={errors.explanation ? true : undefined}
          aria-describedby={[`${base}-explanation-hint`, errorId("explanation")].filter(Boolean).join(" ")}
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
          className="block w-full rounded-md border border-line-control bg-surface p-3 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none aria-[invalid=true]:border-danger-border"
        />
        <p id={`${base}-explanation-hint`} className="flex justify-between text-xs text-fg-muted">
          <span>{NO_SECRETS_HINT}</span>
          <span>
            {explanation.length}/{EXPLANATION_MAX}
          </span>
        </p>
        {fieldError("explanation")}
      </div>

      <fieldset className="space-y-2" aria-describedby={[`${base}-devices-hint`, errorId("devices")].filter(Boolean).join(" ")}>
        <legend className="text-sm font-medium text-fg">
          Devices you recognise<span className="text-danger-fg" aria-hidden="true"> *</span>
        </legend>
        <p id={`${base}-devices-hint`} className="text-xs text-fg-muted">
          Unticked devices will be signed out when you send this. You can add them again later.
        </p>
        {deviceList.map((d, i) => (
          <Checkbox
            key={d.user_device_id}
            id={`${base}-dev-${i}`}
            label={d.user_label && d.label ? `${d.user_label} · ${d.label}` : deviceName(d)}
            description={`last used ${d.last_used_at ? formatRelative(d.last_used_at) : "—"}${d.approx_region ? ` · ${d.approx_region}` : ""}${d.first_seen_at ? ` · first seen ${formatDate(d.first_seen_at)}` : ""}`}
            checked={recognised.includes(d.user_device_id)}
            disabled={noneRecognised}
            onChange={(e) => setRecognised((r) => (e.target.checked ? [...r, d.user_device_id] : r.filter((x) => x !== d.user_device_id)))}
            className="min-h-[48px]"
          />
        ))}
        <Checkbox
          id={deviceList.length === 0 ? `${base}-dev-0` : undefined}
          label="None of these"
          checked={noneRecognised}
          onChange={(e) => {
            setNoneRecognised(e.target.checked);
            if (e.target.checked) setRecognised([]);
          }}
          className="min-h-[48px]"
        />
        {fieldError("devices")}
      </fieldset>

      <fieldset className="space-y-2" aria-describedby={[`${base}-contact-hint`, errorId("preferred_contact")].filter(Boolean).join(" ")}>
        <legend className="text-sm font-medium text-fg">
          Preferred contact<span className="text-danger-fg" aria-hidden="true"> *</span>
        </legend>
        <p id={`${base}-contact-hint`} className="text-xs text-fg-muted">
          Only verified contact methods can be chosen.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
          {contacts.map((c) => (
            <label key={c.value} className={`flex min-h-[44px] items-center gap-2 text-sm ${c.enabled ? "text-fg" : "text-fg-disabled"}`}>
              <input
                id={`${base}-contact-${c.value}`}
                type="radio"
                name="preferred_contact"
                value={c.value}
                disabled={!c.enabled}
                checked={contact === c.value}
                onChange={() => setContact(c.value)}
                className="h-4 w-4 accent-[var(--td-brand)]"
              />
              {c.label}
              {!c.enabled && c.value !== "in_app" ? <span className="text-xs">(not verified)</span> : null}
            </label>
          ))}
        </div>
        {fieldError("preferred_contact")}
      </fieldset>

      <div>
        <Checkbox id={ids.declaration} label={DECLARATION} checked={declaration} onChange={(e) => setDeclaration(e.target.checked)} aria-invalid={errors.declaration ? true : undefined} />
        {fieldError("declaration")}
      </div>

      <div className="sticky bottom-0 -mx-4 flex flex-col gap-2 border-t border-line bg-surface px-4 py-3 sm:static sm:mx-0 sm:flex-row sm:items-center sm:border-0 sm:bg-transparent sm:p-0">
        <Button type="submit" loading={busy} size="lg">
          Send request
        </Button>
        <span className="text-sm text-fg-muted">Response time: first reply within 24 hours</span>
      </div>
      <p role="status" className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        {draftSavedAt ? (
          <>
            <span>Draft saved on this device. It is kept for 7 days and removed when you send the request.</span>
            <Button type="button" variant="ghost" size="sm" onClick={discardDraft}>
              Discard draft
            </Button>
          </>
        ) : (
          <span>Your answers are saved on this device as you type.</span>
        )}
      </p>
    </form>
  );
}
