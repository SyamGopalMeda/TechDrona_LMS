"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, FormField, Input } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { formatWhen, TYPE_LABEL } from "../lib/labels";
import type { JoinPreview, MyRun } from "../lib/types";
import { Loading, StatusBadge } from "./parts";

const CODE_RE = /^[A-HJKMNP-Z2-9]{8}$/;

export function normalizeCode(v: string): string {
  return v.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

/** STU-030 learner Engage: join with a code + runs I joined. */
export function LearnerEngage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const runs = useApi<{ data: MyRun[] }>("engage/me/runs");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const c = normalizeCode(code);
    if (!CODE_RE.test(c)) {
      setError("Enter the 8-character code shown by your host.");
      return;
    }
    router.push(`/app/engage/join/${c}`);
  };

  return (
    <div className="space-y-6">
      <Card title="Join with a code">
        <form onSubmit={submit} noValidate className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div className="sm:w-72">
            <FormField label="Join code" error={error ?? undefined} hint="8 letters and numbers, e.g. AB3K7QXZ">
              {(p) => (
                <Input
                  {...p}
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  maxLength={12}
                  className="font-mono uppercase tracking-widest"
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value);
                    setError(null);
                  }}
                />
              )}
            </FormField>
          </div>
          <Button type="submit" className="sm:mt-7">
            Continue
          </Button>
        </form>
      </Card>

      <section aria-labelledby="my-runs">
        <h2 id="my-runs" className="mb-3 font-display text-lg font-semibold text-fg">
          Activities you joined
        </h2>
        {runs.loading && !runs.data ? (
          <Loading label="Loading your activities" rows={2} />
        ) : runs.error ? (
          <ErrorState error={runs.error} onRetry={() => void runs.reload()} />
        ) : !runs.data?.data.length ? (
          <EmptyState title="Nothing yet" description="When your trainer runs a live poll or quiz, enter the code above or scan the QR code." />
        ) : (
          <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
            {runs.data.data.map((r) => (
              <li key={r.run_id}>
                <Link href={`/app/engage/runs/${seg(r.run_id)}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-surface-hover focus-visible:outline-none focus-visible:shadow-focus">
                  <span className="min-w-0">
                    <span className="block font-medium text-fg">{r.title}</span>
                    <span className="block text-xs text-fg-muted">
                      {TYPE_LABEL[r.activity_type]} · joined {formatWhen(r.joined_at)}
                    </span>
                  </span>
                  <span className="flex gap-2">
                    {r.results_published ? <Badge tone="success">Results out</Badge> : null}
                    <StatusBadge status={r.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Problem → user message for joining. */
export function joinErrorMessage(err: unknown): { title: string; detail: string } {
  if (isApiError(err)) {
    switch (err.code) {
      case "permission_denied":
        return { title: "Members only", detail: "This activity is open to members of its batch only." };
      case "participant_limit_reached":
        return { title: "This activity is full", detail: "The host set a participant limit and it has been reached." };
      case "invalid_state_transition":
        return { title: "This activity has ended", detail: "It's no longer accepting participants." };
      case "not_found":
        return { title: "Code not found", detail: "Check the code with your host and try again." };
      case "rate_limited":
        return { title: "Too many attempts", detail: `Please wait${err.retryAfter ? ` ${err.retryAfter} seconds` : " a moment"} and try again.` };
      default:
        return { title: err.title, detail: err.detail };
    }
  }
  return { title: "Something went wrong", detail: "Please try again." };
}

/** STU-031 join preview + join. */
export function JoinRun({ code }: { code: string }) {
  const router = useRouter();
  const c = normalizeCode(code);
  const preview = useApi<JoinPreview>(CODE_RE.test(c) ? `engage/join/${seg(c)}` : null);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<unknown>(null);

  const go = (runId: string) => router.push(`/app/engage/runs/${seg(runId)}?code=${seg(c)}`);

  const join = async () => {
    setJoining(true);
    setJoinError(null);
    try {
      const res = await api.post<{ run_id: string; status: string; joined: boolean }>(`engage/join/${seg(c)}`);
      if (res.kind === "ok") go(res.data.run_id);
    } catch (err) {
      setJoinError(err);
    } finally {
      setJoining(false);
    }
  };

  const back = (
    <Link href="/app/engage" className="text-sm text-fg-link hover:text-fg-link-hover">
      ← Live activities
    </Link>
  );

  if (!CODE_RE.test(c)) {
    return (
      <div className="space-y-4">
        {back}
        <ErrorState title="That code doesn't look right" detail="Join codes have 8 letters and numbers." />
      </div>
    );
  }
  if (preview.loading && !preview.data) return <Loading label="Loading activity" rows={2} />;
  if (preview.error || !preview.data) {
    const m = joinErrorMessage(preview.error);
    return (
      <div className="space-y-4">
        {back}
        <ErrorState title={m.title} detail={m.detail} onRetry={() => void preview.reload()} />
      </div>
    );
  }
  const p = preview.data;
  const ended = p.status === "closed" || p.status === "finalised";
  const jm = joinError ? joinErrorMessage(joinError) : null;
  return (
    <div className="mx-auto max-w-xl space-y-4">
      {back}
      <Card>
        <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{TYPE_LABEL[p.activity_type]}</p>
        <h1 className="mt-1 break-words font-display text-2xl font-bold text-fg">{p.title}</h1>
        {p.description ? <p className="mt-2 text-sm text-fg-secondary">{p.description}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusBadge status={p.status} />
          <Badge>{p.identity_mode === "anonymous" ? "Anonymous" : "Named"}</Badge>
        </div>
        <p className="mt-3 text-sm text-fg-secondary">
          {p.identity_mode === "anonymous" ? "Your name won't be shown with your answers." : "Your name will be shown with your answers."}
        </p>
        <div className="mt-5">
          {p.joined ? (
            <Button onClick={() => go(p.run_id)}>Continue</Button>
          ) : !p.eligible ? (
            <ErrorState title="Members only" detail="This activity is open to members of its batch only." />
          ) : ended ? (
            <ErrorState title="This activity has ended" detail="It's no longer accepting participants." />
          ) : (
            <Button onClick={() => void join()} loading={joining}>
              Join
            </Button>
          )}
        </div>
        {jm ? (
          <div className="mt-4">
            <ErrorState title={jm.title} detail={jm.detail} />
          </div>
        ) : null}
      </Card>
    </div>
  );
}
