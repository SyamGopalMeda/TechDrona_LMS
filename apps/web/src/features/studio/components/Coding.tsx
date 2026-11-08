"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button, Card, Dialog, FormField, Input, Select, Table, useToast } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg, type ApiState, type SendBody } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, TextArea, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { slugify } from "./Courses";
import type { Body } from "@/lib/api-types";
import { readText } from "@/lib/files/readText";
import type { CodingProblem, CodingProblemSummary, HiddenCaseContentLinks, ProblemValidation, ReferenceSolution, TestCase, ValidationCase } from "../lib/types";

/** Coding problems in scope (`GET /studio/coding/problems`, envelope `{data, meta}`) + create (COD-13). */
export function CodingProblemList() {
  const router = useRouter();
  const fail = useFailToast();
  const list = useApi<{ data: CodingProblemSummary[]; meta: Page<unknown>["page"] }>("studio/coding/problems", { limit: 100 });
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [statement, setStatement] = useState("");
  const [difficulty, setDifficulty] = useState("3");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [statementError, setStatementError] = useState<string | undefined>();

  const create = async () => {
    setError(title.trim().length < 3 ? "Enter a title (at least 3 characters)." : undefined);
    setStatementError(statement.trim() ? undefined : "Write the problem statement.");
    if (title.trim().length < 3 || !statement.trim()) return;
    setBusy(true);
    try {
      const res = await api.post<CodingProblem>("studio/coding/problems", {
        title: title.trim(),
        slug: slugify(title),
        statement_md: statement,
        difficulty: Number(difficulty),
      } satisfies SendBody<"studio/coding/problems", "post">);
      if (res.kind === "ok") router.push(`/studio/coding/${seg(res.data.problem_id)}`);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (fe.title || fe.slug || fe.statement_md) {
        setError(fe.title ?? fe.slug);
        setStatementError(fe.statement_md);
      } else fail(err, "Couldn't create the problem");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}>New problem</Button>
      </div>
      <Table
        caption="Coding problems"
        columns={[
          {
            key: "t",
            header: "Problem",
            cell: (p: CodingProblemSummary) => (
              <Link className="text-fg-link underline" href={`/studio/coding/${seg(p.problem_id)}`}>
                {p.title}
              </Link>
            ),
          },
          { key: "d", header: "Difficulty", cell: (p) => p.difficulty },
          { key: "s", header: "Status", cell: (p) => <StatusBadge status={p.status} /> },
          { key: "c", header: "Cases", cell: (p) => `${p.test_cases.sample} sample · ${p.test_cases.hidden} hidden` },
          { key: "v", header: "Version", cell: (p) => p.version_no },
        ]}
        rows={list.data?.data}
        rowKey={(p) => p.problem_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No coding problems yet" }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        dismissible={!busy}
        title="New coding problem"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void create()} loading={busy}>
              Create draft
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Title" required error={error}>
            {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
          </FormField>
          <FormField label="Statement (Markdown)" required error={statementError}>
            {(p) => <TextArea {...p} rows={5} className="font-mono" value={statement} onChange={(e) => setStatement(e.target.value)} />}
          </FormField>
          <FormField label="Difficulty">
            {(p) => <Select {...p} value={difficulty} onChange={(e) => setDifficulty(e.target.value)} options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />}
          </FormField>
        </div>
      </Dialog>
    </div>
  );
}

/**
 * CMS-010 coding problem editor. COD-14 edit, COD-16 cases (hidden = metadata only),
 * COD-15 add sample / hidden (both sent inline as text, `TestCaseIn`), COD-18 reference
 * solution validation, COD-17 audited hidden-case content links, COD-19 publish (gated
 * server-side on a passing validation of the current case set).
 *
 * Hidden test case data is never rendered here: the file inputs are cleared after upload,
 * the list shows ordinal / weight / size / hash only, and COD-17 hands out single-use
 * download links that are opened directly (content never enters React state).
 */
export function CodingProblemEditor({ problemId }: { problemId: string }) {
  const toast = useToast();
  const fail = useFailToast();
  const problem = useApi<CodingProblem>(`studio/coding/problems/${seg(problemId)}`);
  const cases = useApi<{ problem_version: number; data: TestCase[] }>(`studio/coding/problems/${seg(problemId)}/test-cases`);
  const [f, setF] = useState({ title: "", statement_md: "", difficulty: "3", time_limit_ms: "2000", memory_limit_mb: "256", scoring_mode: "weighted_cases" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const p = problem.data;
  useEffect(() => {
    if (p)
      setF({
        title: p.title,
        statement_md: p.statement_md,
        difficulty: String(p.difficulty),
        time_limit_ms: String(p.limits.time_limit_ms),
        memory_limit_mb: String(Math.round(p.limits.memory_limit_kb / 1024)),
        scoring_mode: p.scoring_mode,
      });
  }, [p]);

  const editable = p?.status !== "in_review" && p?.status !== "retired";
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setErrors({});
    try {
      await fn();
      toast.show({ tone: "success", title: ok });
      await Promise.all([problem.reload(), cases.reload()]);
    } catch (err) {
      if (err instanceof ApiError && err.code === "sod_violation") toast.show({ tone: "warning", title: "A different reviewer must publish this problem", requestId: err.requestId });
      else if (err instanceof ApiError && err.code === "invalid_state_transition" && key === "publish" && problemReason(err) === "validation_required")
        toast.show({
          tone: "warning",
          title: "Validate before publishing",
          description: "Run the reference solution against every test case (Validate). It must pass on the current cases and limits.",
          requestId: err.requestId,
        });
      else if (err instanceof ApiError && err.code === "invalid_state_transition" && key === "publish")
        toast.show({ tone: "warning", title: "Can't publish yet", description: err.detail || "Add at least one sample and one hidden test case first.", requestId: err.requestId });
      else {
        const fe = fieldErrorsOf(err);
        if (Object.keys(fe).length) setErrors(fe);
        else fail(err);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Boundary state={problem}>
      {(prob) => (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={prob.status} />
            <span className="text-sm text-fg-muted">Version {prob.version_no}</span>
          </div>
          <Card title="Statement and limits">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <FormField label="Title" required error={errors.title}>
                  {(pp) => <Input {...pp} value={f.title} disabled={!editable} onChange={set("title")} />}
                </FormField>
              </div>
              <div className="md:col-span-2">
                <FormField label="Statement (Markdown)" error={errors.statement_md}>
                  {(pp) => <TextArea {...pp} rows={10} className="font-mono" value={f.statement_md} disabled={!editable} onChange={set("statement_md")} />}
                </FormField>
              </div>
              <FormField label="Time limit (ms)" error={errors.time_limit_ms}>
                {(pp) => <Input {...pp} type="number" min={100} inputMode="numeric" value={f.time_limit_ms} disabled={!editable} onChange={set("time_limit_ms")} />}
              </FormField>
              <FormField label="Memory limit (MB)" error={errors.memory_limit_mb}>
                {(pp) => <Input {...pp} type="number" min={16} inputMode="numeric" value={f.memory_limit_mb} disabled={!editable} onChange={set("memory_limit_mb")} />}
              </FormField>
              <FormField label="Difficulty">
                {(pp) => <Select {...pp} value={f.difficulty} disabled={!editable} onChange={set("difficulty")} options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />}
              </FormField>
              <FormField label="Scoring">
                {(pp) => (
                  <Select
                    {...pp}
                    value={f.scoring_mode}
                    disabled={!editable}
                    onChange={set("scoring_mode")}
                    options={[
                      { value: "weighted_cases", label: "Sum of passed case weights" },
                      { value: "all_or_nothing", label: "All or nothing" },
                    ]}
                  />
                )}
              </FormField>
            </div>
            {editable ? (
              <Button
                className="mt-4"
                variant="secondary"
                loading={busy === "save"}
                onClick={() =>
                  void run(
                    "save",
                    () =>
                      api.patch(`studio/coding/problems/${seg(problemId)}`, {
                        title: f.title.trim(),
                        statement_md: f.statement_md,
                        difficulty: Number(f.difficulty),
                        time_limit_ms: Number(f.time_limit_ms),
                        memory_limit_kb: Number(f.memory_limit_mb) * 1024,
                        scoring_mode: f.scoring_mode as "weighted_cases" | "all_or_nothing",
                      } satisfies Body<"studio/coding/problems/{problem_id}", "patch">),
                    "Problem saved",
                  )
                }
              >
                Save
              </Button>
            ) : null}
          </Card>
          <TestCases problemId={problemId} state={cases} editable={!!editable} />
          <ValidationPanel problemId={problemId} languages={prob.allowed_languages ?? prob.languages ?? []} editable={!!editable} />
          <div className="flex flex-wrap gap-2">
            <Button
              loading={busy === "publish"}
              disabled={prob.status === "published" || prob.status === "retired" || prob.test_cases.sample === 0 || prob.test_cases.hidden === 0}
              onClick={() => void run("publish", () => api.post(`studio/coding/problems/${seg(problemId)}/publish`, {}), "Problem published")}
            >
              Publish
            </Button>
          </div>
          <p className="text-sm text-fg-muted">Publishing needs a passing validation of the reference solution on the current test cases and limits.</p>
        </div>
      )}
    </Boundary>
  );
}

/** Extension member `reason` of a problem+json error (e.g. `validation_required`). */
function problemReason(err: ApiError): string | undefined {
  const r = (err.problem as unknown as Record<string, unknown> | null)?.reason;
  return typeof r === "string" ? r : undefined;
}

const VERDICT_TONE: Record<string, string> = { AC: "text-success-fg", PARTIAL: "text-warning-fg" };

function Verdict({ v }: { v: string }) {
  return <span className={`font-mono text-xs font-semibold ${VERDICT_TONE[v] ?? "text-danger-fg"}`}>{v}</span>;
}

const STATUS_LABEL: Record<ProblemValidation["status"], string> = { passed: "Passed", failed: "Failed", error: "Error" };

/**
 * COD-18: reference solution editor + validation. The response carries per-case
 * ordinal/verdict/time/memory only (hidden cases are never echoed).
 */
function ValidationPanel({ problemId, languages, editable }: { problemId: string; languages: string[]; editable: boolean }) {
  const toast = useToast();
  const fail = useFailToast();
  const refs = useApi<{ data: ReferenceSolution[] }>(`studio/coding/problems/${seg(problemId)}/reference-solutions`);
  const latest = useApi<ProblemValidation>(`studio/coding/problems/${seg(problemId)}/validation`);
  const [lang, setLang] = useState(languages[0] ?? "");
  const [code, setCode] = useState("");
  const [result, setResult] = useState<ProblemValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = refs.data?.data;
  useEffect(() => {
    if (!lang && languages[0]) setLang(languages[0]);
  }, [lang, languages]);
  useEffect(() => {
    setCode(stored?.find((r) => r.language_key === lang)?.source_code ?? "");
  }, [stored, lang]);

  const shown = result ?? (latest.error ? null : (latest.data ?? null));

  const validate = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = code.trim() ? { reference_solutions: [{ language_key: lang, source_code: code }] } : {};
      const res = await api.post<ProblemValidation>(`studio/coding/problems/${seg(problemId)}/validate`, body);
      if (res.kind === "ok") {
        setResult(res.data);
        const passed = res.data.status === "passed";
        toast.show({ tone: passed ? "success" : "warning", title: passed ? "Validation passed" : "Validation failed" });
        void refs.reload();
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_state_transition") {
        const r = problemReason(err);
        setError(r === "no_reference_solution" ? "Add a reference solution first." : r === "no_test_cases" ? "Add test cases before validating." : err.detail);
      } else if (err instanceof ApiError && err.code === "rate_limited") setError("Validation is limited to 10 runs an hour. Try again later.");
      else fail(err, "Couldn't validate");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Reference solution and validation">
      <p className="mb-3 text-sm text-fg-muted">The reference solution runs against every sample and hidden case. Results show verdicts only.</p>
      <div className="space-y-3">
        <div className="max-w-xs">
          <FormField label="Language">
            {(p) => <Select {...p} value={lang} onChange={(e) => setLang(e.target.value)} options={languages.map((l) => ({ value: l, label: l }))} />}
          </FormField>
        </div>
        <FormField label="Reference solution" hint={stored?.some((r) => r.language_key === lang) ? "Saved solution loaded." : "No saved solution for this language."}>
          {(p) => <TextArea {...p} rows={8} className="font-mono" value={code} disabled={!editable} onChange={(e) => setCode(e.target.value)} />}
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm font-medium text-danger-fg">
          {error}
        </p>
      ) : null}
      <Button className="mt-3" variant="secondary" loading={busy} disabled={!editable || !lang} onClick={() => void validate()}>
        Validate
      </Button>
      <div className="mt-4 border-t border-line pt-4">
        {shown ? (
          <div className="space-y-3">
            <p className="text-sm">
              <strong>{STATUS_LABEL[shown.status] ?? shown.status}</strong> · version {shown.problem_version} · {new Date(shown.validated_at).toLocaleString()}
              {!shown.is_current ? <span className="ml-2 text-warning-fg">Out of date: cases or limits changed since this run.</span> : null}
            </p>
            {shown.detail ? <p className="text-sm text-fg-muted">{shown.detail}</p> : null}
            {shown.solutions.map((sol) => (
              <Table
                key={sol.language_key}
                caption={`Validation results (${sol.language_key}): ${sol.verdict}, ${sol.passed_cases}/${sol.total_cases} cases`}
                columns={[
                  { key: "o", header: "#", cell: (c: ValidationCase) => c.ordinal, align: "right" },
                  { key: "k", header: "Kind", cell: (c) => (c.is_sample ? "Sample" : "Hidden") },
                  { key: "v", header: "Verdict", cell: (c) => <Verdict v={c.verdict} /> },
                  { key: "t", header: "Time", cell: (c) => (c.time_ms == null ? "—" : `${c.time_ms} ms`), align: "right" },
                  { key: "m", header: "Memory", cell: (c) => (c.memory_kb == null ? "—" : `${Math.round(c.memory_kb / 1024)} MB`), align: "right" },
                ]}
                rows={sol.cases}
                rowKey={(c) => String(c.ordinal)}
                empty={{ title: "No cases ran" }}
              />
            ))}
          </div>
        ) : latest.loading ? (
          <p className="text-sm text-fg-muted">Loading the latest validation…</p>
        ) : (
          <p className="text-sm text-fg-muted">Not validated yet.</p>
        )}
      </div>
    </Card>
  );
}

/**
 * COD-17: audited hidden-case access. Needs a reason; step-up is handled by the api client.
 * Returns single-use links valid for 5 minutes, opened directly and never fetched into state.
 */
function HiddenContentDialog({ testCase, onClose }: { testCase: HiddenCase | null; onClose: () => void }) {
  const fail = useFailToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [links, setLinks] = useState<HiddenCaseContentLinks | null>(null);
  const [busy, setBusy] = useState(false);
  const caseId = testCase?.test_case_id;

  useEffect(() => {
    setReason("");
    setError(null);
    setLinks(null);
  }, [caseId]);

  if (!testCase) return null;

  const request = async () => {
    if (reason.trim().length < 10) {
      setError("Give a reason of at least 10 characters (it is recorded in the audit log).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.get<HiddenCaseContentLinks>(`studio/coding/test-cases/${seg(testCase.test_case_id)}/content`, { query: { reason: reason.trim() } });
      setLinks(res);
    } catch (err) {
      if (err instanceof ApiError && err.code === "rate_limited") setError("You've opened too many hidden cases this hour. Try again later.");
      else if (err instanceof ApiError && err.code === "permission_denied") setError("You don't have access to hidden test case content.");
      else if (err instanceof ApiError && err.code === "validation_failed") setError(err.detail);
      else fail(err, "Couldn't open the hidden case");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title={`Hidden case ${testCase.ordinal} content`}
      footer={
        links ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void request()} loading={busy}>
              Get download links
            </Button>
          </>
        )
      }
    >
      {links ? (
        <div className="space-y-3 text-sm">
          <p>
            Each link works once and expires at <strong>{new Date(links.expires_at).toLocaleTimeString()}</strong>. Don&apos;t share them.
          </p>
          <ul className="space-y-2">
            <li>
              <a className="text-fg-link underline" href={links.input_url} target="_blank" rel="noopener noreferrer">
                Download input
              </a>{" "}
              <span className="font-mono text-xs text-fg-muted">sha256 {shaShort(links.sha256.input)}</span>
            </li>
            <li>
              <a className="text-fg-link underline" href={links.expected_url} target="_blank" rel="noopener noreferrer">
                Download expected output
              </a>{" "}
              <span className="font-mono text-xs text-fg-muted">sha256 {shaShort(links.sha256.expected)}</span>
            </li>
          </ul>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-fg-muted">Viewing hidden content is audited. You may be asked to confirm it&apos;s you.</p>
          <FormField label="Reason" required error={error ?? undefined} hint="For example: fixing reported issue CMS-013-482">
            {(p) => <TextArea {...p} rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </FormField>
        </div>
      )}
    </Dialog>
  );
}

function shaShort(s: string | null): string {
  return s ? `${s.slice(0, 12)}…` : "—";
}

type HiddenCase = Extract<TestCase, { is_sample: false }>;

function TestCases({ problemId, state, editable }: { problemId: string; state: ApiState<{ problem_version: number; data: TestCase[] }>; editable: boolean }) {
  const toast = useToast();
  const fail = useFailToast();
  const [sample, setSample] = useState({ input: "", expected_output: "" });
  const [weight, setWeight] = useState("1");
  const inputRef = useRef<HTMLInputElement>(null);
  const expectedRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [hiddenError, setHiddenError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<HiddenCase | null>(null);

  const all = state.data?.data ?? [];
  const samples = all.filter((c) => c.is_sample);
  const hidden = all.filter((c): c is HiddenCase => !c.is_sample);

  const addSample = async () => {
    if (!sample.input.trim() || !sample.expected_output.trim()) return;
    setBusy("sample");
    try {
      await api.post(`studio/coding/problems/${seg(problemId)}/test-cases`, {
        kind: "sample",
        input: sample.input,
        expected_output: sample.expected_output,
      } satisfies SendBody<"studio/coding/problems/{problem_id}/test-cases", "post">);
      setSample({ input: "", expected_output: "" });
      toast.show({ tone: "success", title: "Sample case added" });
      await state.reload();
    } catch (err) {
      fail(err, "Couldn't add the sample");
    } finally {
      setBusy(null);
    }
  };

  const addHidden = async () => {
    const inFile = inputRef.current?.files?.[0];
    const outFile = expectedRef.current?.files?.[0];
    setHiddenError(null);
    if (!inFile || !outFile) {
      setHiddenError("Choose both the input file and the expected output file.");
      return;
    }
    setBusy("hidden");
    try {
      // COD-15 takes hidden case content inline (`TestCaseIn`); it is never kept in state.
      const [input, expected_output] = await Promise.all([readText(inFile), readText(outFile)]);
      await api.post(`studio/coding/problems/${seg(problemId)}/test-cases`, {
        kind: "hidden",
        input,
        expected_output,
        weight: Number(weight) || 1,
      } satisfies Body<"studio/coding/problems/{problem_id}/test-cases", "post">);
      toast.show({ tone: "success", title: "Hidden case uploaded", description: "Its content is stored encrypted and isn't shown here." });
      await state.reload();
    } catch (err) {
      if (err instanceof ApiError) fail(err, "Couldn't upload the hidden case");
      else setHiddenError("The upload didn't complete. Check your connection and try again.");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
      if (expectedRef.current) expectedRef.current.value = "";
      setBusy(null);
    }
  };

  return (
    <>
      <Card title="Sample cases (shown to students)">
        <Boundary state={state}>
          {() =>
            samples.length === 0 ? (
              <p className="text-sm text-fg-muted">No sample cases yet.</p>
            ) : (
              <ol className="space-y-3">
                {samples.map((c) =>
                  c.is_sample ? (
                    <li key={c.test_case_id} className="grid gap-2 md:grid-cols-2">
                      <div>
                        <p className="text-xs font-semibold uppercase text-fg-muted">Sample {c.ordinal} input</p>
                        <pre className="mt-1 overflow-x-auto rounded-md bg-surface-sunken p-2 text-xs">{c.input}</pre>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase text-fg-muted">Expected output</p>
                        <pre className="mt-1 overflow-x-auto rounded-md bg-surface-sunken p-2 text-xs">{c.expected_output}</pre>
                      </div>
                    </li>
                  ) : null,
                )}
              </ol>
            )
          }
        </Boundary>
        {editable ? (
          <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-2">
            <FormField label="Sample input">{(p) => <TextArea {...p} rows={3} className="font-mono" value={sample.input} onChange={(e) => setSample((s) => ({ ...s, input: e.target.value }))} />}</FormField>
            <FormField label="Expected output">
              {(p) => <TextArea {...p} rows={3} className="font-mono" value={sample.expected_output} onChange={(e) => setSample((s) => ({ ...s, expected_output: e.target.value }))} />}
            </FormField>
            <div className="md:col-span-2">
              <Button variant="secondary" onClick={() => void addSample()} loading={busy === "sample"} disabled={!sample.input.trim() || !sample.expected_output.trim()}>
                Add sample
              </Button>
            </div>
          </div>
        ) : null}
      </Card>
      <Card title="Hidden cases">
        <p className="mb-3 text-sm text-fg-muted">
          Hidden cases are encrypted at rest. Only their metadata is listed; students see verdicts only. Opening a case&apos;s content needs a reason and is audited.
        </p>
        <Table
          caption="Hidden test cases (metadata only)"
          columns={[
            { key: "o", header: "#", cell: (c: HiddenCase) => c.ordinal, align: "right" },
            { key: "w", header: "Weight", cell: (c) => c.weight, align: "right" },
            { key: "s", header: "Size", cell: (c) => (typeof c.size_bytes === "number" ? `${(c.size_bytes / 1024).toFixed(1)} KiB` : "—"), align: "right" },
            { key: "h", header: "SHA-256", cell: (c) => <span className="font-mono text-xs">{shaShort(c.input_sha256)}</span> },
            {
              key: "x",
              header: "Content",
              cell: (c) => (
                <Button size="sm" variant="ghost" aria-label={`View content of hidden case ${c.ordinal}`} onClick={() => setViewing(c)}>
                  View content
                </Button>
              ),
            },
          ]}
          rows={state.data ? hidden : undefined}
          rowKey={(c) => c.test_case_id}
          loading={state.loading}
          error={state.error}
          onRetry={() => void state.reload()}
          empty={{ title: "No hidden cases yet" }}
        />
        <HiddenContentDialog testCase={viewing} onClose={() => setViewing(null)} />
        {editable ? (
          <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
            <FormField label="Input file" required>
              {(p) => <input {...p} ref={inputRef} type="file" className="block text-sm text-fg" />}
            </FormField>
            <FormField label="Expected output file" required>
              {(p) => <input {...p} ref={expectedRef} type="file" className="block text-sm text-fg" />}
            </FormField>
            <FormField label="Weight">{(p) => <Input {...p} type="number" min={1} inputMode="numeric" value={weight} onChange={(e) => setWeight(e.target.value)} />}</FormField>
            {hiddenError ? (
              <p role="alert" className="text-sm font-medium text-danger-fg md:col-span-3">
                {hiddenError}
              </p>
            ) : null}
            <div className="md:col-span-3">
              <Button variant="secondary" onClick={() => void addHidden()} loading={busy === "hidden"}>
                Upload hidden case
              </Button>
            </div>
          </div>
        ) : null}
      </Card>
    </>
  );
}
