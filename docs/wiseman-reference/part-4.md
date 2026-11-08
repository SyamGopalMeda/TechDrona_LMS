# Reference LMS demo — Part 4 (video ≈ 47:31 – 59:15)

Source: 59 screen-recording frames (c_00085535 … c_00106639; time = frame/30). The transcript is empty for this range, so everything below comes from the screen only.
The product is called "the reference platform". Its branding, logos and product names are deliberately left out. Only its functions are described.

Scope note: a large part of this segment is off-topic. The presenter visits WhatsApp, Google Play Console, Google AI Studio, ChatGPT and Google Meet. Those parts appear in the timeline only where they explain a reference-platform workflow, for example the AI prompt round-trip for bulk import. Personal data seen on screen (phone numbers, emails, chat contents) is left out on purpose.

---

## 1. Timeline

| Video time | Screen / URL path | What the presenter does |
|---|---|---|
| 47:31 – 47:37 | `/app/articles/<id>` (Articles app, header subtitle "Verified lessons, ready to share"). Article: "Understanding Variables and Dynamic Typing in Python" | Scrolls through an AI-generated article: code blocks with output panels, diagrams, "Key idea" / "Watch out" callouts, "Try it yourself" exercises, "What's Next", then back to the top. |
| 47:37 – 48:09 | Same article, top of page | Shows the article header toolbar (Verified, Public, Regenerate, delete, Publish & share) and the verification banners, then scrolls the body again. |
| 48:45 – 48:46 | `/app/articles/<other id>`: "Writing Clean Functions with Arguments and Return Values" | Opens a second article whose status is **Not published**. |
| 48:59 – 49:00 | Same | Opens the macOS Chrome Dock menu (profiles/windows). Not a platform feature. |
| 49:01 – 50:00 | WhatsApp Web, Google Play Console (blank), Google AI Studio API Keys / Gemini API Spend page | Off-topic. Shows the cloud AI API keys and monthly spend (a project is used to power the platform's AI). Not a platform feature. |
| 50:23 | `/app/articles/<id>` ("Writing Clean Functions…") | Back on the article. |
| 50:46 – 51:25 | `/app/question-banks`: **Bulk import via prompt** modal | Opens Bulk import. Picks question type **Code**, keeps How many = 5, types "Python Sets" in Extra instructions, scrolls to the generated prompt, clicks **Copy prompt**. |
| 51:29 – 52:00 | chatgpt.com | Pastes the prompt into an external chat model and gets a JSON array of 5 coding questions with test cases. |
| 52:05 | Marketing site (root domain) section "Simple for students." | Briefly shows the marketing page with mock-ups of the student home and a learning path. |
| 52:07 – 53:28 | `/app/question-banks`: Bulk import modal | Pastes the JSON into Step 2. Validation reports **"1 problem found"** (invalid JSON). Re-copies the clean JSON from ChatGPT, pastes again, clicks **Validate & import**. Toast: "Questions imported to your bank." Counters go from 21 banks / 128 questions / 8 subjects to 22 / 133 / 9. |
| 54:00 – 55:00 | `/app/question-banks`: list page | Shows the bank cards in grid view, then switches to list view. |
| 55:18 – 56:00 | `/admin`: Platform admin → Clients → client detail modal | Opens a client (institution) record and shows **Authorized tools** checkboxes, the AI (Gemini) section with **Premium** toggle, model, usage caps, code-execution key, and **Block this client…**. |
| 56:45 – 57:00 | `/admin` → marketing site home | Closes the modal and navigates to the marketing home page ("Every classroom tool, with a mentor built in"), hovering **Sign in** (link to `/login`). |
| 57:40 – 59:00 | chatgpt.com | Shows the full prompt text that the platform generated (JSON schema for coding questions). |
| 59:09 – 59:15 | Google Meet | Presenter stops presenting and leaves the meeting. End of segment. |

---

## 2. Features

### 2.1 AI-generated, auto-verified Articles (lessons)
**Role:** instructor/admin (author). Readers are students or the public once the article is shared.
**Seen:** 47:31 – 48:46, 50:23. URL `/app/articles/<articleId>`.

**App header:** app tile with the subtitle "Verified lessons, ready to share", a back arrow, an organisation switcher chip ("Skillyheads", the tenant name) and a user avatar menu.

**Article toolbar (top of article):**
- `← Articles` (back to the article list)
- Status chip **Verified** (green check)
- Visibility chip, with two values seen:
  - **Public** (globe icon) on the first article
  - **Not published** (lock icon) on the second article
- **Regenerate** button (circular-arrow icon)
- Delete button (red trash icon)
- **Publish & share** primary button (share icon)

**Banners at the top:**
- Notice (light red/orange): "1 sample output(s) were replaced with the real program output." This means the system runs the code samples and replaces any wrong sample output with the real output.
- Verification bar (green check):
  - Article 1: "Fact-checked by a second AI review (2 fixes applied) · 7 of 7 code samples run and match their output"
  - Article 2: "Fact-checked by a second AI review (0 fixes applied) · 7 of 7 code samples run and match their output"

**Article metadata:**
- Title (H1)
- Subtitle/summary line
- Level chip: **Beginner** (graduation-cap icon)
- Estimated study time: "About 1.5 h of study" / "About 1 h of study" (clock icon)

**Body content blocks seen:**
- Headings (H2) and sub-headings (H3, coloured, e.g. "Comparing Objects: Identity vs Equality")
- Paragraphs with bold keywords and inline code spans
- Code block: language label (`python`) at top left, **Copy** button at top right, dark theme
- **Output** panel under the code block (terminal icon + "Output"), showing the program's stdout
- Diagrams: box-and-arrow diagrams (e.g. "Variable Names (References)" → "Computer Memory (Objects)"), and vertical flowcharts (e.g. "Assign product_status = 'Available'" → … → "Unreferenced 'Available' object garbage collected"). They appear to be rendered diagrams (Mermaid-like); the format is (unclear).
- Callouts:
  - **Key idea** (blue, key icon)
  - **Watch out** (amber, warning-triangle icon)
- Exercise cards: **Try it yourself** (pink, with a pencil/ruler-style icon). Each has a problem statement and a collapsible **▶ Show answer**.
- Closing section **What's Next**, which links to the next chapter (e.g. "In the next chapter, Chapter 4: … you will build upon…"). This shows that articles are part of a chapter sequence (Chapter 1, 2, 3… and Chapter 5 referenced).

**Right sidebar "On this page"** (table of contents, sticky). Examples:
- Article 1: Variables Are References, Not Containers · Memory Allocation and Object Identity · How Dynamic Typing Works in Python · Type Inspection and Type Hints · Common Mistakes and How to Avoid Them · Summary of Key Points · Exercises · What's Next
- Article 2: Positional and Keyword Arguments · Setting Sensible Default Parameters · Enforcing Keyword-Only Arguments · Returning Data Cleanly · Function Interface Comparison · Exercises with Solutions · Summary of Key Points · What's Next

**Workflow implied:**
1. An article is generated by AI (generation UI not shown in this segment).
2. A second AI review fact-checks it and applies fixes.
3. Code samples are executed and their outputs checked or replaced.
4. The article is marked Verified.
5. The author can Regenerate, Delete, or Publish & share (Not published → Public).

---

### 2.2 Question Banks: list page
**Role:** instructor/admin.
**Seen:** 53:28 – 55:00. URL `/app/question-banks`.

- App header subtitle: "Store and manage questions".
- Page title **Question Banks**, with the subtitle "Author reusable questions for co-practice, assessments, polls and more."
- Header buttons:
  - **Bulk import** (document icon)
  - **Generate with AI** (sparkle icon)
  - **+ New bank** (primary, green)
- Stat cards:
  - **Banks** (21 → 22 after import)
  - **Questions** (128 → 133)
  - **Subjects** (8 → 9)
- Search field "Search banks..." with a result count on the right (22).
- View toggles: **grid** and **list** icons.
- **Grid view card:** coloured bank icon, "N questions" badge at top right, bank name (bold), subject line below (e.g. "ABAP-OOPS", "programming", "Number Series", "Arrays", "Basics of programming"), and an **Open bank →** link. Bank URL pattern: `/app/question-banks/<bankId>`.
- **List view row:** icon, name, subject, "5 Qs" / "10 Qs" count, and an → arrow.
- Example banks: ABAP-OOPS bank (5), Adhithya-Lists-MCQ (5), Adhithya-Py-Lists-1 (5), AptitudeTest-1 (10), Arrays (5), Arrays & Strings (10).
- A loading indicator (animated dots) shows while the list refreshes after import.
- Toast at bottom right: "Questions imported to your bank." with a green check and a close ×.

---

### 2.3 Bulk import via prompt (bring-your-own-LLM question generation)
**Role:** instructor/admin.
**Seen:** 50:46 – 53:28 (prompt text 57:40 – 59:00).

**Modal title:** "Bulk import via prompt" (partly hidden by the screen-share bar; reads "Bulk import v… prompt"). Close × at top right.

**Fields:**
- **Question type**: tile selector, one choice:
  - **Code** (`</>` icon)
  - **MCQ** (list icon). This was the default selection when the modal opened.
  - **Essay** (pencil icon)
  - **Poll** (bar-chart icon)
  - **Survey** (clipboard icon)
  - **Words** (cloud icon; word cloud)
- **How many?**: number input, default **5**
- **Subject (optional)**: placeholder "e.g. DBMS"
- **Topic (optional)**: placeholder "e.g. normalization"
- **Extra instructions (optional)**: textarea, placeholder "Difficulty, style, constraints..." (the presenter typed "Python Sets")
- **Save to**: dropdown, default "**+ New bank**". It presumably also lists existing banks (not expanded on screen).
- **New bank name**: placeholder "Auto-named if blank"

**Step 1 panel:** "Step 1 — copy this prompt into any chat model". Helper text: "Paste it into Claude, ChatGPT, Gemini or any model. Copy the JSON it returns and paste it in Step 2 below." It has a **Copy prompt** button and shows a read-only dark code box with the generated prompt.

**Generated prompt contents (Code type), as seen in ChatGPT at 57:40:**
- "You are an expert assessment author. Generate exactly 5 Programming question(s) for the subject "Python" on the topic "Sets"." Subject and topic were filled in, apparently from the extra instructions or inference (unclear).
- "Additional instructions: Python Sets"
- "Return ONLY a JSON array — no prose, no explanations, no markdown, no code fences. The array must contain exactly 5 objects, each with this exact shape:"
- Schema for a coding question:
  - `"description"`: "the full problem statement"
  - `"sampleInput"`: "example input"
  - `"sampleOutput"`: "expected output for that input"
  - `"acceptanceCriteria"`: "how a correct solution is judged (optional, use \"\" if none)"
  - `"testCases"`: `[ { "input": "stdin for one case", "expectedOutput": "exact stdout for that input", "hidden": false } ]`
  - `"tags"`: ["2-5 short lowercase tags"]
- "Rules:"
  - Output must be valid JSON that JSON.parse can read — a single array of 5 objects
  - Do NOT wrap the JSON in ``` fences or add any text before or after it
  - Any double quote that appears INSIDE a string value MUST be escaped as \" (or w… (truncated))
  - "tags" must be an array of 2-5 short lowercase strings
  - Include realistic, consistent sampleInput and sampleOutput
  - Provide 4-6 "testCases" for automatic grading. Each has the exact stdin in "inpu… (truncated)
  - Begin the response with "[" and end with "]"

So each coding test case has a **hidden: true/false** flag (visible sample cases vs hidden grading cases). The model output seen included cases such as `"input": "4\n10 20 30 40", "expectedOutput": "4", "hidden": true`, plus tags `["python","sets","unique-count","collections"]`.

**Step 2:** "Step 2 — paste the model's JSON response". Textarea placeholder `[ { "description": "…", "tags": ["…"] }, … ]`.

**Validation and error handling:**
- Footer buttons: **Cancel** and **Validate & import**. Validate & import is disabled until something is pasted.
- If validation fails, an error panel appears:
  - Header: "⚠ 1 problem found"
  - **Copy for the model** button
  - Message: "The pasted text isn't valid JSON (Unexpected character "\n" at position 2). This is usually an unescaped double quote inside a value — e.g. "s = "abc"". Ask the model to return strictly valid JSON with all inner quotes escaped as \" (or use single quotes inside strings), then paste again."
  - Footer hint: "Copy these back to the model, ask it to fix and return corrected JSON, then paste again."
  - Cause in the demo: the first paste carried HTML-escaped characters (`&#x20;`, trailing `\`).
- On success the modal closes, the toast "Questions imported to your bank." appears, and the counters update. A new bank was auto-created: Banks +1, Questions +5, Subjects +1.

---

### 2.4 Platform admin: Clients (multi-tenant institution management)
**Role:** platform super-admin. Header badge "Platform admin".
**Seen:** 55:18 – 57:00. URL `/admin`.

**Left nav, section "PLATFORM":**
- **Clients**
- **AI Models**
- **Demo requests**

**Clients page:**
- Title "Clients", subtitle "Institutions registered on the platform"
- Buttons: **Refresh**, **+ Add client**
- Search: "Search by name, code, or email"
- Row: institution name + client code (e.g. "SkillMat SKM", "Skillyheads TEST"), contact person · email, tool count ("7 tools", "15 tools"), status badge "**Approved**"

**Client detail modal** (title = institution name):
- Status chip **Approved**
- Read-only fields: **Client code**, **Contact person**, **Mobile**, **Email**
- **Authorized tools**: a grid of tool cards. Each card has an icon, a name, a category sub-label and a checkbox. Checked cards are highlighted.

  | Tool | Category label | Checked in demo |
  |---|---|---|
  | Co-practice | Practice | ✔ |
  | Options | Practice | ✔ |
  | Essays | Practice | – |
  | Polls | Practice | – |
  | Wordmaps | Practice | – |
  | Surveys | Management | ✔ |
  | Co-assess | Practice | – |
  | Discuss | Practice | – |
  | Assignment Manager | Management | ✔ |
  | Evaluation | Management | ✔ |
  | (more below, scrolled past; the client shows "15 tools") | | (unclear) |

- **AI (Gemini)** section, with a "Key set" badge:
  - Toggle: **"Premium — unlocks AI question generation"** (on)
  - **Model** dropdown (value `gemini-3.5-flash`)
  - **API key (admin)**: input, placeholder "Enter to replace"
  - **[Platform] interactions / activity**: input "Unlimited". Helper: "Default cap per assessment/assignment." This caps how many AI-mentor interactions a student gets per activity.
  - **Total [platform] interactions**: input "Unlimited". Helper: "Across all students & activities."
  - **Judge0 Extra CE key (RapidAPI)** ("Key set" badge): input "Enter to replace". Helper: "Enables in-app compile & run for programming questions."
  - **Save AI** button
  - Note: "Clients can set their own key, which overrides this one."
- Danger zone: **Block this client…** (red, ban icon)
- Footer: **Close**, **Save tools**

---

### 2.5 Student-facing views (marketing mock-ups only; tiny, mostly unreadable)
**Seen:** 52:05 (marketing page section "Simple for students.": "Students see only the apps you give them, the work that's due, and how far along their path they are.")

- **Student home mock-up:** greeting "Hi Aarav", subtitle "Pick an app to get started" (approximate), and a "My Assignments" card ("Assignments allocated to you by teacher…", unclear). An app tile grid shows only the apps granted to the student: **Co-practice** ("Practice coding with a mentor…", unclear), **Exam** ("Sit your scheduled exams", approximate), **Paths** ("Follow your learning path", approximate), **Engage** ("Live polls, word clouds & quizzes"). Each tile has an "Open →" link and a small status pill (unclear).
- **Learning path mock-up:** "My paths" breadcrumb and a Refresh link. Path card "DSA Foundations · 6 weeks" with a description (unclear), a score figure ("50", unclear) and a circular progress ring ("50%"). On the left is a vertical step list with green check marks for completed steps (e.g. "Big-O notation primer", "Linked lists, visually", "Week 6 · Linked Lists & Stacks"), then later items without checks ("BST insert & delete", another item (unclear), "Java Mid-term · Proctored"). The right pane shows the selected step "Week 6 · Linked Lists & Stacks" with a status pill (unclear), a line of text (unclear) and an **Open assignment ↗** button. This suggests that path steps can be assignments and proctored exams, and that completion is tracked per step.

Marketing home hero (57:00) lists the platform scope: "Question banks, coding practice, proctored exams, live sessions, surveys, grading and reports in one place — with [an] AI mentor that guides students without handing over the answer." Nav: How it works · Live sessions · All tools · Sign in · Book a demo. CTAs: "Book a free demo", "Explore the tools".

---

## 3. Not shown in this segment
- Assignment creation form, assessment/exam creation, proctoring settings (fullscreen, tab-switch, webcam), poll creation/live results, and the learning-path builder do not appear in these frames. They appear only as names in the tool list or the marketing mock-ups.
- The "Generate with AI" (in-app) flow, the "+ New bank" flow and the inside of a bank (`/app/question-banks/<id>`) were not opened.
- The admin pages "AI Models" and "Demo requests" were not opened.
