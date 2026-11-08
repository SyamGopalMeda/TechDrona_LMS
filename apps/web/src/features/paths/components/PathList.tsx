"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Dialog, EmptyState, FormField, Input, Select, useToast } from "@/components/ui";
import { AIErrorState, aiProblemCode, useEnabledApps } from "@/features/ai";
import { isApiError } from "@/lib/api/errors";
import { Boundary, TextArea, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { pathsApi } from "../lib/api";
import { formatHours } from "../lib/pace";
import type { Level, PathSummary, PathsContext } from "../lib/types";
import { usePathsBase } from "../lib/base";

const LEVELS: { value: Level; label: string }[] = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];

export function usePathsContext() {
  return useApi<PathsContext>("paths/context");
}

/** Trainer "Learning paths" list (cards + search + New / Generate with AI). */
export function PathList() {
  const ctx = usePathsContext();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const enabled = useEnabledApps();
  const pathsOn = enabled.isEnabled("paths");
  const aiOn = pathsOn && enabled.isEnabled("ai_generation");

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const list = useApi<{ data: PathSummary[] }>(ctx.data?.can_author ? "paths" : null, { q: query || undefined });

  return (
    <Boundary state={ctx}>
      {(c) =>
        !c.can_author ? (
          <EmptyState title="You can't author paths yet" description="Ask an admin to give you trainer access to a batch." />
        ) : (
          <div className="space-y-4">
            {!pathsOn ? (
              <p role="status" className="rounded-lg border border-line bg-surface-sunken p-3 text-sm text-fg-secondary">
                Learning paths are turned off. Ask an admin to enable the app.
              </p>
            ) : null}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-3 sm:flex-row">
                <FormField label="Search paths">{(p) => <Input {...p} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search paths…" />}</FormField>
              </div>
              <div className="flex flex-wrap gap-2">
                {aiOn ? (
                  <Button variant="secondary" onClick={() => setAiOpen(true)}>
                    <span aria-hidden="true">✦</span> Generate with AI
                  </Button>
                ) : null}
                <Button onClick={() => setNewOpen(true)}>+ New path</Button>
              </div>
            </div>
            <Boundary state={list}>
              {(l) =>
                l.data.length === 0 ? (
                  <EmptyState title="No learning paths yet" description="Create a path by hand or let AI draft the structure for you to review." />
                ) : (
                  <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {l.data.map((p) => (
                      <li key={p.id}>
                        <PathCard p={p} />
                      </li>
                    ))}
                  </ul>
                )
              }
            </Boundary>
            <NewPathDialog open={newOpen} onClose={() => setNewOpen(false)} />
            <AIGenerateDialog open={aiOpen} onClose={() => setAiOpen(false)} />
          </div>
        )
      }
    </Boundary>
  );
}

function PathCard({ p }: { p: PathSummary }) {
  const base = usePathsBase();
  return (
    <article className="flex h-full flex-col rounded-xl border border-line bg-surface p-4 shadow-xs">
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-display text-base font-semibold text-fg">{p.title}</h2>
        <Badge tone={p.status === "published" ? "success" : "neutral"}>{p.status === "published" ? `Published v${p.version_no}` : p.status === "archived" ? "Archived" : "Draft"}</Badge>
      </div>
      {p.description_md ? <p className="mt-1 line-clamp-3 text-sm text-fg-muted">{p.description_md}</p> : null}
      <p className="mt-3 text-xs text-fg-secondary">
        {p.step_count} steps · {p.total_credits} credits · {formatHours(p.total_hours)}
        {p.has_unpublished_changes && p.status === "published" ? " · unpublished changes" : ""}
        {p.source === "ai" ? " · AI draft" : ""}
      </p>
      <div className="mt-auto pt-4">
        <Link href={`${base}/${encodeURIComponent(p.id)}`} className="inline-flex h-8 items-center rounded-md border border-line-control px-3 text-sm font-medium hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none">
          Open<span className="sr-only"> {p.title}</span>
        </Link>
      </div>
    </article>
  );
}

function NewPathDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const base = usePathsBase();
  const router = useRouter();
  const fail = useFailToast();
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const submit = async () => {
    setBusy(true);
    setErrs({});
    try {
      const p = await pathsApi.createPath({ title: title.trim(), description_md: desc.trim() || undefined });
      router.push(`${base}/${encodeURIComponent(p.id)}`);
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) setErrs(fe);
      else fail(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="New learning path"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy} disabled={!title.trim()}>
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Title" required error={errs.title}>{(p) => <Input {...p} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />}</FormField>
        <FormField label="Description" error={errs.description_md}>{(p) => <TextArea {...p} value={desc} rows={3} onChange={(e) => setDesc(e.target.value)} />}</FormField>
      </div>
    </Dialog>
  );
}

export function AIGenerateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const base = usePathsBase();
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState<"mixed" | "textbook">("mixed");
  const [level, setLevel] = useState<Level>("beginner");
  const [hours, setHours] = useState("20");
  const [steps, setSteps] = useState("8");
  const [guidelines, setGuidelines] = useState("");
  const [busy, setBusy] = useState(false);
  const [aiErr, setAiErr] = useState<{ code: string; detail: string | null } | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const submit = async () => {
    setBusy(true);
    setAiErr(null);
    setErrs({});
    try {
      const p = await pathsApi.aiGenerate({
        topic: topic.trim(),
        style,
        level,
        target_hours: Number(hours),
        approx_steps: Number(steps),
        guidelines: guidelines.trim() || undefined,
      });
      toast.show({ tone: "success", title: "AI path drafted — review it and attach content." });
      router.push(`${base}/${encodeURIComponent(p.id)}`);
    } catch (e) {
      const code = aiProblemCode(e);
      if (code) setAiErr({ code, detail: isApiError(e) ? (e.problem?.detail ?? null) : null });
      else {
        const fe = fieldErrorsOf(e);
        if (Object.keys(fe).length) setErrs(fe);
        else fail(e);
      }
    } finally {
      setBusy(false);
    }
  };

  const styleCard = (value: "mixed" | "textbook", title: string, hint: string) => (
    <label className={`flex cursor-pointer flex-col rounded-lg border p-3 ${style === value ? "border-brand bg-brand-subtle" : "border-line"}`}>
      <span className="flex items-center gap-2 text-sm font-semibold">
        <input type="radio" name="path-style" value={value} checked={style === value} onChange={() => setStyle(value)} />
        {title}
      </span>
      <span className="mt-1 text-xs text-fg-muted">{hint}</span>
    </label>
  );

  const valid = topic.trim().length > 1 && Number(hours) > 0 && Number(steps) > 0;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="Generate a path with AI"
      description="AI drafts the path structure. You review it, attach the actual content and allocate it afterwards — nothing is published automatically."
      className="max-w-xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy} disabled={!valid}>
            <span aria-hidden="true">✦</span> Generate
          </Button>
        </>
      }
    >
      {busy ? (
        <div aria-live="polite" className="space-y-2 rounded-lg border border-line p-4">
          <p className="text-sm font-medium">Designing your path… reading your guidelines.</p>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-brand motion-reduce:animate-none" />
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {aiErr ? <AIErrorState code={aiErr.code} detail={aiErr.detail} onRetry={() => void submit()} /> : null}
            <FormField label="Topic / goal" required error={errs.topic}>{(p) => <Input {...p} value={topic} maxLength={200} placeholder="Core Python" onChange={(e) => setTopic(e.target.value)} />}</FormField>
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Path style</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {styleCard("mixed", "Mixed", "Videos, readings, articles, assignments and assessments")}
              {styleCard("textbook", "Textbook", "Every step is a written chapter, in order")}
            </div>
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-3">
            <FormField label="Level">{(p) => <Select {...p} value={level} onChange={(e) => setLevel(e.target.value as Level)} options={LEVELS} />}</FormField>
            <FormField label="Target total hours" error={errs.target_hours}>{(p) => <Input {...p} type="number" min={1} max={500} value={hours} onChange={(e) => setHours(e.target.value)} />}</FormField>
            <FormField label="Approx steps" error={errs.approx_steps}>{(p) => <Input {...p} type="number" min={1} max={60} value={steps} onChange={(e) => setSteps(e.target.value)} />}</FormField>
          </div>
          <FormField label="Guidelines (optional)" hint="Each step's depth follows its hours and your guidelines.">
            {(p) => <TextArea {...p} rows={3} maxLength={4000} value={guidelines} onChange={(e) => setGuidelines(e.target.value)} />}
          </FormField>
        </div>
      )}
    </Dialog>
  );
}
