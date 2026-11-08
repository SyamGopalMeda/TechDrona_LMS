"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Badge, Button, Card, Checkbox, Dialog, EmptyState, FormField, Input, Select, useToast } from "@/components/ui";
import { Boundary, TextArea, fieldErrorsOf, formatDateTime, useFailToast } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { pathsApi, seg } from "../lib/api";
import type { ArticleDetail, ArticleSummary, Audience, Level, PathsContext } from "../lib/types";
import { ArticleRenderer, OnThisPage, useArticleToc } from "./ArticleRenderer";
import { usePathsContext } from "./PathList";
import { BatchMemberSearch } from "./BatchMemberSearch";
import { usePathsBase } from "../lib/base";

export const AUDIENCE_LABEL: Record<Audience, string> = {
  batches: "Chosen batches",
  people: "Chosen people",
};

const STARTER = `## Introduction

Write the lesson here.

:::key-idea
The one thing to remember.
:::
`;

/* ------------------------------------------------------------------ list */

export function ArticleList() {
  const base = usePathsBase();
  const ctx = usePathsContext();
  const router = useRouter();
  const fail = useFailToast();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const list = useApi<{ data: ArticleSummary[] }>(ctx.data?.can_author ? "path-articles" : null, { q: q.trim() || undefined });

  const create = async () => {
    setBusy(true);
    try {
      const a = await pathsApi.createArticle({ title: "Untitled article", body_md: STARTER });
      router.push(`${base}/articles/${encodeURIComponent(a.id)}`);
    } catch (e) {
      fail(e);
      setBusy(false);
    }
  };

  return (
    <Boundary state={ctx}>
      {(c) => (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-col gap-3 sm:flex-row">
              <FormField label="Search articles">{(p) => <Input {...p} type="search" value={q} onChange={(e) => setQ(e.target.value)} />}</FormField>
            </div>
            <Button onClick={() => void create()} loading={busy} disabled={!c.can_author}>
              + New article
            </Button>
          </div>
          <Boundary state={list}>
            {(l) =>
              l.data.length === 0 ? (
                <EmptyState title="No articles yet" description="Articles are lessons you write once and use as path steps or share with a link." />
              ) : (
                <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
                  {l.data.map((a) => (
                    <li key={a.id} className="flex flex-col gap-1 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <Link href={`${base}/articles/${encodeURIComponent(a.id)}`} className="font-medium text-fg hover:underline">
                          {a.title}
                        </Link>
                        {a.subtitle ? <p className="text-sm text-fg-muted">{a.subtitle}</p> : null}
                        <p className="text-xs text-fg-muted">Updated {formatDateTime(a.updated_at)}</p>
                      </div>
                      <Badge tone={a.status === "published" ? "success" : "neutral"}>{a.status === "published" ? (a.audience ? AUDIENCE_LABEL[a.audience] : "Published") : "Not published"}</Badge>
                    </li>
                  ))}
                </ul>
              )
            }
          </Boundary>
        </div>
      )}
    </Boundary>
  );
}

/* ------------------------------------------------------------------ editor */

const SNIPPETS: { label: string; text: string }[] = [
  { label: "Key idea", text: "\n:::key-idea\nThe main point.\n:::\n" },
  { label: "Watch out", text: "\n:::watch-out\nA common mistake.\n:::\n" },
  { label: "Note", text: "\n:::note\nExtra context.\n:::\n" },
  { label: "Tip", text: "\n:::tip\nA helpful hint.\n:::\n" },
  { label: "Code", text: "\n```python\nprint(\"hello\")\n```\n```output\nhello\n```\n" },
  { label: "Table", text: "\n| Column A | Column B |\n| --- | --- |\n| 1 | 2 |\n" },
  { label: "Exercise", text: "\n:::exercise Try it yourself\nWhat does this print?\n:::answer\nThe answer.\n:::\n" },
];

export function ArticleEditor({ articleId }: { articleId: string }) {
  const state = useApi<ArticleDetail>(`path-articles/${seg(articleId)}`);
  return <Boundary state={state}>{(a) => <ArticleEditorBody key={`${a.id}:${a.updated_at}`} article={a} reload={state.reload} />}</Boundary>;
}

function ArticleEditorBody({ article, reload }: { article: ArticleDetail; reload: () => Promise<void> }) {
  const base = usePathsBase();
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const [title, setTitle] = useState(article.title);
  const [subtitle, setSubtitle] = useState(article.subtitle ?? "");
  const [level, setLevel] = useState<Level | "">(article.level ?? "");
  const [minutes, setMinutes] = useState(article.est_minutes ? String(article.est_minutes) : "");
  const [body, setBody] = useState(article.body_md);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [shareOpen, setShareOpen] = useState(false);
  const [view, setView] = useState<"write" | "preview">("write");
  const area = useRef<HTMLTextAreaElement>(null);
  const toc = useArticleToc(body);
  const dirty =
    title !== article.title || subtitle !== (article.subtitle ?? "") || level !== (article.level ?? "") || minutes !== (article.est_minutes ? String(article.est_minutes) : "") || body !== article.body_md;

  const insert = (text: string) => {
    const el = area.current;
    const at = el ? el.selectionStart : body.length;
    const next = body.slice(0, at) + text + body.slice(at);
    setBody(next);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(at + text.length, at + text.length);
    });
  };

  const save = async () => {
    setBusy(true);
    setErrs({});
    try {
      await pathsApi.updateArticle(article.id, {
        title: title.trim(),
        subtitle: subtitle.trim() || null,
        level: level || null,
        est_minutes: minutes ? Number(minutes) : null,
        body_md: body,
      });
      toast.show({ tone: "success", title: "Article saved" });
      await reload();
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) setErrs(fe);
      else fail(e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete "${article.title}"? This cannot be undone.`)) return;
    try {
      await pathsApi.deleteArticle(article.id);
      router.push(`${base}/articles`);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`${base}/articles`} className="text-sm text-fg-link underline">
            ← Articles
          </Link>
          <Badge tone={article.status === "published" ? "success" : "neutral"}>{article.status === "published" ? (article.audience ? AUDIENCE_LABEL[article.audience] : "Published") : "Not published"}</Badge>
          {dirty ? <Badge tone="warning">Unsaved changes</Badge> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => void remove()}>
            Delete
          </Button>
          <Button variant="secondary" onClick={() => void save()} loading={busy} disabled={!dirty}>
            Save
          </Button>
          <Button onClick={() => setShareOpen(true)} disabled={dirty}>
            Publish &amp; share
          </Button>
        </div>
      </div>
      <Card>
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label="Title" required error={errs.title}>{(p) => <Input {...p} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />}</FormField>
          <FormField label="Subtitle" error={errs.subtitle}>{(p) => <Input {...p} value={subtitle} maxLength={300} onChange={(e) => setSubtitle(e.target.value)} />}</FormField>
          <FormField label="Level">
            {(p) => (
              <Select
                {...p}
                value={level}
                onChange={(e) => setLevel(e.target.value as Level | "")}
                options={[
                  { value: "", label: "Not set" },
                  { value: "beginner", label: "Beginner" },
                  { value: "intermediate", label: "Intermediate" },
                  { value: "advanced", label: "Advanced" },
                ]}
              />
            )}
          </FormField>
          <FormField label="Study time (minutes)" error={errs.est_minutes}>{(p) => <Input {...p} type="number" min={1} max={1440} value={minutes} onChange={(e) => setMinutes(e.target.value)} />}</FormField>
        </div>
      </Card>
      <div className="flex gap-2 lg:hidden" role="group" aria-label="Editor view">
        <Button size="sm" variant={view === "write" ? "primary" : "secondary"} onClick={() => setView("write")}>
          Write
        </Button>
        <Button size="sm" variant={view === "preview" ? "primary" : "secondary"} onClick={() => setView("preview")}>
          Preview
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className={view === "preview" ? "hidden lg:block" : undefined}>
          <div className="mb-2 flex flex-wrap gap-1" role="toolbar" aria-label="Insert block">
            {SNIPPETS.map((s) => (
              <Button key={s.label} size="sm" variant="secondary" onClick={() => insert(s.text)}>
                + {s.label}
              </Button>
            ))}
          </div>
          <FormField label="Content (Markdown)" error={errs.body_md} hint="Headings (##), code fences, :::key-idea / :::watch-out / :::note / :::tip callouts, tables and :::exercise blocks.">
            {(p) => <TextArea {...p} ref={area} rows={28} value={body} onChange={(e) => setBody(e.target.value)} className="font-mono" />}
          </FormField>
        </div>
        <div className={view === "write" ? "hidden lg:block" : undefined}>
          <p className="mb-2 text-sm font-medium">Preview</p>
          <div className="rounded-xl border border-line bg-surface p-4">
            <OnThisPage toc={toc} />
            <ArticleRenderer source={body} />
          </div>
        </div>
      </div>
      <PublishDialog open={shareOpen} onClose={() => setShareOpen(false)} article={article} onDone={() => void reload()} />
    </div>
  );
}

function PublishDialog({ open, onClose, article, onDone }: { open: boolean; onClose: () => void; article: ArticleDetail; onDone: () => void }) {
  const toast = useToast();
  const fail = useFailToast();
  const ctx = useApi<PathsContext>(open ? "paths/context" : null);
  const batches = ctx.data?.batches ?? [];
  const [audience, setAudience] = useState<Audience>(article.audience ?? "batches");
  const [batchIds, setBatchIds] = useState<string[]>(article.batch_ids ?? []);
  const [people, setPeople] = useState<string[]>(article.user_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const link = typeof window === "undefined" ? `/read/${article.id}` : `${window.location.origin}/read/${encodeURIComponent(article.id)}`;
  const published = article.status === "published";

  const publish = async () => {
    setBusy(true);
    setErrs({});
    try {
      await pathsApi.publishArticle(article.id, {
        audience,
        ...(audience === "batches" ? { batch_ids: batchIds } : {}),
        ...(audience === "people" ? { user_ids: people } : {}),
      });
      toast.show({ tone: "success", title: published ? "Sharing updated" : "Article published" });
      onDone();
      onClose();
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) setErrs(fe);
      else fail(e);
    } finally {
      setBusy(false);
    }
  };
  const unpublish = async () => {
    setBusy(true);
    try {
      await pathsApi.unpublishArticle(article.id);
      toast.show({ tone: "success", title: "Article unpublished" });
      onDone();
      onClose();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      toast.show({ tone: "success", title: "Link copied" });
    } catch {
      toast.show({ tone: "warning", title: "Copy the link manually" });
    }
  };

  const radio = (value: Audience, hint: string) => (
    <label className={`flex cursor-pointer flex-col rounded-lg border p-3 ${audience === value ? "border-brand bg-brand-subtle" : "border-line"}`}>
      <span className="flex items-center gap-2 text-sm font-semibold">
        <input type="radio" name="audience" value={value} checked={audience === value} onChange={() => setAudience(value)} />
        {AUDIENCE_LABEL[value]}
      </span>
      <span className="mt-1 text-xs text-fg-muted">{hint}</span>
    </label>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="Publish & share"
      footer={
        <>
          {published ? (
            <Button variant="danger" onClick={() => void unpublish()} disabled={busy} className="mr-auto">
              Unpublish
            </Button>
          ) : null}
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void publish()} loading={busy}>
            {published ? "Save" : "Publish"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">Who can read it</legend>
          {radio("batches", "Signed-in members of the batches you pick")}
          {radio("people", "Only the people you pick")}
        </fieldset>
        {audience === "batches" ? (
          <fieldset className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-line p-2">
            <legend className="sr-only">Batches</legend>
            {batches.length === 0 ? <p className="text-sm text-fg-muted">No batches available.</p> : null}
            {batches.map((b) => (
              <Checkbox
                key={b.id}
                label={`${b.name} (${b.code})`}
                checked={batchIds.includes(b.id)}
                onChange={(e) => setBatchIds(e.currentTarget.checked ? [...batchIds, b.id] : batchIds.filter((x) => x !== b.id))}
              />
            ))}
            {errs.batch_ids ? <p role="alert" className="text-xs text-danger-fg">{errs.batch_ids}</p> : null}
          </fieldset>
        ) : null}
        {audience === "people" ? (
          <div className="space-y-2">
            <BatchMemberSearch batches={batches} chosen={new Set(people)} onPick={(m) => setPeople([...people, m.user_id])} error={errs.user_ids} hint="Choose a batch, then type at least 2 letters." />
            <p className="text-sm text-fg-muted">
              {people.length} {people.length === 1 ? "person" : "people"} chosen
              {people.length ? (
                <Button variant="ghost" size="sm" onClick={() => setPeople([])} className="ml-2">
                  Clear
                </Button>
              ) : null}
            </p>
          </div>
        ) : null}
        <FormField label="Link" hint="Learners on a path that includes this article can always read it, published or not.">
          {(p) => (
            <div className="flex gap-2">
              <Input {...p} readOnly value={link} />
              <Button variant="secondary" size="md" onClick={() => void copy()} aria-label="Copy link">
                Copy
              </Button>
              <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex h-10 items-center rounded-md border border-line-control px-3 text-sm" aria-label="Open in a new tab">
                ↗
              </a>
            </div>
          )}
        </FormField>
      </div>
    </Dialog>
  );
}
