"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button, Card, ErrorState, FormField, PageHeader, Select, Skeleton } from "@/components/ui";
import { uuid7 } from "@/lib/ids/uuid7";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { difficultyRange, practiceApi } from "../lib/api";
import type { Difficulty, PracticeStartBody, TaxonomyNode } from "../lib/types";
import { isEntitlementError, PaywallCard, RecommendationsPanel } from "./shared";

export const DIFFICULTIES: { value: "" | Difficulty; label: string }[] = [
  { value: "", label: "Mixed (adaptive)" },
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
];

/** Start a practice set (PLC-19) and open it. Shared by the hub, subject page and recommendations. */
export function useStartPractice() {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  const start = async (body: PracticeStartBody) => {
    setStarting(true);
    setError(null);
    key.current ??= uuid7();
    try {
      const s = await practiceApi.startSession(body, key.current);
      key.current = null;
      router.push(`/app/practice/sessions/${encodeURIComponent(s.session_id)}`);
    } catch (e) {
      key.current = null;
      setError(e);
    } finally {
      setStarting(false);
    }
  };
  return { start, starting, error };
}

export function TopicPicker({ subjects, initialSubjectId }: { subjects: TaxonomyNode[]; initialSubjectId?: string }) {
  const [subjectId, setSubjectId] = useState(initialSubjectId ?? subjects[0]?.id ?? "");
  const [topicId, setTopicId] = useState("");
  const [difficulty, setDifficulty] = useState<"" | Difficulty>("");
  const { start, starting, error } = useStartPractice();
  const subject = subjects.find((s) => s.id === subjectId);
  const topics = subject?.children ?? [];

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        // A subject is the root topic of its tree, so "All topics" practises the whole subject.
        void start({ mode: "topic_set", topic_id: topicId || subjectId, ...difficultyRange(difficulty || null) });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        {!initialSubjectId ? (
          <FormField label="Subject">
            {(p) => (
              <Select
                {...p}
                value={subjectId}
                onChange={(e) => {
                  setSubjectId(e.target.value);
                  setTopicId("");
                }}
                options={subjects.map((s) => ({ value: s.id, label: s.name }))}
              />
            )}
          </FormField>
        ) : null}
        <FormField label="Topic">
          {(p) => (
            <Select
              {...p}
              value={topicId}
              onChange={(e) => setTopicId(e.target.value)}
              options={[{ value: "", label: "All topics" }, ...topics.map((t) => ({ value: t.id, label: `${t.name} (${t.question_count})` }))]}
            />
          )}
        </FormField>
        <FormField label="Difficulty">
          {(p) => <Select {...p} value={difficulty} onChange={(e) => setDifficulty(e.target.value as "" | Difficulty)} options={DIFFICULTIES} />}
        </FormField>
      </div>
      {error ? isEntitlementError(error) ? <PaywallCard error={error} /> : <ErrorState error={error} /> : null}
      <Button type="submit" loading={starting} disabled={!subjectId}>
        Start 10-question set
      </Button>
    </form>
  );
}

/** PRC-001 Practice hub. */
export function PracticeHub() {
  const subjects = useLoader("subjects", () => practiceApi.subjects());
  const { start } = useStartPractice();

  return (
    <div>
      <PageHeader
        title="Practice"
        description="Pattern-aligned practice with instant feedback and step-by-step explanations."
        actions={
          <Link className="text-sm text-fg-link underline" href="/app/practice/review">
            Review incorrect &amp; bookmarked
          </Link>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Card title="Start a practice set">
            {subjects.error ? (
              <ErrorState error={subjects.error} onRetry={() => void subjects.reload()} />
            ) : !subjects.data ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <TopicPicker subjects={subjects.data} />
            )}
          </Card>
          {subjects.data?.length ? (
            <Card title="Subjects">
              <ul className="grid gap-3 sm:grid-cols-2">
                {subjects.data.map((s) => (
                  <li key={s.id}>
                    <Link
                      href={`/app/practice/${encodeURIComponent(s.slug)}`}
                      className="block rounded-lg border border-line p-4 hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none"
                    >
                      <span className="font-medium text-fg">{s.name}</span>
                      <span className="mt-1 block text-sm text-fg-muted">
                        {s.children.length} topics · {s.question_count} questions
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
        <RecommendationsPanel onStart={(s) => void start(s)} />
      </div>
    </div>
  );
}
