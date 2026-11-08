"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, Skeleton, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { FormAlert } from "@/features/auth/components/shared";
import { problemFieldErrors, toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import type { Me, ProfilePatchBody } from "../lib/types";
import { useResource } from "../lib/use-resource";

/** STU-020 Profile · ME-01 read, ME-02 update, AUTH-03 resend verification. */
export function ProfileSettings() {
  const toast = useToast();
  const me = useResource<Me>("me");
  const [name, setName] = useState("");
  const [year, setYear] = useState("");
  const [branch, setBranch] = useState("");
  const [fe, setFe] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = me.data?.profile;
    if (!p) return;
    setName(p.full_name ?? "");
    setYear(p.graduation_year ? String(p.graduation_year) : "");
    setBranch(p.branch ?? "");
  }, [me.data]);

  if (me.error) return <ErrorState error={me.error} onRetry={me.reload} />;
  if (!me.data) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading profile…</span>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const { user, profile } = me.data;
  const locked = !!profile?.legal_name_locked;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (!locked && name.trim().length < 2) v.full_name = "Enter your full name.";
    const y = year ? Number(year) : null;
    if (year && (!Number.isInteger(y) || y! < 1990 || y! > new Date().getFullYear() + 8)) v.graduation_year = "Enter a 4-digit graduation year.";
    if (branch.length > 80) v.branch = "Use 80 characters or fewer.";
    setFe(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    setError(null);
    try {
      const body: ProfilePatchBody = { graduation_year: y, branch: branch.trim() || null };
      if (!locked) body.full_name = name.trim();
      await api.patch("me/profile", body);
      toast.show({ tone: "success", title: "Profile saved." });
      await me.reload();
    } catch (err) {
      const f = problemFieldErrors(err);
      if (Object.keys(f).length) setFe(f);
      else {
        setError(toFormError(err));
        setTimeout(() => alertRef.current?.focus(), 0);
      }
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setResending(true);
    try {
      await api.post("auth/verify/email/resend", undefined, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Verification email sent." });
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card title="Contact details">
        <dl className="grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-fg-muted">Email</dt>
            <dd className="mt-0.5 flex flex-wrap items-center gap-2 text-fg">
              {user.email ?? "Not added"}
              {user.email ? user.email_verified ? <Badge tone="success">Verified</Badge> : <Badge tone="warning">Not verified</Badge> : null}
              {user.email && !user.email_verified ? (
                <Button variant="ghost" size="sm" loading={resending} onClick={resend}>
                  Resend link
                </Button>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="text-fg-muted">Mobile</dt>
            <dd className="mt-0.5 flex flex-wrap items-center gap-2 text-fg">
              {user.mobile_masked ?? "Not added"}
              {user.mobile_masked ? user.mobile_verified ? <Badge tone="success">Verified</Badge> : <Badge tone="warning">Not verified</Badge> : null}
              {user.mobile_masked && !user.mobile_verified ? (
                <Link href="/verify/mobile" className="text-fg-link underline">
                  Verify
                </Link>
              ) : null}
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-xs text-fg-muted">Changing your email or mobile number is not available here yet. Contact support if you need to change it.</p>
      </Card>

      <Card title="Profile">
        <form onSubmit={submit} noValidate className="max-w-md space-y-4">
          <FormAlert ref={alertRef} error={error} />
          <FormField label="Full name" hint={locked ? "Your name is locked because it appears on a certificate. Contact support to correct it." : undefined} error={fe.full_name} required>
            {(f) => <Input {...f} name="full_name" autoComplete="name" value={name} disabled={locked} onChange={(e) => setName(e.target.value)} />}
          </FormField>
          <FormField label="Graduation year" error={fe.graduation_year}>
            {(f) => <Input {...f} name="graduation_year" inputMode="numeric" maxLength={4} value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, ""))} />}
          </FormField>
          <FormField label="Branch" hint="For example CSE, ECE, IT" error={fe.branch}>
            {(f) => <Input {...f} name="branch" value={branch} onChange={(e) => setBranch(e.target.value)} />}
          </FormField>
          <Button type="submit" loading={busy}>
            Save changes
          </Button>
        </form>
      </Card>
    </div>
  );
}
