# Reference LMS demo — Part 1 (video 00:00 – 19:41)

Source: screen-recorded demo, frames `c_00000000` – `c_00035443` (59 sampled frames, roughly one every 30–60 s plus scene changes). There was no transcript, so everything here comes from what is visible on screen.

Conventions:
- Labels in "quotes" are copied exactly from the screen.
- The product brand name is replaced by **[Brand]**. Its AI tutor persona is called **[AI mentor]**. Do not copy the brand, logo or mascot.
- Anything blurred (modal open/close transitions) is marked *(unclear)*.
- The org shown is the presenter's own ("Skillyheads"). Person names and emails are demo data.
- URLs are on the product's tools sub-domain. Only the paths are given below.

---

## 1. Timeline

| Video time | Screen / URL path | What the presenter does |
|---|---|---|
| 00:00 | Public marketing home page (`/`) | Scrolls the tool tiles: Co-practice, Question Banks, Assignment Manager, Exam, Evaluation (partly visible). |
| 01:00 | `/console` (Admin console, org "Skillyheads") | Shows the admin overview and the "YOUR ENABLED APPS" grid. Hovers Question Banks. |
| 01:11 | `/app/question-banks` | Opens Question Banks. Clicks "Generate with AI". |
| 01:31 – 02:00 | `/app/question-banks`, "Generate with AI" modal | Types Topic "Python-ListComprehensions" and General instructions "Moderate difficulty". Switches Question type from MCQ to Code, How many = 5, Save to = "+ New bank", leaves New bank name blank. |
| 03:00 | Same modal, review step | 5 drafted questions shown. Clicks "Save 5 to bank". Toast: "AI questions saved to your bank." |
| 03:08 – 03:15 | `/app/question-banks/{bankId}` | Opens the new bank "Adhithya-Py-Lists-1" and an "Edit question" modal (sample input/output), then closes it. |
| 04:00 | `/console` | Back to the console. Hovers Assignment Manager. |
| 04:07 | `/app/assignment-manager` | Assignments list. Clicks "New assignment". Modal: name and total marks. |
| 04:37 | `/app/assignment-manager/{assignmentId}` | Toast "Assignment created — add sections & questions." |
| 05:00 – 06:23 | Assignment editor | Names it "Adhithya-Lists", Total marks 50. Ticks the AI-help checkbox and sets interactions to 0, later 1. Clicks "Import from bank", picks bank "Adhithya-Py-Lists-1" (5 code questions) and adds them to Section 1. Sets 10 marks per question. |
| 06:11 – 06:23 | (Video-call window, then the public site "Simple for students." section) | Side detour: switches tabs briefly and returns. |
| 07:00 | Assignment editor | All 5 questions at 10 marks (Q4 still 0 at this point). |
| 07:23 – 09:00 | "Allocate — Adhithya-Lists" modal | Picks a batch and sets schedule dates. Picks "Evaluator engine per section" (dropdown opened) and Human evaluators. Clicks "Allocate to batch". |
| 09:34 | Assignment editor | Status shows "✓ 50 / 50 allocated", interactions per learner = 1. |
| 10:00 | `/login` | Logs out and logs in as the student (srikrishna…). |
| 10:29 | `/assignments/{assignmentId}` (student attempt) | Student coding workspace with the [AI mentor] side panel ("1 of your … interactions left"). |
| 10:49 – 11:06 | External AI chatbot in another tab | Presenter pastes the question into an external chatbot, copies its code and pastes it back into the editor. This shows a copy/paste loophole: assignments are not proctored. |
| 12:00 – 13:00 | Student attempt | Uses "Guide", which spends the last interaction ("0 of your … interactions left"), then "Run". Result: "Accepted 0.058s 25 MB". Clicks "Submit assignment". |
| 13:01 | Student → "My assignments" | Redirected after submitting. |
| 14:00 – 14:39 | `/app/evaluation/assignments/{assignmentId}` (admin) | Evaluation page. Opens "Review — Srikrishna" and runs AI grading. |
| 15:00 – 15:31 | `/login` → `/assignments/{assignmentId}` (student) | Student sees "Submitted successfully, Final score: 9 / 50" with per-question scores. Opens the Question 1 feedback modal. |
| 16:00 | `/login` | Logs out again. |
| 17:00 – 18:44 | `/app/assessment-manager/{assessmentId}` (admin) | Assessment (proctored exam) editor. Edits conduct instructions and toggles, adds a "Programming" section, imports 2 questions and sets 10 marks each. Opens "Schedule — Adhithya-Py-Lists". |
| 19:00 | `/login` | Logs in as the student. |
| 19:34 | `/app/exam/{examId}` (student) | Exam workspace with a 29:59 countdown and a "Submit" button. No AI panel. |
| 19:41 | (Other tab, file storage) | Presenter switches away. End of part 1. |

---

## 2. Features

### F1. Admin console / app launcher
- **Role:** admin (header badge "Admin").
- **URL:** `/console`
- **Header:** product logo + "Admin" badge on the left. On the right, an org switcher button ("Skillyheads", building icon) and an avatar dropdown ("V").
- **Greeting:** "Welcome, Krishna", with the org name "Skillyheads" below it.
- **Left sidebar** (under the org name heading "SKILLYHEA…" (truncated)): "Overview", "Question Banks", "Batches", "Users", "Practice content", "Settings".
- **Stat cards:** "5 Users", "2 Batches".
- **"YOUR ENABLED APPS"** grid. Each card has an icon, title, one-line description and a → arrow:
  - "Co-practice" – "Practice coding with a mentor be…" (truncated)
  - "Options" – "Run quick multiple-choice quizzes"
  - "Surveys" – "Feedback forms with AI analysis"
  - "Assignment Manager" – "Create assignments, allocate to b…" (in the app header: "Create assignments, allocate to batches, evaluate")
  - "Evaluation" – "Grade submissions & publish res…" (in the app header: "Grade submissions & publish results")
  - "Assess Studio" – "Build proctored assessments"
  - "Reports" – "Monitor activity & extract reports"
  - "Question Banks" – "Store and manage questions"
  - "Engage" – "Live polls, word clouds & quizzes"
  - "Assessment Manager" – "Set up timed, proctored exams"
  - "Exam" – "Sit your scheduled exams"
  - "Paths Manager" – "Design guided learning paths"
  - "Articles" – "Verified lessons…" (truncated)
  - "Paths" – (description unclear)
  - "Reports" (second card) – "Completion, quality & trends"
- Each app has its own route (`/app/question-banks`, `/app/assignment-manager`, `/app/evaluation`, `/app/assessment-manager`, `/app/exam`). Inside an app, the header shows a back arrow, the app icon, the app name and its tagline.
- **Marketing claim:** students only see the apps the admin enables for them: "Students see only the apps you give them, the work that's due, and how far along their path they are." The public site's student-home preview shows: "Hi Aarav", "My Assignments – Assignments allocated to your batches — take them and see results", app tiles Co-practice / Exam / Paths each with "Open →", and a "MANAGEMENT" group containing Engage. It also previews a path view: "DSA Foundations · 6 weeks", a weekly step list with status icons (e.g. "Week 6 · Linked Lists & Stacks" "Completed — credits released by your evaluator", "Open assignment"), and the last step "Java Mid-term · Proctored". This is a small marketing preview, so detail is limited.

### F2. Question Banks
- **Role:** admin/instructor.
- **URL:** `/app/question-banks`

**List page**
- Title "Question Banks"; subtitle "Author reusable questions for co-practice, assessments, polls and more."
- Buttons: "Bulk import", "Generate with AI", "+ New bank".
- Stat cards: "19 Banks", "118 Questions", "8 Subjects".
- Search/filter bar *(unclear)*, a count ("19"), and a grid/list view toggle.
- Bank cards show an icon, bank name, subject (e.g. "ABAP-OOPS bank" / "ABAP-OOPS"; "Arrays & Strings" / "Basics of programming"), a "N questions" badge and an "Open bank →" link *(partly unclear)*.
- The marketing page says there are "six types" of question. In the AI generator these are Code, MCQ, Essay, Poll, Survey and Words.

**"Generate with AI" modal**
- Banner: "Premium — [Brand] drafts questions you can review before saving."
- Mode tabs (pills): "On a topic" (selected), "For a company", "On a subject", "Specific test". Only the "On a topic" fields are shown in the demo.
- "Topic *" (required) text input. Example: "Python-ListComprehensions".
- "General instructions" textarea. Example: "Moderate difficulty".
- "Question type" single-select tiles: "Code", "MCQ" (default selected), "Essay", "Poll", "Survey", "Words".
- "How many?" number input (default 5).
- "Save to" dropdown. The default value is "+ New bank"; existing banks are presumably also listed.
- "New bank name" input with placeholder "Auto-named if left blank".
- Buttons: "Cancel", "Generate".

**Review step (same modal)**
- Header line: "5 drafted · 5 selected", with a "Clear" link.
- Each drafted question is a card with a type icon, the full question text, auto-generated tags (e.g. "python", "list-comprehension", "matrix", "filtering", "moderate") and a selection checkbox (checked by default).
- Buttons: "Back", "Save 5 to bank" (the count follows the selection).
- On save, toast "AI questions saved to your bank."

**Bank detail page** (`/app/question-banks/{bankId}`)
- Bank title (e.g. "Adhithya-Py-Lists-1"), with subject and count below ("programming · 5 questions").
- Buttons: "From bank" (copy from another bank), "Bulk import", "AI", "+ Add question".
- Type filter chips with counts: "All 5", "Code 5".
- Search box "Search questions & tags" and an "All tags" dropdown.
- Question rows: a type badge ("CODE"), question text truncated to 2 lines, tag chips, and edit (pencil) and delete (trash) icons.

**"Edit question" modal (Code/Programming type)**
- Type header card: "Programming", with a subtitle *(unclear)*.
- "Question description" textarea.
- "Question image" "(optional)", with an "Add question image" upload area.
- "Sample input" and "Sample output" side by side. Example: input `3 / 5 1 2 / -1 4 2 / 0 3 2`, output `0 1`.
- More fields probably sit below, e.g. test cases (not shown; the modal was scrolled only partway).
- Buttons: "Cancel", "Save".

**"Import questions from a bank" picker** (reused by Assignment Manager and Assessment Manager)
- "Search banks…" input, plus a sort dropdown ("Newest first").
- Category chips with counts: "All categories 20", "ABAP-OOPS 1", "Arrays 1", "Basics of programming 1", "College Student Feedback 1", "HLDs 1", "Java 2", "Number Series 1", "programming 11", "Uncategorised 1".
- Banks are grouped by kind, e.g. "PROGRAMMING BANKS 12".
- Bank cards show name, subject, a "5 Qs" badge, a type-count chip ("5 Code"), hashtags (#python #list-comprehension #moderate) and "Created 5 Nov 2026 · Last added 5 Nov 2026".
- Clicking a bank drills in. It shows "← All banks", bank name and "programming · 5 questions", a "Select entire bank (5)" link, and a checkbox list of questions.
- Buttons: "Cancel", "Add to section".

### F3. Assignment Manager (create assignment)
- **Role:** admin/instructor.
- **URL:** `/app/assignment-manager`

**List page**
- Title "Assignments". Subtitle *(partly unclear)*: "…with sections and marks. Allocate them to batches next."
- Button "+ New assignment", plus a grid/list toggle and a search bar.
- Cards show title, "N section(s) · N questions", a status pill *(unclear)*, and "Edit →" and "Clone" actions. Examples: "Aptitude TEst-I", "Audio Self-introduction Preparation and Scripting" (2 sections · 6 questions), "Build an Object-Oriented ALV … Report Assignment", "DSA-Java".

**"New assignment" modal**
- "Assignment name *" (placeholder "Mid-term — DSA").
- "Total marks *" (default 100).
- Buttons: "Cancel", "Create".
- On create, toast "Assignment created — add sections & questions." and the editor opens (`/app/assignment-manager/{id}`).

**Editor**
- Top row: an editable assignment name field, then "TOTAL MARKS" (number), then an allocation meter pill ("0 / 50 allocated", orange). When the marks match it turns green: "✓ 50 / 50 allocated". Then "Save" and "Allocate" (primary).
- AI-help setting row:
  - Checkbox "[AI mentor] "Guide me" & "Explain" while taking".
  - "Interactions per learner:" number stepper. The placeholder "Unlimited" appears when empty; 0 and 1 were set in the demo.
  - Hint "Capped by your organization's limit."
- Validation warning (orange): "Allocated marks (0) don't match the total (50). Adjust question marks — some may be 0."
- Section block:
  - Editable section title ("Section 1") and a counter ("0 q · 0 marks", later "5 q · 50 marks").
  - Buttons: "Import from bank" (primary), a duplicate-section icon, and "+ Section".
  - Empty state: "No questions in this section yet. Use Import from bank to add some."
- Question rows inside a section:
  - Number (1–5), type icon, "CODE" badge, truncated text.
  - A per-question "marks" number input (default 0) and a delete (trash) icon.
- "ALLOCATIONS TO BATCHES" panel. Empty state: "Not allocated yet. Use Allocate to assign this to a batch with a schedule and evaluators."

**Rules shown**
- Questions come only from banks (import).
- Marks are set per question, and the sum must equal Total marks.
- Sections are multiple and can be duplicated.
- AI-help usage is capped per learner and further capped by the org limit.

### F4. Allocate assignment to batch (schedule + evaluators + grading engine)
- **Role:** admin/instructor.
- **Modal title:** "Allocate — {assignment name}".
- "Batch" dropdown (placeholder "Choose a batch…").
- "Schedule" group, with four date-time pickers (calendar popup with month navigation, hour, minute, AM/PM; each field has a clear ×):
  - "Visible from"
  - "Visible until"
  - "Can start at"
  - "Must submit by" (placeholder "Select date & time")
  - Demo values: Visible from 4 Nov 2026 22:10; Visible until 6 Nov 2026 22:10; Can start at 5 Nov 2026 22:10; Must submit by 6 Nov 2026 22:10.
- Help text: "Learners see the assignment after "Visible from", can begin after "Can start at", and must submit before "Must submit by". Evaluators can grant late submission per learner."
- "Evaluator engine per section". Each section row has a dropdown and a description line:
  - Options: "Pure AI" (default), "AI + Human", "Pure Objective", "Adaptive", "Pure Manual".
  - The "Pure AI" description is "AI evaluates every question type automatically." The other descriptions were not shown.
- "Human evaluators · optional": a "Search people…" box and a list of org users (name + email) with checkboxes.
- Buttons: "Cancel", "Allocate to batch".

### F5. Student assignment attempt (coding workspace with AI tutor)
- **Role:** student.
- **URL:** `/assignments/{id}`
- **Login page:** "Sign in to reach your apps." Fields: email (placeholder "you@school.edu") and "Password", then "Sign in". Footer: "New organization? Register your institution".
- **Header:** logo, org switcher ("Skillyheads" with up/down chevrons), avatar ("S").

**Left column**
- Assignment title (truncated "Adhithya-L…").
- Remaining-time chip with a clock icon ("23h 54m…"), counting down to the due time.
- "SECTION 1" with numbered question bubbles 1–5; the current one is highlighted.
- "Question 1" with its marks ("10 marks") and the full question text.
- "Submit assignment" (primary) at the bottom.

**Centre**
- "Language" dropdown ("python") and a "Maximize" button.
- Dark code editor with line numbers.
- "Compile & run" collapsible panel:
  - "INPUT (STDIN)" textarea, "Prefilled with the sample input. Programs that read stdin need input here."
  - "OUTPUT" box showing "Running test cases…", then a verdict badge "Accepted" with time "0.058s" and memory "25 MB", then the program output ("0 1").
- Buttons: "Run tests", "Run".
- Footer: "< Prev", "Next >".

**Right panel — AI tutor**
- Header: [AI mentor] avatar and name; counter "1 of your [AI mentor] interactions left" (later "0 of …").
- Intro: "Stuck on a coding question? Ask me to guide or explain — I won't give away the answer."
- Buttons: "Guide (1)" (the count shows remaining uses) and "Explain".
- Feedback card after "Guide":
  - "Where it needs work" (a bullet titled e.g. "Unpacking Syntax: …")
  - "Do this next …"
  - "Rating Progress: 9/10 — Spotless logic, just one syntax tweak!"
  - "Tip …"
- At the limit: "You're out of [AI mentor] interactions for this assignment. Use compile & run to keep checking your work." The Guide and Explain buttons are disabled ("Guide (0)").

**Observation:** assignments have no proctoring. The presenter copied the question to an external chatbot and pasted the answer back without any warning.

### F6. Student result view
- **URL:** `/assignments/{id}` after submit. Back link "← My assignments".
- Banner: ✓ "Submitted successfully", "Final score: 9 / 50". Button "Request modification" (the student asks to change or reopen the submission).
- Per-question list: type icon, "1. {truncated question}", a comment/feedback icon, score ("9 / 10", "0 / 10" …) and a chevron.
- Clicking a question opens the "Question 1" modal, with a small icon pair top-right *(unclear)*. It contains:
  - The question text.
  - The submitted code (dark block), under a heading *(unclear, likely "Your answer")*.
  - Evaluator feedback, under a heading *(unclear)*. Example: "Excellent solution! The code uses list comprehension appropriately for both reading the matrix and identifying strictly diagonally dominant rows, while correctly handling edge cases and output formatting."

### F7. Evaluation (grading & publishing)
- **Role:** admin/instructor/evaluator.
- **URLs:** `/app/evaluation` and `/app/evaluation/assignments/{assignmentId}`.
- Breadcrumb "…ations" (likely "← Evaluations", unclear).
- Title (assignment name), with "1 submission · 50 marks" below.
- Buttons: "Run AI grading", "Publish results" (primary).
- Per-section stat card: "Section 1 — 0 / 50 avg".
- Learner rows: name ("Srikrishna"), status line "0 / 50 finalized · 5 AI pending", and a "Review" button.

**"Review — {learner}" modal** (has an expand icon and a close ×)
- Each question shows:
  - Number, type icon, full question text and max marks ("/ 10").
  - The learner's code (read-only block).
  - A source badge ("✓ AI"), an editable marks field ("10") and an AI feedback comment.
- Footer buttons: "Run AI grading", "Close", "Finalize & save".
- **Workflow:** run AI grading (all submissions, or one learner from the modal) → review and override marks and comments → "Finalize & save" → "Publish results" so students can see them.
- The final student score shown (9/50) suggests only Q1 was answered.

### F8. Assessment Manager (timed, proctored exam)
- **Role:** admin/instructor.
- **URL:** `/app/assessment-manager/{id}`. App tagline: "Set up timed, proctored exams".
- **Top fields:** only partly visible after scrolling. A number field ("30", i.e. duration in minutes, consistent with the 30-minute timer) and a read-only "Total marks: 0" chip, which updates to 2 and then 20 as questions are added.
- **"Conduct instructions"** textarea. Default/example text: "This is a timed, proctored exam. Do not switch tabs, copy/paste, leave this window, or shrink it — these actions are recorded. Once you begin, the timer cannot be paused."
  - This text implies that tab switches, copy/paste, leaving the window and resizing it are detected and logged.
- **Toggles** (all off in the demo):
  - "[AI mentor] "Guide me" during exam" — "Let candidates ask for hints"
  - "Shuffle question order" — "Different order per candidate"
  - "Shuffle MCQ options" — "Different option order per candidate"
- **"SECTIONS"** with a "+ Add section" button.
  - Empty state: "Add a section, then import questions from a bank."
  - Each section has an editable name ("Programming"), an "Import" button (opens the same bank picker as F2) and a delete icon.
  - Question rows: number, type icon, truncated text, a marks input with the suffix "mk" (default 1; set to 10), and delete.
- **"SCHEDULED FOR BATCHES"** with a "Schedule" button.
  - Subtitle: "Grade submissions in the Evaluation tool → Assessments tab."
  - Empty state: "Not scheduled yet. Save first, then schedule for one or more batches."

### F9. Schedule assessment for a batch
- **Modal title:** "Schedule — {assessment name}".
- "Batch" dropdown ("Choose a batch…").
- "Window opens" (placeholder "Choose when it opens") and "Window closes" ("Choose when it closes") date-time pickers. Demo: 4 Nov 2026 22:20 → 6 Nov 2026 22:20.
- Rule text: "Candidates may begin any time in this window. Once they agree to the instructions, the **30-minute** timer starts and auto-submits at 0:00 (or when the window closes, whichever is first)."
- "Evaluators · see plagiarism metrics, may grade": a "Search people…" box and a list of users with checkboxes. The empty state is "No matching people".
  - The subtitle implies evaluators get plagiarism metrics.
- "Grading per section": per-section row (e.g. "Programming"), with a dropdown (shown value "Pure Objective"; same engine family as F4) and a "Negative" checkbox for negative marking.
- Buttons: "Cancel", "Schedule".
- **Rules:** a flexible start window; a fixed per-candidate duration that starts on accepting the instructions; auto-submit at 0:00 or at window close; the timer cannot be paused.

### F10. Student exam workspace
- **Role:** student.
- **URL:** `/app/exam/{id}`
- Minimal top bar: small logo, exam name ("Adhithya-Py-Lists"), countdown "29:59" with a clock icon, and a "Submit" button (primary).
  - The usual org/avatar header is absent, which suggests a locked-down mode.
- Left column: section name "PROGRAMM…" (truncated), question bubbles 1–2, "Question 1" "10 marks", question text.
- Centre: language dropdown ("python"), "Maximize", code editor, "Compile & run", "Run tests", "Run", "Prev", "Next".
- No AI tutor panel, because the guide toggle was off.
- The instruction-agreement screen, fullscreen prompts and violation warnings were not captured in this part. Check part 2.

---

## 3. Notes for Tech Drona developers
- One shared **question bank** (6 types, tags, subjects, AI drafting with review, bulk import) feeds assignments, assessments, polls and surveys through a common **"Import from bank"** picker.
- **Assignment vs assessment** are separate apps:
  - Assignments: untimed, a long open window, an AI tutor with an interaction quota, multi-date scheduling.
  - Assessments: a fixed-duration timer, proctoring rules, shuffle toggles, negative marking.
- The **grading engine is chosen per section at allocation time**: Pure AI / AI + Human / Pure Objective / Adaptive / Pure Manual, with optional human evaluators.
- **Evaluation flow:** AI grading → human review/override → "Finalize & save" → "Publish results". Students get per-question scores and feedback, plus "Request modification".
- Late submission can be granted per learner by evaluators (stated in the help text, but the UI was not shown).
