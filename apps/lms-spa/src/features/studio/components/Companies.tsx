"use client";

import { useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, FormField, Input, PageHeader, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { useApiAll, useApi, seg, type SendBody } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, TextArea, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import type { TestSummary } from "@/features/trainer/lib/types";
import { slugify } from "./Courses";
import { RefSelect, TopicSelect, useTopics } from "./Pickers";

/** PLC-16 item: `company_out` + `paths` (`path_out`). verified: app/modules/placement/bank.py */
export interface CompanyPathOut {
  id: string;
  company_id: string;
  organization_id: string | null;
  role_name: string;
  version_no: number;
  status: "draft" | "published" | "retired" | string;
  pattern: { section: string; topic_id: string; weight: string | number; minutes?: number | null; question_count?: number | null }[];
  published_at: string | null;
  steps: { id: string; position: number; step_type: string; title: string; topic_id: string | null; test_id: string | null; lesson_key: string | null; is_required: boolean }[];
}

export interface CompanyOut {
  id: string;
  slug: string;
  name: string;
  industry: string | null;
  hub_status: "draft" | "published" | "archived" | string;
  description_md: string | null;
  paths: CompanyPathOut[];
}

type PathBody = Body<"studio/company-paths/{company_path_id}", "put">;
type StepType = "practice_set" | "test" | "coding_set" | "lesson";

interface SectionRow {
  section: string;
  topic_id: string;
  weight: string;
  minutes: string;
  question_count: string;
}
interface StepRow {
  step_type: StepType;
  title: string;
  topic_id: string;
  test_id: string;
  /** Lesson steps are kept as they are (no lesson picker here). */
  lesson_key?: string;
  is_required: boolean;
}
interface PathForm {
  id: string | null;
  company_id: string;
  role_name: string;
  status: "draft" | "published" | "retired";
  pattern: SectionRow[];
  steps: StepRow[];
}

const emptySection = (): SectionRow => ({ section: "", topic_id: "", weight: "", minutes: "", question_count: "" });
const emptyStep = (): StepRow => ({ step_type: "practice_set", title: "", topic_id: "", test_id: "", is_required: true });

/** Client checks mirroring CompanyPathPut (placement/schemas.py) before the PUT. */
export function validatePath(f: PathForm): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.role_name.trim()) e.role_name = "Enter the role (e.g. Graduate Engineer Trainee).";
  if (f.pattern.length === 0) e.pattern = "Add at least one exam section.";
  f.pattern.forEach((s, i) => {
    if (!s.section.trim()) e[`pattern.${i}.section`] = "Name the section.";
    if (!s.topic_id) e[`pattern.${i}.topic_id`] = "Choose a topic.";
    const w = Number(s.weight);
    if (!(w > 0 && w <= 100)) e[`pattern.${i}.weight`] = "Weight between 0 and 100.";
  });
  f.steps.forEach((s, i) => {
    if (!s.title.trim()) e[`steps.${i}.title`] = "Name the step.";
    if (s.step_type === "lesson") return;
    if (s.step_type === "test" ? !s.test_id : !s.topic_id) e[`steps.${i}.ref`] = s.step_type === "test" ? "Choose a test." : "Choose a topic.";
  });
  return e;
}

export function pathBody(f: PathForm): PathBody {
  return {
    company_id: f.company_id,
    organization_id: null,
    role_name: f.role_name.trim(),
    status: f.status,
    pattern: f.pattern.map((s) => ({
      section: s.section.trim(),
      topic_id: s.topic_id,
      weight: s.weight,
      ...(s.minutes ? { minutes: Number(s.minutes) } : {}),
      ...(s.question_count ? { question_count: Number(s.question_count) } : {}),
    })) as PathBody["pattern"],
    steps: f.steps.map((s) => ({
      step_type: s.step_type,
      title: s.title.trim(),
      is_required: s.is_required,
      ...(s.step_type === "lesson" ? { lesson_key: s.lesson_key } : s.step_type === "test" ? { test_id: s.test_id } : { topic_id: s.topic_id }),
    })) as PathBody["steps"],
  };
}

function newId(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * CMS-009 companies and company paths (audit ADM-50 / INV-13): PLC-16 list, PLC-17 create,
 * PLC-18 put a role path (exam pattern by topic + ordered prep steps). Platform paths only.
 */
export function CompaniesManager({ header }: { header?: { title: string; description?: string } } = {}) {
  const toast = useToast();
  const fail = useFailToast();
  const companies = useApi<{ items: CompanyOut[] }>("studio/companies");
  const topics = useTopics();
  const tests = useApiAll<TestSummary>("studio/tests");
  const testOptions = { data: tests.data?.items.map((t) => ({ id: t.id, label: `${t.title} (${t.status})` })), loading: tests.loading, error: tests.error, reload: tests.reload };

  const [companyOpen, setCompanyOpen] = useState(false);
  const [c, setC] = useState({ name: "", slug: "", industry: "", hub_status: "draft" as "draft" | "published" | "archived", description_md: "" });
  const [path, setPath] = useState<PathForm | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const createCompany = async () => {
    const e: Record<string, string> = {};
    if (!c.name.trim()) e.name = "Enter the company name.";
    if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(c.slug)) e.slug = "Lowercase letters, numbers and dashes.";
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      await api.post(
        "studio/companies",
        { name: c.name.trim(), slug: c.slug, industry: c.industry.trim() || null, hub_status: c.hub_status, description_md: c.description_md.trim() || null } satisfies SendBody<"studio/companies", "post">,
        { idempotencyKey: true },
      );
      toast.show({ tone: "success", title: "Company added" });
      setCompanyOpen(false);
      setC({ name: "", slug: "", industry: "", hub_status: "draft", description_md: "" });
      await companies.reload();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't add the company");
    } finally {
      setBusy(false);
    }
  };

  const openPath = (companyId: string, p?: CompanyPathOut) => {
    setErrors({});
    setPath(
      p
        ? {
            id: p.id,
            company_id: companyId,
            role_name: p.role_name,
            status: (p.status as PathForm["status"]) ?? "draft",
            pattern: p.pattern.map((s) => ({ section: s.section, topic_id: s.topic_id, weight: String(s.weight), minutes: s.minutes ? String(s.minutes) : "", question_count: s.question_count ? String(s.question_count) : "" })),
            steps: p.steps.map((s) => ({
              step_type: s.step_type as StepType,
              title: s.title,
              topic_id: s.topic_id ?? "",
              test_id: s.test_id ?? "",
              ...(s.lesson_key ? { lesson_key: s.lesson_key } : {}),
              is_required: s.is_required,
            })),
          }
        : { id: null, company_id: companyId, role_name: "", status: "draft", pattern: [emptySection()], steps: [] },
    );
  };

  const savePath = async () => {
    if (!path) return;
    const e = validatePath(path);
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      await api.put(`studio/company-paths/${seg(path.id ?? newId())}`, pathBody(path));
      toast.show({ tone: "success", title: "Company path saved" });
      setPath(null);
      await companies.reload();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't save the path");
    } finally {
      setBusy(false);
    }
  };

  const updSection = (i: number, patch: Partial<SectionRow>) => setPath((p) => (p ? { ...p, pattern: p.pattern.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : p));
  const updStep = (i: number, patch: Partial<StepRow>) => setPath((p) => (p ? { ...p, steps: p.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) } : p));

  return (
    <div className="space-y-4">
      {(() => {
        const newCompany = (
          <Button
            onClick={() => {
              setErrors({});
              setCompanyOpen(true);
            }}
          >
            New company
          </Button>
        );
        return header ? <PageHeader title={header.title} description={header.description} actions={newCompany} /> : <div className="flex justify-end">{newCompany}</div>;
      })()}
      <Boundary state={companies}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title="No companies yet" description="Add a company, then describe its hiring pattern and prep path." />
          ) : (
            <div className="space-y-4">
              {data.items.map((co) => (
                <Card
                  key={co.id}
                  title={
                    <span className="inline-flex items-center gap-2">
                      {co.name} <StatusBadge status={co.hub_status} />
                    </span>
                  }
                  actions={
                    <Button size="sm" variant="secondary" onClick={() => openPath(co.id)}>
                      New role path
                    </Button>
                  }
                >
                  <p className="mb-2 text-sm text-fg-muted">
                    <span className="font-mono">{co.slug}</span>
                    {co.industry ? ` · ${co.industry}` : ""}
                  </p>
                  {co.paths.length === 0 ? (
                    <p className="text-sm text-fg-muted">No role paths yet.</p>
                  ) : (
                    <ul className="space-y-1 text-sm">
                      {co.paths.map((p) => (
                        <li key={p.id} className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{p.role_name}</span>
                          <Badge>v{p.version_no}</Badge>
                          <StatusBadge status={p.status} />
                          <span className="text-fg-muted">
                            {p.pattern.length} section{p.pattern.length === 1 ? "" : "s"} · {p.steps.length} step{p.steps.length === 1 ? "" : "s"}
                          </span>
                          <Button size="sm" variant="ghost" onClick={() => openPath(co.id, p)} aria-label={`Edit ${co.name} ${p.role_name}`}>
                            Edit
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              ))}
            </div>
          )
        }
      </Boundary>

      <Dialog
        open={companyOpen}
        onClose={() => setCompanyOpen(false)}
        dismissible={!busy}
        title="New company"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCompanyOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button loading={busy} onClick={() => void createCompany()}>
              Add company
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Name" required error={errors.name}>
            {(p) => (
              <Input
                {...p}
                value={c.name}
                onChange={(e) => {
                  const name = e.target.value;
                  setC((x) => ({ ...x, name, slug: !x.slug || x.slug === slugify(x.name).slice(0, 63) ? slugify(name).slice(0, 63) : x.slug }));
                }}
              />
            )}
          </FormField>
          <FormField label="Slug" required error={errors.slug}>
            {(p) => <Input {...p} className="font-mono" value={c.slug} onChange={(e) => setC((x) => ({ ...x, slug: e.target.value }))} />}
          </FormField>
          <FormField label="Industry" error={errors.industry}>
            {(p) => <Input {...p} value={c.industry} onChange={(e) => setC((x) => ({ ...x, industry: e.target.value }))} />}
          </FormField>
          <FormField label="Hub status">
            {(p) => (
              <Select
                {...p}
                value={c.hub_status}
                onChange={(e) => setC((x) => ({ ...x, hub_status: e.target.value as typeof x.hub_status }))}
                options={[
                  { value: "draft", label: "Draft" },
                  { value: "published", label: "Published" },
                  { value: "archived", label: "Archived" },
                ]}
              />
            )}
          </FormField>
          <FormField label="Description" error={errors.description_md}>
            {(p) => <TextArea {...p} rows={4} value={c.description_md} onChange={(e) => setC((x) => ({ ...x, description_md: e.target.value }))} />}
          </FormField>
        </div>
      </Dialog>

      <Dialog
        open={path !== null}
        onClose={() => setPath(null)}
        dismissible={!busy}
        title={path?.id ? "Edit role path" : "New role path"}
        className="max-w-3xl"
        footer={
          <>
            <Button variant="secondary" onClick={() => setPath(null)} disabled={busy}>
              Cancel
            </Button>
            <Button loading={busy} onClick={() => void savePath()}>
              Save path
            </Button>
          </>
        }
      >
        {path ? (
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <FormField label="Role" required error={errors.role_name}>
                {(p) => <Input {...p} value={path.role_name} onChange={(e) => setPath({ ...path, role_name: e.target.value })} />}
              </FormField>
              <FormField label="Status">
                {(p) => (
                  <Select
                    {...p}
                    value={path.status}
                    onChange={(e) => setPath({ ...path, status: e.target.value as PathForm["status"] })}
                    options={[
                      { value: "draft", label: "Draft" },
                      { value: "published", label: "Published" },
                      { value: "retired", label: "Retired" },
                    ]}
                  />
                )}
              </FormField>
            </div>
            <fieldset className="space-y-2">
              <legend className="font-medium text-fg">Exam pattern</legend>
              {errors.pattern ? (
                <p role="alert" className="text-sm text-danger-fg">
                  {errors.pattern}
                </p>
              ) : null}
              {path.pattern.map((s, i) => (
                <div key={i} className="grid gap-2 rounded-md border border-line p-2 md:grid-cols-5">
                  <FormField label="Section" required error={errors[`pattern.${i}.section`]}>
                    {(p) => <Input {...p} value={s.section} onChange={(e) => updSection(i, { section: e.target.value })} />}
                  </FormField>
                  <div className="md:col-span-2">
                    <FormField label="Topic" required error={errors[`pattern.${i}.topic_id`]}>
                      {(p) => <TopicSelect {...p} topics={topics} value={s.topic_id} onChange={(e) => updSection(i, { topic_id: e.target.value })} />}
                    </FormField>
                  </div>
                  <FormField label="Weight %" required error={errors[`pattern.${i}.weight`]}>
                    {(p) => <Input {...p} inputMode="decimal" value={s.weight} onChange={(e) => updSection(i, { weight: e.target.value })} />}
                  </FormField>
                  <FormField label="Minutes" error={errors[`pattern.${i}.minutes`]}>
                    {(p) => <Input {...p} inputMode="numeric" value={s.minutes} onChange={(e) => updSection(i, { minutes: e.target.value })} />}
                  </FormField>
                  <FormField label="Questions" error={errors[`pattern.${i}.question_count`]}>
                    {(p) => <Input {...p} inputMode="numeric" value={s.question_count} onChange={(e) => updSection(i, { question_count: e.target.value })} />}
                  </FormField>
                  <div className="self-end">
                    <Button size="sm" variant="ghost" disabled={path.pattern.length === 1} onClick={() => setPath({ ...path, pattern: path.pattern.filter((_, j) => j !== i) })}>
                      Remove section
                    </Button>
                  </div>
                </div>
              ))}
              <Button size="sm" variant="secondary" disabled={path.pattern.length >= 20} onClick={() => setPath({ ...path, pattern: [...path.pattern, emptySection()] })}>
                Add section
              </Button>
            </fieldset>
            <fieldset className="space-y-2">
              <legend className="font-medium text-fg">Prep steps</legend>
              {path.steps.map((s, i) => (
                <div key={i} className="grid gap-2 rounded-md border border-line p-2 md:grid-cols-4">
                  <FormField label="Kind">
                    {(p) => (
                      <Select
                        {...p}
                        value={s.step_type}
                        disabled={s.step_type === "lesson"}
                        onChange={(e) => updStep(i, { step_type: e.target.value as StepType, topic_id: "", test_id: "" })}
                        options={[
                          { value: "practice_set", label: "Practice set (topic)" },
                          { value: "coding_set", label: "Coding set (topic)" },
                          { value: "test", label: "Test" },
                          ...(s.step_type === "lesson" ? [{ value: "lesson", label: "Lesson (kept as linked)" }] : []),
                        ]}
                      />
                    )}
                  </FormField>
                  <FormField label="Title" required error={errors[`steps.${i}.title`]}>
                    {(p) => <Input {...p} value={s.title} onChange={(e) => updStep(i, { title: e.target.value })} />}
                  </FormField>
                  <FormField label={s.step_type === "test" ? "Test" : "Topic"} required error={errors[`steps.${i}.ref`] ?? errors[`steps.${i}.topic_id`] ?? errors[`steps.${i}.test_id`]}>
                    {(p) =>
                      s.step_type === "lesson" ? (
                        <p className="text-sm text-fg-muted">Linked course lesson</p>
                      ) : s.step_type === "test" ? (
                        <RefSelect {...p} noun="test" state={testOptions} value={s.test_id} onChange={(e) => updStep(i, { test_id: e.target.value })} />
                      ) : (
                        <TopicSelect {...p} topics={topics} value={s.topic_id} onChange={(e) => updStep(i, { topic_id: e.target.value })} />
                      )
                    }
                  </FormField>
                  <div className="self-end">
                    <Button size="sm" variant="ghost" onClick={() => setPath({ ...path, steps: path.steps.filter((_, j) => j !== i) })}>
                      Remove step
                    </Button>
                  </div>
                </div>
              ))}
              <Button size="sm" variant="secondary" disabled={path.steps.length >= 200} onClick={() => setPath({ ...path, steps: [...path.steps, emptyStep()] })}>
                Add step
              </Button>
            </fieldset>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}
