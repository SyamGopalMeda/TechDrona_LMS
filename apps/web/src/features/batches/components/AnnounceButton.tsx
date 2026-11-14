"use client";

import { useState } from "react";
import { Button, Checkbox, FormField, Input, useToast } from "@/components/ui";
import { Icon } from "@/components/ui/Display";
import { api } from "@/lib/api/client";
import { ActionDialog, TextArea } from "@/features/admin/components/console-ui";
import { toOutcome } from "@/features/admin/lib/console";

const EMPTY = { title: "", body: "", send_email: false };

/**
 * Batch announcement (NTF: POST batches/{id}/announcements, permission notification.batch_announce
 * for the batch's trainer or an Admin). Every active student in the batch gets it in their
 * Notifications inbox, and by email when ticked. The api allows 3 per batch per day.
 */
export function AnnounceButton({ batchId, batchName }: { batchId: string; batchName?: string | null }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const toast = useToast();
  return (
    <>
      <Button onClick={() => setOpen(true)} className="gap-2">
        <Icon name="megaphone" className="h-[18px] w-[18px]" />
        Message students
      </Button>
      <ActionDialog<{ recipients: number }>
        open={open}
        onClose={() => setOpen(false)}
        onOpen={() => setForm(EMPTY)}
        title={batchName ? `Message ${batchName}` : "Message this batch"}
        description="Every student in this batch gets it in their Notifications. You can send up to 3 messages a day to a batch."
        submitLabel="Send message"
        validate={() => (!form.title.trim() ? "Add a subject." : !form.body.trim() ? "Write the message." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post<{ recipients: number }>(
              `batches/${encodeURIComponent(batchId)}/announcements`,
              { title: form.title.trim(), body: form.body.trim(), send_email: form.send_email },
              { idempotencyKey: true },
            ),
          )
        }
        onDone={(outcome) => {
          if (outcome.kind !== "ok") return;
          const n = outcome.data.recipients;
          toast.show({ title: "Message sent", description: `${n} student${n === 1 ? "" : "s"} will see it in Notifications.`, tone: "success" });
        }}
      >
        <FormField label="Subject" required>
          {(f) => <Input {...f} maxLength={120} value={form.title} onChange={(e) => setForm((v) => ({ ...v, title: e.target.value }))} />}
        </FormField>
        <FormField label="Message" required hint="Plain text, up to 2,000 characters.">
          {(f) => <TextArea {...f} rows={5} maxLength={2000} value={form.body} onChange={(e) => setForm((v) => ({ ...v, body: e.target.value }))} />}
        </FormField>
        <Checkbox label="Also send by email" checked={form.send_email} onChange={(e) => setForm((v) => ({ ...v, send_email: e.target.checked }))} />
      </ActionDialog>
    </>
  );
}
