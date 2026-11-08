import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { CompaniesManager, pathBody, validatePath } from "./Companies";
import { CourseEditor, CourseList, moveLesson, moveModule, outlineOf } from "./Courses";
import { docToText, textToDoc } from "./LessonEditor";
import { LessonMediaPanel, MediaLibrary } from "./Media";
import { flattenTopics, type TopicNode } from "./Pickers";
import { QuestionBank, QuestionEditor, ReviewQueue } from "./Questions";
import { TaxonomyManager } from "./Taxonomy";
import { postToProvider } from "../lib/media";
import type { CourseDetail, Lesson } from "../lib/types";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  vi.unstubAllGlobals();
  push.mockReset();
});

/** FE-24: paste long text in one event instead of typing key by key. */
async function fill(el: HTMLElement, text: string) {
  await userEvent.click(el);
  await userEvent.paste(text);
}

const topic = (id: string, name: string, children: TopicNode[] = [], parent_id: string | null = null): TopicNode => ({
  id,
  parent_id,
  kind: parent_id ? "topic" : "subject",
  slug: name.toLowerCase(),
  name,
  path: name.toLowerCase(),
  depth: parent_id ? 1 : 0,
  position: 0,
  is_active: true,
  question_count: 3,
  children,
});
const subjects = { items: [topic("s1", "Aptitude", [topic("t1", "Percentages", [], "s1"), topic("t2", "Ratios", [], "s1")])] };

const lesson = (over: Partial<Lesson> = {}): Lesson => ({
  id: "l1",
  lesson_key: "k1",
  title: "Intro video",
  lesson_type: "video",
  position: 0,
  is_required: true,
  is_free_preview: false,
  duration_seconds: null,
  est_reading_minutes: null,
  assets: [],
  ...over,
});

const course = (over: Partial<CourseDetail> = {}): CourseDetail => {
  const tree = {
    id: "cv1",
    version_no: 1,
    status: "draft",
    title: "DSA Basics",
    summary: null,
    description_md: null,
    outcomes: [],
    level: "beginner" as const,
    language: "en",
    category: null,
    tags: [],
    change_type: null,
    changelog: null,
    created_by: "u1",
    submitted_at: null,
    published_at: null,
    modules: [
      { id: "m1", module_key: "mk1", title: "Week 1", position: 0, lessons: [lesson(), lesson({ id: "l2", title: "Arrays article", lesson_type: "article" })] },
      { id: "m2", module_key: "mk2", title: "Week 2", position: 1, lessons: [lesson({ id: "l3", title: "Quiz 1", lesson_type: "quiz", test_id: "t9" })] },
    ],
  };
  return {
    id: "c1",
    organization_id: null,
    slug: "dsa",
    title: "DSA Basics",
    course_kind: "self_paced",
    visibility: "private",
    status: "draft",
    is_free: false,
    current_version_id: null,
    completeness_pct: 0,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    draft: tree,
    published: null,
    ...over,
  } as CourseDetail;
};

describe("outline ordering (ADM-45, CAT-12)", () => {
  const outline = outlineOf(course().draft!.modules);
  it("builds the CAT-12 body from the draft tree", () => {
    expect(outline).toEqual([
      { module_key: "mk1", title: "Week 1", lesson_ids: ["l1", "l2"] },
      { module_key: "mk2", title: "Week 2", lesson_ids: ["l3"] },
    ]);
  });
  it("moves lessons within and across modules, and modules", () => {
    expect(moveLesson(outline, "l2", -1)?.[0]!.lesson_ids).toEqual(["l2", "l1"]);
    const across = moveLesson(outline, "l2", 1)!;
    expect(across.map((m) => m.lesson_ids)).toEqual([["l1"], ["l2", "l3"]]);
    expect(moveLesson(outline, "l1", -1)).toBeNull();
    expect(moveLesson(outline, "l3", 1)).toBeNull();
    expect(moveModule(outline, "mk2", -1)?.map((m) => m.module_key)).toEqual(["mk2", "mk1"]);
    expect(moveModule(outline, "mk1", -1)).toBeNull();
    expect(outline[0]!.lesson_ids).toEqual(["l1", "l2"]); // input untouched
  });
});

describe("article body (ADM-45)", () => {
  it("round-trips headings, lists and paragraphs", () => {
    const text = "## Arrays\n\nAn array stores items.\n\n- fast reads\n- fixed size\n\n1. declare\n2. fill";
    const doc = textToDoc(text);
    expect(doc.content.map((n) => n.type)).toEqual(["heading", "paragraph", "bulletList", "orderedList"]);
    expect(docToText(doc)).toBe(text);
    expect(docToText(null)).toBe("");
  });
});

describe("topic picker data (ADM-51)", () => {
  it("flattens the PLC-01 tree with breadcrumb labels", () => {
    expect(flattenTopics(subjects.items).map((t) => [t.id, t.label, t.level])).toEqual([
      ["s1", "Aptitude", 0],
      ["t1", "Aptitude › Percentages", 1],
      ["t2", "Aptitude › Ratios", 1],
    ]);
  });
});

describe("CourseList create (ADM-41, single company)", () => {
  it("sends no organization or org_only visibility; the api picks the owner", async () => {
    const api = mockApi({
      "GET studio/courses": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "POST studio/courses": { status: 201, body: { id: "c9" } },
    });
    restore = api.restore;
    renderWithProviders(<CourseList hrefPattern="/trainer/courses/:id/edit" />);
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    await fill(screen.getByLabelText(/^Title/), "Batch DSA");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trainer/courses/c9/edit"));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ title: "Batch DSA", slug: "batch-dsa" });
  });
});

const courseRoutes = (c: CourseDetail, extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  "GET studio/courses/c1": { body: c },
  "GET studio/courses/c1/versions": { body: { data: [] } },
  "GET placement/subjects": { body: subjects },
  "GET studio/tests": { body: { items: [{ id: "t9", title: "Arrays quiz", status: "published" }] } },
  ...extra,
});

describe("CourseEditor (ADM-45 / ADM-56)", () => {
  it("hides Publish and Archive when canPublish is false", async () => {
    const published = course({ status: "published", draft: null, published: { ...course().draft!, status: "published" } });
    const api = mockApi(courseRoutes(published));
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" canPublish={false} />);
    expect(await screen.findByText("1. Week 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    // Published lessons are read-only: no reorder controls.
    expect(screen.queryByRole("button", { name: "Move Intro video down" })).not.toBeInTheDocument();
  });

  it("reorders lessons with CAT-12 and saves lesson fields with CAT-14", async () => {
    const api = mockApi(
      courseRoutes(course(), {
        "PUT studio/courses/c1/draft/outline": { body: {} },
        "PATCH studio/lessons/l2": { body: {} },
      }),
    );
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Move Arrays article down" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({
      modules: [
        { module_key: "mk1", title: "Week 1", lesson_ids: ["l1"] },
        { module_key: "mk2", title: "Week 2", lesson_ids: ["l2", "l3"] },
      ],
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit Arrays article" }));
    const editor = await screen.findByRole("region", { name: "Lesson Arrays article" });
    await fill(within(editor).getByLabelText(/^Article/), "## Arrays\n\nContiguous memory.");
    await fill(within(editor).getByLabelText(/^Reading time/), "7");
    await userEvent.click(within(editor).getByRole("checkbox", { name: /Free preview/ }));
    await userEvent.click(within(editor).getByRole("button", { name: "Save lesson" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      title: "Arrays article",
      is_required: true,
      is_free_preview: true,
      est_reading_minutes: 7,
      article_body: {
        type: "doc",
        content: [
          { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Arrays" }] },
          { type: "paragraph", content: [{ type: "text", text: "Contiguous memory." }] },
        ],
      },
    });
  });

  it("adds a quiz lesson with a test picker instead of a raw id (ADM-51)", async () => {
    const api = mockApi(courseRoutes(course(), { "POST studio/courses/c1/draft/lessons": { status: 201, body: {} } }));
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" />);
    await fill(await screen.findByLabelText(/^Module/), "Week 2");
    await fill(screen.getByLabelText(/^Lesson title/), "Quiz 2");
    await userEvent.selectOptions(screen.getByLabelText(/^Type/), "quiz");
    const picker = await screen.findByRole("combobox", { name: /^Test/ });
    await waitFor(() => expect(within(picker).getByRole("option", { name: "Arrays quiz (published)" })).toBeInTheDocument());
    await userEvent.selectOptions(picker, "t9");
    await userEvent.click(screen.getByRole("button", { name: "Add lesson" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ title: "Quiz 2", lesson_type: "quiz", module_key: "mk2", test_id: "t9" });
  });

  it("saves lesson topics with exactly one primary (CAT-15)", async () => {
    const api = mockApi(courseRoutes(course(), { "PUT studio/lessons/l1/topics": { body: {} } }));
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Intro video" }));
    const editor = await screen.findByRole("region", { name: "Lesson Intro video" });
    const pick = within(editor).getByRole("combobox", { name: /^Topic/ });
    await waitFor(() => expect(pick).toBeEnabled());
    await userEvent.selectOptions(pick, "t1");
    await userEvent.click(within(editor).getByRole("button", { name: "Add topic" }));
    await userEvent.selectOptions(pick, "t2");
    await userEvent.click(within(editor).getByRole("button", { name: "Add topic" }));
    await userEvent.click(within(editor).getByRole("button", { name: "Save topics" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "studio/lessons/l1/topics")).toBe(true));
    expect(api.calls.find((c) => c.path === "studio/lessons/l1/topics")?.body).toEqual({
      topics: [
        { topic_id: "t1", is_primary: true },
        { topic_id: "t2", is_primary: false },
      ],
    });
  });
});

describe("Lesson types, topics and resources (w2b R4)", () => {
  it("offers pdf and practice_set; a practice set picks only practice-set tests (following next_cursor)", async () => {
    const api = mockApi(
      courseRoutes(course(), {
        "GET studio/tests": (call) =>
          call.url.includes("cursor=p2")
            ? { body: { items: [{ id: "t2", title: "Ratios practice", status: "published", test_kind: "practice_set" }], page: { next_cursor: null, has_more: false } } }
            : { body: { items: [{ id: "t9", title: "Arrays quiz", status: "published", test_kind: "course_quiz" }], page: { next_cursor: "p2", has_more: true } } },
        "POST studio/courses/c1/draft/lessons": { status: 201, body: {} },
      }),
    );
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" />);
    const type = await screen.findByLabelText(/^Type/);
    expect(within(type).getByRole("option", { name: "PDF document" })).toBeInTheDocument();
    await fill(screen.getByLabelText(/^Module/), "Week 2");
    await fill(screen.getByLabelText(/^Lesson title/), "Ratios drill");
    await userEvent.selectOptions(type, "practice_set");
    const picker = await screen.findByRole("combobox", { name: /^Practice set test/ });
    await waitFor(() => expect(within(picker).getByRole("option", { name: "Ratios practice (published)" })).toBeInTheDocument());
    expect(within(picker).queryByRole("option", { name: "Arrays quiz (published)" })).not.toBeInTheDocument();
    await userEvent.selectOptions(picker, "t2");
    await userEvent.click(screen.getByRole("button", { name: "Add lesson" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ title: "Ratios drill", lesson_type: "practice_set", module_key: "mk2", test_id: "t2" });
  });

  it("shows the lesson's saved topics and loads its resources from GET studio/resources", async () => {
    const withTopics = course();
    withTopics.draft!.modules[0]!.lessons[0] = lesson({ topics: [{ topic_id: "t1", is_primary: true }] });
    const api = mockApi(
      courseRoutes(withTopics, {
        "GET studio/resources": { body: { data: [{ id: "r1", title: "Cheat sheet", resource_type: "link", access_level: "entitled", url: "https://x.example/c", has_file: false }], page: { next_cursor: null, has_more: false } } },
      }),
    );
    restore = api.restore;
    renderWithProviders(<CourseEditor courseId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Intro video" }));
    const editor = await screen.findByRole("region", { name: "Lesson Intro video" });
    const chosen = await within(editor).findByRole("list", { name: "Chosen topics" });
    await waitFor(() => expect(chosen).toHaveTextContent("Aptitude › Percentages"));
    expect(await within(editor).findByText("Cheat sheet")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "studio/resources")?.url).toContain("lesson_id=l1");
  });
});

describe("LessonMediaPanel (INV-03, MED-01..03)", () => {
  it("gets a ticket, uploads straight to the provider, then polls until ready", async () => {
    const provider = vi.fn(async () => new Response(null, { status: 201 }));
    vi.stubGlobal("fetch", provider);
    const api = mockApi({
      "POST media/uploads/video": { status: 201, body: { lesson_asset_id: "a1", provider: "vdocipher", status: "uploading", upload: { url: "https://upload.example.com/vdo", fields: { policy: "P", key: "orig/v1" } } } },
      "GET media/assets/a1/status": { body: { id: "a1", asset_type: "video", provider: "vdocipher", status: "ready", scan_status: "not_required", mime_type: null, size_bytes: null, duration_seconds: 600 } },
    });
    restore = api.restore;
    const onChanged = vi.fn();
    renderWithProviders(<LessonMediaPanel lesson={lesson()} editable onChanged={onChanged} />);
    const file = new File(["video-bytes"], "intro.mp4", { type: "video/mp4" });
    await userEvent.upload(screen.getByLabelText("Video file"), file);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(api.calls.find((c) => c.path === "media/uploads/video")?.body).toEqual({ lesson_id: "l1", title: "Intro video" });
    expect(provider).toHaveBeenCalledWith("https://upload.example.com/vdo", expect.objectContaining({ method: "POST", credentials: "omit" }));
    const form = (provider.mock.calls[0] as unknown as [string, RequestInit])[1].body as FormData;
    expect([...form.keys()]).toEqual(["policy", "key", "file"]);
    expect(within(screen.getByRole("list", { name: "Lesson media" })).getByText("Ready")).toBeInTheDocument();
  });

  it("shows the api problem when the video provider isn't configured", async () => {
    const provider = vi.fn();
    vi.stubGlobal("fetch", provider);
    const api = mockApi({ "POST media/uploads/video": problem(503, "provider_unavailable", "Video provider not configured", { detail: "VdoCipher credentials are missing." }) });
    restore = api.restore;
    renderWithProviders(<LessonMediaPanel lesson={lesson()} editable />);
    await userEvent.upload(screen.getByLabelText("Video file"), new File(["x"], "a.mp4", { type: "video/mp4" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Video provider not configured");
    expect(alert).toHaveTextContent("VdoCipher credentials are missing.");
    expect(provider).not.toHaveBeenCalled();
  });

  it("uploads a PDF as a lesson file (MED-02)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    const api = mockApi({
      "POST media/uploads/file": { status: 201, body: { purpose: "lesson_file", s3_key: "content/lesson_file/x/notes.pdf", upload: { url: "https://bucket.example.com", fields: { key: "k" } }, expires_at: "2026-11-03T10:00:00Z", max_bytes: 3, lesson_asset_id: "a2" } },
      "GET media/assets/a2/status": { body: { id: "a2", asset_type: "pdf", provider: "s3", status: "failed", scan_status: "infected", mime_type: "application/pdf", size_bytes: 3, duration_seconds: null } },
    });
    restore = api.restore;
    renderWithProviders(<LessonMediaPanel lesson={lesson({ lesson_type: "article" })} editable />);
    expect(screen.queryByLabelText("Video file")).not.toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText("PDF or captions file"), new File(["pdf"], "notes.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "media/uploads/file")?.body).toEqual({ purpose: "lesson_file", filename: "notes.pdf", content_type: "application/pdf", size_bytes: 3, lesson_id: "l1", asset_type: "pdf" });
  });

  it("reports a provider rejection", async () => {
    await expect(postToProvider({ url: "https://x.example.com", fields: {} }, new File(["a"], "a"), (async () => new Response("denied", { status: 403 })) as typeof fetch)).rejects.toThrow(/HTTP 403/);
  });
});

describe("MediaLibrary (CMS-012)", () => {
  it("lists lessons of the chosen course with their media status", async () => {
    const c = course();
    c.draft!.modules[0]!.lessons[0]!.assets = [{ id: "a1", asset_type: "video", status: "processing" }];
    const api = mockApi({
      "GET studio/courses": { body: { data: [{ id: "c1", title: "DSA Basics", status: "draft", draft: { id: "cv1", status: "draft", version_no: 1 } }], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "GET studio/courses/c1": { body: c },
    });
    restore = api.restore;
    renderWithProviders(<MediaLibrary />);
    await userEvent.selectOptions(await screen.findByLabelText("Course"), "c1");
    expect(await screen.findByText("Processing")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Manage media" })).toHaveLength(3);
  });
});

const qVersion = (over: Record<string, unknown> = {}) => ({
  question_version_id: "v1",
  version_no: 1,
  status: "in_review",
  difficulty: 2,
  stem_html: "Pick the prime",
  default_marks: "1",
  default_negative: "0",
  expected_seconds: null,
  authored_by: "u1",
  reviewed_by: "u2",
  published_at: null,
  options: [
    { option_id: "o1", label: "A", html: "4", is_correct: false },
    { option_id: "o2", label: "B", html: "5", is_correct: true },
  ],
  explanation_html: "5 is prime",
  answer_key: null,
  ...over,
});
const question = (over: Record<string, unknown> = {}) => ({
  question_id: "q1",
  organization_id: null,
  question_type: "mcq_single",
  primary_topic_id: "t1",
  status: "draft",
  current_version_id: null,
  created_by: "u1",
  keys_visible: true,
  tags: [],
  versions: [qVersion()],
  ...over,
});

describe("QuestionEditor (ADM-48 / ADM-51 / ADM-55)", () => {
  it("hides Publish from the author of an approved version", async () => {
    const api = mockApi({ "GET studio/questions/q1": { body: question() }, "GET me": { body: { user: { id: "u1" } } }, "GET placement/subjects": { body: subjects } });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="q1" />);
    expect(await screen.findByText(/Another content manager must publish/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
  });

  it("lets another manager publish, shows the topic name and the reviewer comment", async () => {
    const api = mockApi({
      "GET studio/questions/q1": { body: question({ versions: [qVersion({ review_comment: "Tighten option B wording" })] }) },
      "GET me": { body: { user: { id: "u3" } } },
      "GET placement/subjects": { body: subjects },
    });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="q1" />);
    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
    expect(screen.getByText("Tighten option B wording")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText(/^Topic/)).toHaveDisplayValue("Aptitude › Percentages"));
  });

  it("sends the retire reason (PLC-11)", async () => {
    const api = mockApi({
      "GET studio/questions/q1": { body: question({ status: "active", versions: [qVersion({ status: "published", published_at: "2026-11-01T00:00:00Z" })] }) },
      "GET me": { body: { user: { id: "u3" } } },
      "GET placement/subjects": { body: subjects },
      "POST studio/questions/q1/retire": { body: {} },
    });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="q1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));
    const dialog = await screen.findByRole("dialog", { name: "Retire this question?" });
    await fill(within(dialog).getByLabelText(/^Reason/), "Duplicate of Q-114");
    await userEvent.click(within(dialog).getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "studio/questions/q1/retire")).toBe(true));
    expect(api.calls.find((c) => c.path === "studio/questions/q1/retire")?.body).toEqual({ reason: "Duplicate of Q-114" });
  });

  it("picks the topic of a new question from the taxonomy", async () => {
    const api = mockApi({ "GET placement/subjects": { body: subjects } });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="new" />);
    const pick = await screen.findByLabelText(/^Topic/);
    await waitFor(() => expect(pick).toBeEnabled());
    expect(within(pick).getByRole("option", { name: "Aptitude › Ratios" })).toBeInTheDocument();
  });
});

describe("ReviewQueue server filter (ADM-54)", () => {
  it("asks PLC-04 for awaiting_review and never offers Review for approved items", async () => {
    const item = (id: string, reviewed: boolean) => ({
      question_id: id,
      organization_id: null,
      question_type: "mcq_single",
      primary_topic_id: "t1",
      status: "draft",
      latest_version: { question_version_id: `v-${id}`, version_no: 1, status: "in_review", reviewed, difficulty: 2, stem_html: `Stem ${id}` },
    });
    const api = mockApi({
      "GET studio/questions": { body: { items: [item("q1", false), item("q2", true)], limit: 200, offset: 0 } },
      "GET studio/courses": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 100 } } },
    });
    restore = api.restore;
    renderWithProviders(<ReviewQueue />);
    expect(await screen.findByRole("link", { name: "Stem q1" })).toBeInTheDocument();
    expect(screen.queryByText("Stem q2")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Review" })).toHaveLength(1);
    expect(api.calls.find((c) => c.path === "studio/questions")?.url).toContain("version_status=awaiting_review");
  });
});

describe("QuestionBank search (w2b R4)", () => {
  it("sends the stem search as q and shows the retired reason", async () => {
    const row = { question_id: "q1", organization_id: null, question_type: "mcq_single", primary_topic_id: "t1", status: "retired", retired_reason: "Duplicate of Q-114", latest_version: { question_version_id: "v1", version_no: 1, status: "retired", difficulty: 2, stem_html: "<p>What is 2+2?</p>" } };
    const api = mockApi({ "GET studio/questions": { body: { items: [row], limit: 25, offset: 0 } } });
    restore = api.restore;
    renderWithProviders(<QuestionBank />);
    expect(await screen.findByText("Retired: Duplicate of Q-114")).toBeInTheDocument();
    await fill(screen.getByLabelText("Search question text"), "2+2");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("q=2%2B2"))).toBe(true));
  });
});

describe("TaxonomyManager (CMS-008)", () => {
  it("creates a topic under a subject (PLC-02)", async () => {
    const api = mockApi({ "GET studio/topics": { body: subjects }, "POST studio/topics": { status: 201, body: {} } });
    restore = api.restore;
    renderWithProviders(<TaxonomyManager />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a topic under Aptitude" }));
    const dialog = await screen.findByRole("dialog");
    await fill(within(dialog).getByLabelText(/^Name/), "Time and Work");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Time and Work", slug: "time-and-work", parent_id: "s1", position: 0 });
  });

  it("lists deactivated topics from GET studio/topics so they can be reactivated (w2b R4)", async () => {
    const tree = { items: [topic("s1", "Aptitude", [{ ...topic("t1", "Old topic", [], "s1"), is_active: false }])] };
    const api = mockApi({ "GET studio/topics": { body: tree } });
    restore = api.restore;
    renderWithProviders(<TaxonomyManager />);
    expect(await screen.findByText("Old topic")).toBeInTheDocument();
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "placement/subjects")).toBe(false);
  });

  it("shows an error state when the taxonomy can't load", async () => {
    const api = mockApi({ "GET studio/topics": problem(500, "internal", "Something went wrong") });
    restore = api.restore;
    renderWithProviders(<TaxonomyManager />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });
});

describe("CompaniesManager (CMS-009)", () => {
  it("validates and builds the PLC-18 body", () => {
    const form = { id: null, company_id: "co1", role_name: "", status: "draft" as const, pattern: [{ section: "", topic_id: "", weight: "0", minutes: "", question_count: "" }], steps: [] };
    expect(Object.keys(validatePath(form)).sort()).toEqual(["pattern.0.section", "pattern.0.topic_id", "pattern.0.weight", "role_name"]);
    const ok = {
      ...form,
      role_name: "GET",
      pattern: [{ section: "Quant", topic_id: "t1", weight: "40", minutes: "30", question_count: "" }],
      steps: [
        { step_type: "test" as const, title: "Mock", topic_id: "", test_id: "t9", is_required: true },
        { step_type: "lesson" as const, title: "Watch", topic_id: "", test_id: "", lesson_key: "lk1", is_required: false },
      ],
    };
    expect(validatePath(ok)).toEqual({});
    expect(pathBody(ok)).toEqual({
      company_id: "co1",
      organization_id: null,
      role_name: "GET",
      status: "draft",
      pattern: [{ section: "Quant", topic_id: "t1", weight: "40", minutes: 30 }],
      steps: [
        { step_type: "test", title: "Mock", is_required: true, test_id: "t9" },
        { step_type: "lesson", title: "Watch", is_required: false, lesson_key: "lk1" },
      ],
    });
  });

  it("creates a company (PLC-17)", async () => {
    const api = mockApi({
      "GET studio/companies": { body: { items: [] } },
      "GET placement/subjects": { body: subjects },
      "GET studio/tests": { body: { items: [] } },
      "POST studio/companies": { status: 201, body: {} },
    });
    restore = api.restore;
    renderWithProviders(<CompaniesManager />);
    expect(await screen.findByText("No companies yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog", { name: "New company" });
    await fill(within(dialog).getByLabelText(/^Name/), "Acme Systems");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add company" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Acme Systems", slug: "acme-systems", industry: null, hub_status: "draft", description_md: null });
  });
});
