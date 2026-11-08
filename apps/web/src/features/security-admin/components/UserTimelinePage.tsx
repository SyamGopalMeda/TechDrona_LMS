"use client";

import { useState } from "react";
import { Button, FormField, Input, PageHeader, Select } from "@/components/ui";
import { SECURITY_REASON_CODES } from "@/features/admin/components/console-ui";
import { TimelineTab } from "./EvidenceTabs";

/** SEC-007 user security timeline (H12). Needs a reason code and a case ref or ticket id. */
export function UserTimelinePage({ userId }: { userId: string }) {
  const [reason, setReason] = useState("case_review");
  const [caseRef, setCaseRef] = useState("");
  const [ctx, setCtx] = useState<{ reasonCode: string; caseRef: string } | null>(null);
  return (
    <div>
      <PageHeader eyebrow="SEC-007 · H12" title="User security timeline" description={`User ${userId}`} />
      {ctx ? (
        <TimelineTab userId={userId} ctx={ctx} />
      ) : (
        <form
          className="max-w-lg space-y-4 rounded-xl border border-line bg-surface p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (caseRef.trim()) setCtx({ reasonCode: reason, caseRef: caseRef.trim() });
          }}
        >
          <p className="text-sm text-fg-muted">This view is recorded in the audit log. Give a reason and the case reference or ticket id.</p>
          <FormField label="Reason" required>{(f) => <Select {...f} value={reason} onChange={(e) => setReason(e.target.value)} options={SECURITY_REASON_CODES} />}</FormField>
          <FormField label="Case reference or ticket id" required>{(f) => <Input {...f} value={caseRef} onChange={(e) => setCaseRef(e.target.value)} placeholder="SEC-2611-7KQ4MZ" />}</FormField>
          <Button type="submit" disabled={!caseRef.trim()}>
            Open timeline
          </Button>
        </form>
      )}
    </div>
  );
}
