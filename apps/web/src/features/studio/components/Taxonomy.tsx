"use client";

import { useState } from "react";
import { Badge, Button, Checkbox, Dialog, FormField, Input, PageHeader, Select, StatusBadge, Table, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { seg, type SendBody } from "@/features/trainer/shared/use-api";
import { Boundary, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { slugify } from "./Courses";
import { useTopics, type TopicOption } from "./Pickers";

const TOPIC_SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;

interface TopicForm {
  name: string;
  slug: string;
  parent_id: string;
  position: string;
  is_active: boolean;
}

export function validateTopic(f: TopicForm): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.name.trim()) e.name = "Enter a name.";
  if (!TOPIC_SLUG.test(f.slug)) e.slug = "Lowercase letters, numbers and dashes (up to 63).";
  if (f.position && !Number.isInteger(Number(f.position))) e.position = "Enter a whole number.";
  return e;
}

/**
 * CMS-008 taxonomy (audit ADM-50 / INV-13): the full subject → topic tree from PLC-02b
 * `studio/topics` (deactivated nodes included, so they can be reactivated), create
 * (PLC-02) and edit / deactivate (PLC-03). Moving a topic to a new parent isn't offered here.
 */
const TAXONOMY_PURPOSE =
  "Subjects are top-level; topics sit under them. Deactivated topics stay listed here (marked Inactive) but are hidden from students and authors.";

/** CMS-008. With `header`, renders the page header so its description and primary action sit in the header. */
export function TaxonomyManager({ header }: { header?: { title: string } } = {}) {
  const toast = useToast();
  const fail = useFailToast();
  const topics = useTopics("studio");
  const [editing, setEditing] = useState<TopicOption | "new" | null>(null);
  const [f, setF] = useState<TopicForm>({ name: "", slug: "", parent_id: "", position: "0", is_active: true });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const openNew = (parentId = "") => {
    setF({ name: "", slug: "", parent_id: parentId, position: "0", is_active: true });
    setErrors({});
    setEditing("new");
  };
  const openEdit = (t: TopicOption) => {
    setF({ name: t.node.name, slug: t.node.slug, parent_id: t.node.parent_id ?? "", position: String(t.node.position), is_active: t.node.is_active });
    setErrors({});
    setEditing(t);
  };

  const save = async () => {
    const e = validateTopic(f);
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      if (editing === "new") {
        await api.post(
          "studio/topics",
          { name: f.name.trim(), slug: f.slug, parent_id: f.parent_id || null, position: Number(f.position || 0) } satisfies SendBody<"studio/topics", "post">,
          { idempotencyKey: true },
        );
        toast.show({ tone: "success", title: "Topic added" });
      } else if (editing) {
        const res = await api.patch<{ dependent_question_count?: number }>(`studio/topics/${seg(editing.id)}`, {
          name: f.name.trim(),
          slug: f.slug,
          position: Number(f.position || 0),
          is_active: f.is_active,
        } satisfies Body<"studio/topics/{topic_id}", "patch">);
        const n = res.kind === "ok" ? res.data.dependent_question_count : undefined;
        toast.show({ tone: "success", title: "Topic saved", description: n ? `${n} question${n === 1 ? "" : "s"} use this topic or its subtopics.` : undefined });
      }
      setEditing(null);
      await topics.reload();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't save the topic");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {header ? (
        <PageHeader title={header.title} description={TAXONOMY_PURPOSE} actions={<Button onClick={() => openNew()}>New subject or topic</Button>} />
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-fg-muted">{TAXONOMY_PURPOSE}</p>
          <Button onClick={() => openNew()}>New subject or topic</Button>
        </div>
      )}
      <Boundary state={topics}>
        {() => (
          <Table
            caption="Taxonomy"
            columns={[
              {
                key: "n",
                header: "Name",
                cell: (t: TopicOption) => (
                  <span style={{ paddingLeft: `${t.level * 1.25}rem` }} className={t.level === 0 ? "font-medium" : undefined}>
                    {t.name}
                    {t.node.is_active ? null : <StatusBadge className="ml-2" status="inactive" />}
                  </span>
                ),
              },
              { key: "k", header: "Kind", cell: (t) => <Badge tone={t.level === 0 ? "brand" : "neutral"}>{t.node.kind === "subject" ? "Subject" : t.node.kind === "topic" ? "Topic" : t.node.kind}</Badge> },
              { key: "s", header: "Slug", priority: "secondary", cell: (t) => <span className="font-mono text-xs">{t.node.slug}</span> },
              { key: "q", header: "Published questions", cell: (t) => t.node.question_count, align: "right" },
              {
                key: "x",
                header: <span className="sr-only">Actions</span>,
                align: "right",
                cell: (t) => (
                  <span className="inline-flex gap-1">
                    <Button size="sm" variant="secondary" onClick={() => openNew(t.id)} aria-label={`Add a topic under ${t.name}`}>
                      Add topic
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => openEdit(t)} aria-label={`Edit ${t.name}`}>
                      Edit
                    </Button>
                  </span>
                ),
              },
            ]}
            rows={topics.options}
            rowKey={(t) => t.id}
            empty={{ title: "No subjects yet", description: "Add a subject, then the topics under it. Questions and tests are tagged with these topics." }}
          />
        )}
      </Boundary>
      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        dismissible={!busy}
        title={editing === "new" ? "New subject or topic" : "Edit topic"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={busy}>
              Cancel
            </Button>
            <Button loading={busy} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {editing === "new" ? (
            <FormField label="Parent" hint="Leave empty to create a subject" error={errors.parent_id}>
              {(p) => (
                <Select
                  {...p}
                  value={f.parent_id}
                  onChange={(e) => setF((x) => ({ ...x, parent_id: e.target.value }))}
                  options={[{ value: "", label: "None — this is a subject" }, ...topics.options.filter((t) => t.node.is_active).map((t) => ({ value: t.id, label: t.label }))]}
                />
              )}
            </FormField>
          ) : null}
          <FormField label="Name" required error={errors.name}>
            {(p) => (
              <Input
                {...p}
                value={f.name}
                onChange={(e) => {
                  const name = e.target.value;
                  setF((x) => ({ ...x, name, slug: editing === "new" && (!x.slug || x.slug === slugify(x.name).slice(0, 63)) ? slugify(name).slice(0, 63) : x.slug }));
                }}
              />
            )}
          </FormField>
          <FormField label="Slug" required error={errors.slug}>
            {(p) => <Input {...p} className="font-mono" value={f.slug} onChange={(e) => setF((x) => ({ ...x, slug: e.target.value }))} />}
          </FormField>
          <FormField label="Position" hint="Lower numbers are listed first" error={errors.position}>
            {(p) => <Input {...p} inputMode="numeric" value={f.position} onChange={(e) => setF((x) => ({ ...x, position: e.target.value }))} />}
          </FormField>
          {editing !== "new" ? (
            <Checkbox label="Active (visible to students and authors)" checked={f.is_active} onChange={(e) => setF((x) => ({ ...x, is_active: e.target.checked }))} />
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
