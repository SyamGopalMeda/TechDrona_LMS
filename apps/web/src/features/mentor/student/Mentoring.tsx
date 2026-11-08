"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Select, StatTile, useToast } from "@/components/ui";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { LoadingBlock, formatDateTime, useFailToast } from "@/features/trainer/shared/ui";
import { KIND_LABEL, LIVE_STATUSES, isCode, send } from "../lib/api";
import type { Booking, BookingList, SessionKind, Slot, SlotList } from "../lib/types";
import { MeetingLink } from "../components/Mentor";
import { BookingBadge, FeedbackView } from "../components/shared";

/** "R (no package)" state: no premium placement package. */
function NoPackage() {
  return (
    <EmptyState
      title="Mock interviews come with a placement package"
      description="Book 1:1 mock interviews and career sessions with a mentor once you have a premium placement package."
      action={
        <Link className="text-fg-link underline" href="/app/billing">
          See plans
        </Link>
      }
    />
  );
}

const freeChange = (b: Booking) => Date.parse(b.free_change_until) > Date.now();

function SlotPicker({ slots, onPick, busyId, actionLabel }: { slots: Slot[]; onPick: (s: Slot) => void; busyId: string | null; actionLabel: string }) {
  if (!slots.length) return <EmptyState title="No open slots right now" description="Mentors add new slots every week — check back soon." />;
  return (
    <ul className="divide-y divide-line">
      {slots.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="text-sm">
            <p className="font-medium text-fg">
              {formatDateTime(s.starts_at)} · {s.duration_minutes} min
            </p>
            <p className="text-fg-muted">
              {KIND_LABEL[s.session_kind] ?? s.session_kind}
              {s.mentor_name ? ` with ${s.mentor_name}` : ""}
            </p>
          </div>
          <Button size="sm" loading={busyId === s.id} onClick={() => onPick(s)}>
            {actionLabel}
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** STU-013 mock interviews: book / reschedule / cancel; feedback history. */
export function StudentMentoring() {
  const [kind, setKind] = useState<string>("");
  const slots = useApi<SlotList>("mentoring/slots", { session_kind: kind || undefined, limit: 50 });
  const bookings = useApi<BookingList>("me/mentoring/bookings", { limit: 50 });
  const [busyId, setBusyId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<Booking | null>(null);
  const [moving, setMoving] = useState<Booking | null>(null);
  const toast = useToast();
  const fail = useFailToast();

  const reloadAll = async () => {
    await Promise.all([slots.reload(), bookings.reload()]);
  };

  async function book(s: Slot) {
    setBusyId(s.id);
    try {
      await send<Booking>("post", "mentoring/bookings", { slot_id: s.id }, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Session booked", description: `${formatDateTime(s.starts_at)} — the meeting link appears here before the session.` });
      await reloadAll();
    } catch (err) {
      if (isCode(err, "entitlement_required")) toast.show({ tone: "warning", title: "No mentor sessions left", description: "Your package's mentor sessions are used up." });
      else if (isCode(err, "slot_unavailable")) {
        toast.show({ tone: "warning", title: "That slot was just taken", description: "Pick another time." });
        await slots.reload();
      } else fail(err, "Couldn't book the session");
    } finally {
      setBusyId(null);
    }
  }

  async function reschedule(s: Slot) {
    if (!moving) return;
    setBusyId(s.id);
    try {
      await send<Booking>("post", `mentoring/bookings/${seg(moving.id)}/reschedule`, { slot_id: s.id }, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Session moved", description: formatDateTime(s.starts_at) });
      setMoving(null);
      await reloadAll();
    } catch (err) {
      if (isCode(err, "entitlement_required")) toast.show({ tone: "warning", title: "No mentor sessions left", description: "Moving this late needs a new session credit." });
      else fail(err, "Couldn't reschedule");
    } finally {
      setBusyId(null);
    }
  }

  async function cancel() {
    if (!cancelling) return;
    setBusyId(cancelling.id);
    try {
      const b = await send<Booking>("post", `mentoring/bookings/${seg(cancelling.id)}/cancel`, {}, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Session cancelled", description: b.credit_restored ? "Your session credit is back." : "The session credit was used (less than 12 h notice)." });
      setCancelling(null);
      await reloadAll();
    } catch (err) {
      fail(err, "Couldn't cancel");
    } finally {
      setBusyId(null);
    }
  }

  const noPackage = isCode(slots.error, "entitlement_required");
  const quota = slots.data?.quota ?? bookings.data?.quota;
  const all = bookings.data?.data ?? [];
  const upcoming = all.filter((b) => LIVE_STATUSES.includes(b.status) && Date.parse(b.ends_at) > Date.now());
  const history = all.filter((b) => !upcoming.includes(b));

  return (
    <div className="space-y-6">
      {quota ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <StatTile label="Mentor sessions left" value={quota.has_package ? quota.mentor_sessions_remaining : 0} />
          <StatTile label="Upcoming sessions" value={upcoming.length} />
        </div>
      ) : null}

      <Card title="Your upcoming sessions">
        {bookings.loading && !bookings.data ? (
          <LoadingBlock />
        ) : bookings.error ? (
          <ErrorState error={bookings.error} onRetry={() => void bookings.reload()} />
        ) : upcoming.length ? (
          <ul className="divide-y divide-line">
            {upcoming.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="space-y-1 text-sm">
                  <p className="font-medium text-fg">
                    {formatDateTime(b.starts_at)} · {KIND_LABEL[b.session_kind] ?? b.session_kind}
                    {b.mentor_name ? ` with ${b.mentor_name}` : ""}
                  </p>
                  <MeetingLink url={b.meeting_url} />
                  <p className="text-xs text-fg-muted">
                    {freeChange(b) ? `Free to reschedule or cancel until ${formatDateTime(b.free_change_until)}.` : "Less than 12 h to go: cancelling uses the credit; moving needs a new credit."}
                  </p>
                </div>
                <div className="flex gap-2">
                  <BookingBadge status={b.status} />
                  <Button size="sm" variant="secondary" onClick={() => setMoving(b)}>
                    Reschedule
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setCancelling(b)}>
                    Cancel
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">No sessions booked.</p>
        )}
      </Card>

      <Card
        title="Book a session"
        actions={
          noPackage ? null : (
            <Select
              aria-label="Session type"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              options={[{ value: "", label: "All types" }, ...(Object.keys(KIND_LABEL) as SessionKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))]}
            />
          )
        }
      >
        {noPackage ? (
          <NoPackage />
        ) : slots.error ? (
          <ErrorState error={slots.error} onRetry={() => void slots.reload()} />
        ) : slots.loading && !slots.data ? (
          <LoadingBlock />
        ) : quota && quota.mentor_sessions_remaining <= 0 ? (
          <EmptyState title="You've used all your mentor sessions" description="Sessions you cancel at least 12 h ahead, or that a mentor misses, are credited back." />
        ) : (
          <SlotPicker slots={slots.data?.data ?? []} onPick={(s) => void book(s)} busyId={busyId} actionLabel="Book" />
        )}
      </Card>

      <Card title="Feedback history">
        {history.length ? (
          <ul className="space-y-4">
            {history.map((b) => (
              <li key={b.id} className="space-y-2 border-b border-line pb-4 last:border-0">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-fg">
                    {formatDateTime(b.starts_at)} · {KIND_LABEL[b.session_kind] ?? b.session_kind}
                  </span>
                  <BookingBadge status={b.status} />
                  {b.credit_restored ? <Badge tone="success">Credit restored</Badge> : null}
                </div>
                {b.status === "mentor_no_show" ? <p className="text-sm text-fg-secondary">Sorry — your mentor couldn&apos;t make it. The session credit is back in your account.</p> : null}
                {b.feedback ? <FeedbackView feedback={b.feedback} /> : b.status === "completed" ? <p className="text-sm text-fg-muted">Feedback arrives within 48 h.</p> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">Feedback from past sessions appears here.</p>
        )}
      </Card>

      <Dialog
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        title="Cancel this session?"
        description={cancelling && freeChange(cancelling) ? "You'll get the session credit back." : "It's less than 12 h away, so the session credit will be used."}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCancelling(null)}>
              Keep session
            </Button>
            <Button variant="danger" loading={busyId === cancelling?.id} onClick={() => void cancel()}>
              Cancel session
            </Button>
          </>
        }
      />
      <Dialog
        open={moving !== null}
        onClose={() => setMoving(null)}
        title="Pick a new time"
        description={moving && freeChange(moving) ? "Moving at least 12 h ahead keeps your credit." : "It's less than 12 h away: moving uses a new session credit."}
      >
        <SlotPicker slots={(slots.data?.data ?? []).filter((s) => s.id !== moving?.slot_id)} onPick={(s) => void reschedule(s)} busyId={busyId} actionLabel="Move here" />
      </Dialog>
    </div>
  );
}
