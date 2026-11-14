"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, EmptyState, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, TextArea, fieldErrorsOf, formatDateTime, useFailToast } from "@/features/trainer/shared/ui";
import { isCode, send } from "../lib/api";
import type { Certification, PdfUpload, Resume, ResumeContent, ResumeList, ResumeReview, TemplateKey } from "../lib/types";

const MAX_PDF = 5 * 1024 * 1024;

export const EMPTY_CONTENT: ResumeContent = { headline: "", summary: "", education: [], skills: [], projects: [], internships: [], achievements: [], certifications: [] };

type Row = Record<string, string>;

/** Repeatable rows of text fields (education, projects, internships, certifications). */
function RowsEditor({ legend, fields, rows, onChange, errors, prefix }: { legend: string; fields: { key: string; label: string }[]; rows: Row[]; onChange: (rows: Row[]) => void; errors: Record<string, string>; prefix: string }) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-semibold text-fg">{legend}</legend>
      {rows.map((r, i) => (
        <div key={i} className="grid gap-2 rounded-md border border-line p-3 sm:grid-cols-3">
          {fields.map((f) => (
            <FormField key={f.key} label={f.label} error={errors[`content.${prefix}.${i}.${f.key}`]}>
              {(c) => <Input {...c} value={r[f.key] ?? ""} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, [f.key]: e.target.value } : x)))} />}
            </FormField>
          ))}
          <div className="flex items-end">
            <Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={() => onChange([...rows, {}])}>
        Add {legend.toLowerCase()}
      </Button>
    </fieldset>
  );
}

const toRows = (items: object[] | undefined): Row[] =>
  (items ?? []).map((o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v)])));
const clean = (rows: Row[]) => rows.map((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, v.trim()]))).filter((r) => Object.keys(r).length);
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

/** Editor for one résumé (create when `resume` is null). */
export function ResumeEditor({ resume, suggested, onSaved }: { resume: Resume | null; suggested: Certification[]; onSaved: (r: Resume) => void }) {
  const c = resume?.content ?? EMPTY_CONTENT;
  const [template, setTemplate] = useState<TemplateKey>(resume?.template_key ?? "ats_classic");
  const [headline, setHeadline] = useState(c.headline ?? "");
  const [summary, setSummary] = useState(c.summary ?? "");
  const [skills, setSkills] = useState((c.skills ?? []).join(", "));
  const [achievements, setAchievements] = useState((c.achievements ?? []).join("\n"));
  const [education, setEducation] = useState<Row[]>(toRows(c.education));
  const [projects, setProjects] = useState<Row[]>(toRows(c.projects));
  const [internships, setInternships] = useState<Row[]>(toRows(c.internships));
  const [certs, setCerts] = useState<Row[]>(toRows(c.certifications));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();

  function addSuggested() {
    const have = new Set(certs.map((r) => r.title));
    setCerts([...certs, ...toRows(suggested.filter((s) => !have.has(s.title)))]);
  }

  async function save() {
    const errs: Record<string, string> = {};
    education.forEach((r, i) => {
      if (Object.values(r).some((v) => v.trim()) && (!r.institution?.trim() || !r.degree?.trim())) errs[`content.education.${i}.institution`] = "Institution and degree are required";
    });
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const content = {
      headline: headline.trim(),
      summary: summary.trim(),
      skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
      achievements: lines(achievements),
      education: clean(education),
      projects: clean(projects).map((p) => (p.tech ? { ...p, tech: p.tech.split(",").map((t) => t.trim()).filter(Boolean) } : p)),
      internships: clean(internships),
      certifications: clean(certs),
    };
    setBusy(true);
    try {
      const body = { template_key: template, content };
      const r = resume ? await send<Resume>("put", `me/resumes/${seg(resume.id)}`, body) : await send<Resume>("post", "me/resumes", body);
      toast.show({ tone: "success", title: "Résumé saved", description: `Checklist score ${r.checklist_score}/100` });
      onSaved(r);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't save your résumé");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      noValidate
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Template" error={errors.template_key}>
          {(ctl) => (
            <Select
              {...ctl}
              value={template}
              onChange={(e) => setTemplate(e.target.value as TemplateKey)}
              options={[
                { value: "ats_classic", label: "ATS classic" },
                { value: "ats_modern", label: "ATS modern" },
              ]}
            />
          )}
        </FormField>
        <FormField label="Headline" error={errors["content.headline"]}>
          {(ctl) => <Input {...ctl} value={headline} maxLength={200} onChange={(e) => setHeadline(e.target.value)} />}
        </FormField>
      </div>
      <FormField label="Summary" error={errors["content.summary"]}>
        {(ctl) => <TextArea {...ctl} value={summary} maxLength={2000} onChange={(e) => setSummary(e.target.value)} />}
      </FormField>
      <FormField label="Skills" hint="Separate with commas." error={errors["content.skills"]}>
        {(ctl) => <Input {...ctl} value={skills} onChange={(e) => setSkills(e.target.value)} />}
      </FormField>
      <RowsEditor
        legend="Education"
        prefix="education"
        errors={errors}
        rows={education}
        onChange={setEducation}
        fields={[
          { key: "institution", label: "Institution" },
          { key: "degree", label: "Degree" },
          { key: "field", label: "Field" },
          { key: "start_year", label: "From" },
          { key: "end_year", label: "To" },
          { key: "score", label: "Score / CGPA" },
        ]}
      />
      <RowsEditor
        legend="Projects"
        prefix="projects"
        errors={errors}
        rows={projects}
        onChange={setProjects}
        fields={[
          { key: "title", label: "Title" },
          { key: "description", label: "Description" },
          { key: "tech", label: "Tech (comma separated)" },
          { key: "link", label: "Link" },
        ]}
      />
      <RowsEditor
        legend="Internships"
        prefix="internships"
        errors={errors}
        rows={internships}
        onChange={setInternships}
        fields={[
          { key: "company", label: "Company" },
          { key: "role", label: "Role" },
          { key: "start", label: "Start" },
          { key: "end", label: "End" },
          { key: "description", label: "What you did" },
        ]}
      />
      <FormField label="Achievements" hint="One per line." error={errors["content.achievements"]}>
        {(ctl) => <TextArea {...ctl} value={achievements} onChange={(e) => setAchievements(e.target.value)} />}
      </FormField>
      <RowsEditor
        legend="Certifications"
        prefix="certifications"
        errors={errors}
        rows={certs}
        onChange={setCerts}
        fields={[
          { key: "title", label: "Title" },
          { key: "issuer", label: "Issuer" },
          { key: "issued_on", label: "Issued on" },
          { key: "credential_id", label: "Credential ID" },
        ]}
      />
      {suggested.length ? (
        <Button size="sm" variant="secondary" onClick={addSuggested}>
          Add my Tech Drona certificates ({suggested.length})
        </Button>
      ) : null}
      <div>
        <Button type="submit" loading={busy}>
          Save résumé
        </Button>
      </div>
    </form>
  );
}

function PdfPanel({ resume, onUploaded }: { resume: Resume; onUploaded: (r: Resume) => void }) {
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();

  async function upload(file: File | undefined) {
    if (!file) return;
    if (file.type !== "application/pdf") return setError("Choose a PDF file");
    if (file.size > MAX_PDF) return setError("PDF must be 5 MB or smaller");
    setError(undefined);
    setBusy(true);
    try {
      const up = await send<PdfUpload>("post", `me/resumes/${seg(resume.id)}/pdf-upload`, { filename: file.name, size_bytes: file.size });
      const form = new FormData();
      for (const [k, v] of Object.entries(up.fields)) form.append(k, v);
      form.append("file", file);
      const res = await fetch(up.url, { method: "POST", body: form });
      if (!res.ok) throw new Error("upload failed");
      onUploaded(await send<Resume>("post", `me/resumes/${seg(resume.id)}/pdf-upload/complete`, { key: up.key }));
    } catch (err) {
      fail(err, "Couldn't upload the PDF");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    try {
      const r = await api.get<{ url: string }>(`me/resumes/${seg(resume.id)}/pdf`);
      window.open(r.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      fail(err, "Couldn't open the PDF");
    }
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-fg-muted">Automatic PDF export is coming soon. For now, upload a PDF of your résumé (max 5 MB) to keep with this version.</p>
      <FormField label="Upload PDF" error={error}>
        {(c) => <input {...c} type="file" accept="application/pdf" disabled={busy} onChange={(e) => void upload(e.target.files?.[0])} className="text-sm" />}
      </FormField>
      {resume.has_pdf ? (
        <p>
          Uploaded {formatDateTime(resume.pdf_uploaded_at)} ·{" "}
          <Button size="sm" variant="ghost" onClick={() => void download()}>
            Download PDF
          </Button>
        </p>
      ) : null}
    </div>
  );
}

const REVIEW_LABEL: Record<ResumeReview["status"], string> = { requested: "Pending", in_review: "In review", completed: "Returned", cancelled: "Cancelled" };

export function ReviewPanel({ resume, remaining, onRequested }: { resume: Resume; remaining: number; onRequested: (r: ResumeReview) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();
  const toast = useToast();
  const open = resume.reviews.some((r) => r.status === "requested" || r.status === "in_review");

  async function request() {
    setBusy(true);
    try {
      const r = await send<ResumeReview>("post", `me/resumes/${seg(resume.id)}/review-requests`, note.trim() ? { note: note.trim() } : {}, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Review requested", description: "A mentor will comment on your résumé." });
      setNote("");
      onRequested(r);
    } catch (err) {
      if (isCode(err, "entitlement_required")) toast.show({ tone: "warning", title: "Mentor reviews need a placement package", description: "Or your review credits are used up." });
      else fail(err, "Couldn't request a review");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 text-sm">
      <p className="text-fg-muted">Reviews left: {remaining}</p>
      {open ? (
        <p>A review is pending — you&apos;ll see the mentor&apos;s comments here.</p>
      ) : (
        <div className="space-y-2">
          <FormField label="Note for the mentor (optional)">
            {(c) => <Input {...c} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}
          </FormField>
          <Button loading={busy} disabled={remaining <= 0} onClick={() => void request()}>
            Request mentor review
          </Button>
        </div>
      )}
      {resume.reviews.length ? (
        <ul className="space-y-3">
          {resume.reviews.map((r) => (
            <li key={r.id} className="rounded-md border border-line p-3">
              <p className="flex items-center gap-2">
                <Badge tone={r.status === "completed" ? "success" : "info"}>{REVIEW_LABEL[r.status]}</Badge>
                <span className="text-fg-muted">Requested {formatDateTime(r.requested_at)}</span>
              </p>
              {r.summary ? <p className="mt-2 text-fg">{r.summary}</p> : null}
              {r.comments.length ? (
                <ul className="mt-2 list-inside list-disc">
                  {r.comments.map((c, i) => (
                    <li key={i}>
                      <span className="font-medium">{c.section}:</span> {c.comment}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** STU-014 résumé builder: sections, checklist score, PDF, mentor review. */
export function StudentResume() {
  const state = useApi<ResumeList>("me/resumes");
  const [current, setCurrent] = useState<Resume | null | undefined>(undefined);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (state.data) setCurrent(state.data.data.find((r) => r.is_current) ?? state.data.data[0] ?? null);
  }, [state.data]);

  return (
    <Boundary state={state}>
      {(d) => {
        const r = current === undefined ? (d.data.find((x) => x.is_current) ?? null) : current;
        if (!r && !creating)
          return (
            <EmptyState icon="document"
              title="Build your résumé"
              description="Two ATS-friendly templates. Your Tech Drona certificates can be added in one click."
              action={<Button onClick={() => setCreating(true)}>Start my résumé</Button>}
            />
          );
        return (
          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <Card title={r ? `Résumé · version ${r.version_no}` : "New résumé"}>
              <ResumeEditor key={r?.id ?? "new"} resume={r} suggested={d.suggested_certifications} onSaved={(x) => setCurrent(x)} />
            </Card>
            <div className="space-y-6">
              {r ? (
                <>
                  <Card title={`Checklist score ${r.checklist_score}/100`}>
                    <ul className="space-y-1 text-sm">
                      {r.checklist.map((i) => (
                        <li key={i.key} className={i.done ? "text-fg" : "text-fg-muted"}>
                          {i.done ? "✓" : "○"} {i.label}
                        </li>
                      ))}
                    </ul>
                  </Card>
                  <Card title="PDF">
                    <PdfPanel resume={r} onUploaded={(x) => setCurrent(x)} />
                  </Card>
                  <Card title="Mentor review">
                    <ReviewPanel
                      resume={r}
                      remaining={d.quota.has_package ? d.quota.resume_reviews_remaining : 0}
                      onRequested={(rev) => setCurrent({ ...r, reviews: [rev, ...r.reviews] })}
                    />
                  </Card>
                </>
              ) : null}
            </div>
          </div>
        );
      }}
    </Boundary>
  );
}
