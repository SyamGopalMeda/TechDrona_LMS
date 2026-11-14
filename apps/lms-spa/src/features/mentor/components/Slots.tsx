"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Dialog, FormField, Input, Select, Table, useToast } from "@/components/ui";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { fieldErrorsOf, formatDateTime, localInputToIso, useFailToast } from "@/features/trainer/shared/ui";
import { KIND_LABEL, isCode, overlapConflicts, send } from "../lib/api";
import type { DeleteSlotResult, Duration, MentorSlot, SessionKind } from "../lib/types";

const KIND_OPTIONS = (Object.keys(KIND_LABEL) as SessionKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }));
const DURATIONS: Duration[] = [30, 45, 60];

/** Publish a slot (30/45/60 min). Overlap with an existing slot → 409 slot_overlap. */
export function SlotForm({ onCreated }: { onCreated: (slots: MentorSlot[]) => void }) {
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState<string>("60");
  const [kind, setKind] = useState<SessionKind>("mock_interview");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflicts, setConflicts] = useState<{ starts_at: string; ends_at: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  async function submit() {
    const iso = localInputToIso(start);
    const errs: Record<string, string> = {};
    if (!iso) errs.starts_at = "Choose a start time";
    else if (Date.parse(iso) <= Date.now()) errs.starts_at = "Choose a time in the future";
    setErrors(errs);
    setConflicts([]);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const res = await send<{ data: MentorSlot[] }>("post", "mentor/slots", {
        slots: [{ starts_at: iso, duration_minutes: Number(duration), session_kind: kind }],
      });
      toast.show({ tone: "success", title: "Slot published" });
      setStart("");
      onCreated(res.data);
    } catch (err) {
      if (isCode(err, "slot_overlap")) {
        setConflicts(overlapConflicts(err));
        setErrors({ starts_at: "This overlaps another of your slots" });
        return;
      }
      const fe = fieldErrorsOf(err);
      const mapped: Record<string, string> = {};
      for (const [k, v] of Object.entries(fe)) mapped[k.replace(/^slots\.\d+\./, "")] = v;
      if (Object.keys(mapped).length) setErrors(mapped);
      else fail(err, "Couldn't publish the slot");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Starts at" required error={errors.starts_at}>
          {(c) => <Input {...c} type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />}
        </FormField>
        <FormField label="Length" error={errors.duration_minutes}>
          {(c) => <Select {...c} value={duration} onChange={(e) => setDuration(e.target.value)} options={DURATIONS.map((d) => ({ value: String(d), label: `${d} minutes` }))} />}
        </FormField>
        <FormField label="Session type" error={errors.session_kind}>
          {(c) => <Select {...c} value={kind} onChange={(e) => setKind(e.target.value as SessionKind)} options={KIND_OPTIONS} />}
        </FormField>
      </div>
      {conflicts.length ? (
        <ul role="alert" className="text-sm text-danger-fg">
          {conflicts.map((c) => (
            <li key={c.starts_at}>
              Overlaps {formatDateTime(c.starts_at)} – {formatDateTime(c.ends_at)}
            </li>
          ))}
        </ul>
      ) : null}
      <Button type="submit" loading={busy}>
        Publish slot
      </Button>
    </form>
  );
}

/** MEN-002 availability: own slots, publish, delete (booked → cancel with student credit). */
export function MentorSlots() {
  const list = useApi<{ data: MentorSlot[] }>("mentor/slots");
  const [target, setTarget] = useState<MentorSlot | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  async function remove() {
    if (!target) return;
    setBusy(true);
    try {
      const r = await send<DeleteSlotResult>("delete", `mentor/slots/${seg(target.id)}`);
      toast.show({ tone: "success", title: r.cancelled_booking_id ? "Session cancelled — the student's credit was restored" : "Slot removed" });
      setTarget(null);
      await list.reload();
    } catch (err) {
      fail(err, "Couldn't remove the slot");
    } finally {
      setBusy(false);
    }
  }

  const rows = (list.data?.data ?? []).filter((s) => s.status !== "cancelled");
  return (
    <div className="space-y-6">
      <Card title="Publish availability">
        <SlotForm onCreated={() => void list.reload()} />
      </Card>
      <Table
        caption="Your slots"
        showCaption
        columns={[
          { key: "w", header: "When", cell: (s: MentorSlot) => formatDateTime(s.starts_at) },
          { key: "d", header: "Length", cell: (s) => `${s.duration_minutes} min` },
          { key: "k", header: "Type", cell: (s) => KIND_LABEL[s.session_kind] ?? s.session_kind },
          {
            key: "s",
            header: "Status",
            cell: (s) =>
              s.status === "booked" && s.booking_id ? (
                <Link className="text-fg-link underline" href={`/mentor/sessions/${seg(s.booking_id)}`}>
                  Booked{s.student_name ? ` by ${s.student_name}` : ""}
                </Link>
              ) : (
                <Badge tone={s.status === "open" ? "success" : "neutral"}>{s.status === "open" ? "Open" : s.status}</Badge>
              ),
          },
          {
            key: "a",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (s) =>
              s.status === "open" || s.status === "booked" ? (
                <Button size="sm" variant="ghost" onClick={() => setTarget(s)}>
                  {s.status === "booked" ? "Cancel session" : "Delete"}
                </Button>
              ) : null,
          },
        ]}
        rows={rows}
        rowKey={(s) => s.id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No slots yet", description: "Publish a 30, 45 or 60 minute slot so students can book you." }}
      />
      <Dialog
        open={target !== null}
        onClose={() => setTarget(null)}
        title={target?.status === "booked" ? "Cancel this booked session?" : "Delete this slot?"}
        description={target?.status === "booked" ? "The student is notified and gets the session credit back." : "Students will no longer see this slot."}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>
              Keep
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void remove()}>
              {target?.status === "booked" ? "Cancel session" : "Delete slot"}
            </Button>
          </>
        }
      />
    </div>
  );
}
