# Reference LMS demo — Part 2 (video ≈ 19:42 – 44:23)

Source: 59 cropped frames (c_00035479 … c_00079892), time = frame / 30. The transcript was empty, so everything below comes from what is on screen.
The reference product's name and logo are left out on purpose. "[platform]" stands in for the product name wherever on-screen text contains it.
Org/tenant shown: "Skillyheads". Admin user: "Krishna" (avatar "V"). Student user: "Srikrishna" (avatar "S").
"(unclear)" means the text could not be read in the frame.

---

## 1. Timeline

| Video time | Screen / URL path | What the presenter does |
|---|---|---|
| 19:43 – 20:08 | `/app/exam/<examId>`: student exam-taking screen, exam "Adhithya-Py-Lists" | As a student, takes a coding exam. The editor is empty at first, then holds a Python solution. Countdown timer runs 29:50 → 29:25. He switches briefly to another tab (ChatGPT) and to VS Code, then comes back. |
| 20:08 | same | Back in the exam, a red **integrity warning banner** shows: tab/window switching was detected. |
| 20:24 – 20:28 | same | Clicks **Submit**. A confirmation modal appears (blurred). The exam is submitted (Submit button shows a spinner). |
| 20:34 | same URL, post-submit page | Result page shows "← My exams" and a note that the attempt was flagged for review. |
| 21:00 | `/console`: admin console overview | Goes back to the admin console home and hovers over the app tiles. |
| 21:13 – 21:17 | `/app/evaluation/assessments/<examId>`: Evaluation for that exam | Opens the Review modal for the student's submission, closes it, and shows the submission list with integrity badges, "Run AI grading" and "Publish results". |
| 22:00 – 23:00 | `/console` | Back on the console overview. Hovers over Question Banks. |
| 23:07 – 25:14 | `/app/question-banks`: "Generate with AI" modal | Generates 5 MCQs on "Python-Lists-MCQ" with AI, reviews the drafts, clicks "Save 5 to bank". Toast: "AI questions saved to your bank." |
| 25:50 – 26:12 | `/app/question-banks/<bankId>`: bank "Adhithya-Lists-MCQ" | Opens the "New Objective (MCQ) question" modal, cancels it, opens the Edit modal on one question, and shows the bank's question list. |
| 27:00 – 29:06 | `/app/engage/new?type=quiz`: Engage, new live quiz | Configures quiz settings (how it runs, who can join, identity, results, questions mode, winner rule, participant limit) and adds questions from the question bank. |
| 30:00 – 34:00 | `/app/engage/<id>/present`: presenter / big-screen mode | Shows the join screen (QR + link + joined count). Runs Q1 live, reveals the answer distribution with the fastest-correct winner, then shows the per-question summary (`/app/engage/<id>`). |
| 34:54 – 35:00 | `/app/engage`: Engage activity list | Deletes the duplicate "Adhithya-Lists-1 (copy)" (browser confirm). The list shows quizzes, polls and word clouds. |
| 36:00 – 37:00 | `/app/engage/new?type=wordcloud` → `/app/engage/<id>` | Creates a Word Cloud ("Name the best model you are aware of?") and opens its control room. Starts it, 2 responses come in, the word cloud is revealed. |
| 39:00 | `/app/paths`: student-side "My Paths" (admin account) | Empty state: "No paths yet". |
| 39:05 – 41:17 | `/app/paths-manager`: Paths Manager | Opens "Generate a path with AI", fills it in (Core Python, Mixed, beginner, 40 h, 8 steps, guidelines) and generates. Toast: "AI path created — review & attach content." |
| 41:25 – 42:21 | `/app/paths-manager/<pathId>`: path editor | Opens the Allocate modal (flow, progression, start date, study pace) and shows the path's step list (Assignment and Assessment steps, add-step buttons, Allocated to). |
| 43:00 | `/` (root): student home, logged in as Srikrishna | Student home page with "My Assignments" and app cards. Clicks Paths. |
| 44:00 – 44:23 | `/app/paths` → `/app/paths/<pathId>`: student path player | Student's list of assigned paths with progress. Opens "Core Python Fundamentals Path" and moves through steps: video step, docs/reading step (embedded page) and article step. |

---

## 2. Features

### 2.1 Student exam-taking screen (coding exam), proctoring and integrity flags
**Role:** Student. **Time:** 19:43 – 20:34. **URL:** `/app/exam/<examId>`

**Layout (exam "Adhithya-Py-Lists"):**
- Header: exam title at left. At right, a **countdown timer** (clock icon, e.g. "29:50", "29:40", "29:33", "29:25", "29:09", "29:05"; it counts down from about 30:00) and a green **Submit** button (paper-plane icon).
- Left panel:
  - Section label "PROGRAMMING".
  - Question navigator: numbered circles "1" (filled green = current) and "2".
  - Question card: code icon, "Question 1", marks label at right ("10 marks" during the attempt; "0 marks" shown at the moment of submit, probably the score once auto-evaluated (unclear)).
  - Full question statement text (the matrix diagonal-dominance problem).
- Right panel:
  - "Language" dropdown (value "python").
  - "Maximize" button (expand icon).
  - Dark code editor with line numbers.
  - Bottom bar: "Compile & run" dropdown (terminal icon + chevron), **Run tests** button (flask icon), **Run** button (green, play icon). Run and Run tests are greyed out while the editor is empty.
- Footer: "< Prev" and "Next >" buttons.

**Integrity / proctoring behaviour seen:**
- After the student left the tab (went to ChatGPT and VS Code), a full-width red banner appears under the header:
  **"Integrity warning — unusual activity is being recorded (5 events). Your submission will be flagged for review."** (warning-triangle icon).
- Submit opens a confirmation modal, blurred in the recording. The title looks like "Submit exam?" (unclear). It has a line of text and a red/orange note (unclear), plus two buttons: a secondary one ("Keep working"? (unclear)) and a green primary one ("Submit now"? (unclear)).
- The post-submit page shows "← My exams", a blurred header block with the exam name and details, and a yellow notice: **"This attempt was flagged for review due to integrity events during the exam."** (shield icon).

Rules shown: a timed exam with a countdown; tab-switch and window-inactive events are counted, the count is shown live to the student, and the attempt is flagged for review rather than auto-terminated. No fullscreen or webcam prompts are visible in these frames.

### 2.2 Evaluation (grading and publishing results)
**Role:** Admin/Instructor. **Time:** 21:13 – 21:17. **URL:** `/app/evaluation/assessments/<examId>`
- App header: "Evaluation", subtitle "Grade submissions & publish results". Back arrow at left.
- "← All evaluations" link.
- Title "Adhithya-Py-Lists". Sub-line: "1 submission · 20 marks".
- Buttons at top right: **Run AI grading** (sparkle icon) and **Publish results** (green, paper-plane icon).
- Section score card: "Programming", "0 / 20 avg".
- Submission row:
  - Shield icon and student name "Srikrishna".
  - Status "0 / 20 finalized · 2 AI pending".
  - Integrity badges: orange **"Tab switches: 2"** and red **"Window inactive: 3 (≥3)"**. "(≥3)" looks like the threshold that triggered the flag.
  - **Review** button.
- Review modal (21:13, blurred): title "Review — Srikrishna" (unclear). It shows a question header with a tag/badge (unclear), the question text, the student's submitted code in a read-only block, a score/marks row (unclear), and footer buttons: left link (unclear), "Close" (unclear) and a green primary button ("Finalise score"? (unclear)).

### 2.3 Admin console overview (app launcher)
**Role:** Admin. **Time:** 21:00, 22:00 – 23:00. **URL:** `/console`
- Top bar: product name with an "Admin" badge, org switcher "Skillyheads", avatar menu "V".
- Left nav (section "SKILLYHEADS"): **Overview**, **Question Banks**, **Batches**, **Users**, **Practice content**, **Settings**.
- "Welcome, Krishna" with sub-line "Skillyheads".
- Stat cards: "5 Users", "2 Batches".
- "YOUR ENABLED APPS" tile grid (title and subtitle; subtitles truncated as shown):
  - **Co-practice**: "Practice coding with a mentor be…"
  - **Options**: "Run quick multiple-choice quizzes" (links to `/app/options`)
  - **Surveys**: "Feedback forms with AI analysis"
  - **Assignment Manager**: "Create assignments, allocate to b…"
  - **Evaluation**: "Grade submissions & publish res…"
  - **Assess Studio**: "Build proctored assessments"
  - **Reports**: "Monitor activity & extract reports"
  - **Question Banks**: "Store and manage questions" (links to `/app/question-banks`)
  - **Engage**: "Live polls, word clouds & quizzes"
  - **Assessment Manager**: "Set up timed, proctored exams"
  - **Exam**: "Sit your scheduled exams"
  - **Paths Manager**: "Design guided learning paths"
  - **Articles**: "Verified lessons…" (truncated)
  - **Paths**: subtitle hidden
  - **Reports** (second tile): "Completion, quality & trends"

### 2.4 Question Banks, including AI generation
**Role:** Admin/Instructor. **Time:** 23:07 – 26:12. **URL:** `/app/question-banks`, `/app/question-banks/<bankId>`

**Banks list page:**
- Header "Question Banks". Subtitle: "Author reusable questions for co-practice, assessments, polls and more."
- Buttons: **Bulk import**, **Generate with AI** (sparkle), **+ New bank** (green).
- Stat cards: "20 Banks", "123 Questions", "8 Subjects".
- List shows a "Loading banks…" state.

**"Generate with AI" modal:**
- Banner: "Premium — [platform] drafts questions you can review before saving." (sparkle icon).
- Source mode pills: **On a topic** (selected), **For a company**, **On a subject**, **Specific test**.
- **Topic \*** (required). Placeholder "Binary search trees"; entered value "Python-Lists-MCQ".
- **General instructions** textarea. Placeholder "Difficulty, sub-topics, style…"; entered value "Python Lists MCQ".
- **Question type** (single-select chips): **Code**, **MCQ** (selected), **Essay**, **Poll**, **Survey**, **Words**.
- **How many?** number stepper (value 5).
- **Save to** dropdown (value "+ New bank").
- **New bank name** text field, placeholder "Auto-named if left blank".
- Buttons: **Cancel**, **Generate** (sparkle). Generate is disabled until Topic is filled.
- Review step: header "5 drafted · 5 selected" and a **Clear** link. Each draft card has an MCQ icon, the question text, its options listed inline separated by "·", tag chips (e.g. "python", "list-comprehension", "basics", "easy" / "filtering" / "conditionals", "intermediate") and a checkbox (all ticked).
  Buttons: **Back**, **Save 5 to bank** (the count follows the selection).
- Success toast: "AI questions saved to your bank."
- AI-assigned tags include a difficulty tag (easy / intermediate / advanced).

**Bank detail page (`Adhithya-Lists-MCQ`):**
- "← All banks". Title, then sub-line "programming · 5 questions" (subject · count).
- Buttons: **From bank** (download icon), **Bulk import**, **AI** (sparkle), **+ Add question** (green).
- Type filter pills: "All 5", "MCQ 5".
- Search box "Search questions & tags" and an **All tags** dropdown filter.
- Question rows: MCQ icon, "MCQ" badge, "1 correct", question text, tag chips, **edit (pencil)** and **delete (trash)** icons.

**"New Objective (MCQ) question" modal:**
- Type header card: "Objective (MCQ)", "Multiple choice with one or many correct answers".
- **Question description** textarea, placeholder "Write the question…".
- **Question image** (optional) area: "Add question image".
- **Options — tick the correct one(s)**, with a **+ Add option** link. Each option row has a tick toggle (marks it correct), a text field ("Option 1", "Option 2"), an add-image icon per option and a delete icon.
- **Tags** ("used later for search & filtering") field: "Add a tag and press Enter".
- Buttons: **Cancel**, **Add question**.
- The Edit modal (26:06, blurred) has the same layout. Title "Edit question" (unclear); footer "Cancel" / "Save" (unclear).

### 2.5 Engage: live quizzes, polls and word clouds
**Role:** Admin/Instructor (host); participants join by link or QR. **Time:** 27:00 – 37:00.

**Activity list (`/app/engage`):**
- Title "Engage". Subtitle "Run live polls, word clouds and quizzes."
- **+ New** button with a dropdown chevron. Types seen via URL: `type=quiz` and `type=wordcloud`. Poll is a listed type.
- "Search activities…" with a count (8). Grid/list view toggle.
- Activity cards show:
  - Type icon, title, "Quiz · 5 questions" / "Word Cloud · 1 question" / "Poll · 4 questions".
  - A "Live" badge.
  - Settings summary, e.g. "Public · Named · Fastest first" or "Public · Anonymous".
  - Buttons: **Open control room** (green), **Edit**, **Duplicate** (copy icon), **Delete** (trash).
- Delete asks for browser confirmation: 'Delete "Adhithya-Lists-1 (copy)"? This cannot be undone.' (Cancel / OK).
- Duplicating creates "<name> (copy)".
- Example activities: Adhithya-Lists-1 (Quiz), SRIT-IT (Word Cloud), SRIT-Intro (Poll · 4 questions), SAP-SMARTFORMS-QUIZ (Quiz · 3 questions), GK (Word Cloud, Anonymous), English-Phonetics (Quiz · 3 questions).

**Create form (New Quiz / New Word Cloud). The same settings blocks appear for both:**
- **Title** and **Description (optional)** ("A short line participants will see"). "← Engage" back link. Page title "New Word Cloud" (the quiz page title was not visible).
- **How it runs:** **Instant / live** ("You start & control it live") | **Scheduled** ("Opens & closes on a timer").
- **Who can join:** **Members only** ("Signed-in users of your org") | **Anyone (public)** ("Join by name via link/QR").
- **Identity:** **Named** ("Names appear in summaries") | **Anonymous** ("Responses aren't traced").
- **Results:** **Live** ("Shown as votes arrive") | **On publish** ("Hidden until you publish").
- **Questions:** **All at once** ("Show every question") | **One by one** ("You reveal each live").
- **Winner rule** (quiz only): **Fastest First** ("First correct wins each question") | **All Correct** ("Most correct answers wins").
- **Participant limit (optional)**: number field, placeholder "Unlimited".
- **QUESTIONS** section with an **Add from question bank** button. Each question block has:
  - Drag handle, "Question 1" field, image icon, delete icon.
  - Option rows: radio circle to tick the correct one, "Option" field, image icon per option.
  - "+ Add option" link and the hint "Tick the correct answer".
- **+ Add question** button. Footer: **Cancel**, **Save quiz**.
- In the demo the quiz was set to Anyone (public), Named, On publish, One by one, Fastest First.

**"Add from question bank" modal:**
- "Search banks…" field and a sort dropdown ("Newest first").
- Category filter chips with counts: All categories 21, ABAP-OOPS 1, Arrays 1, Basics of programming 1, College Student Feedback 1, HLDs 1, Java 2, Number Series 1, programming 12, Uncategorised 1.
- Banks are grouped by type, e.g. "OBJECTIVE (MCQ) BANKS 7". Each bank card shows name, subject, "5 Qs", "5 MCQ", hashtags, and "Created <date> · Last added <date>".
- Opening a bank shows "← All banks", the bank name, "programming · 5 questions", and a checkbox list of questions each marked "4 options".
- Buttons: **Cancel**, **Add questions**. Picked questions are appended to the quiz with their options and the correct answer pre-ticked.

**Presenter / big-screen mode (`/app/engage/<id>/present`):**
- Join screen: "JOIN THE POLL", the activity title, a large QR code, the join URL (`/live/<id>`), and a live counter "● 1 joined". A green start button sits below it (label hidden). Close (X) at top right.
- Question screen:
  - Header: title "Adhithya-Lists-1", "Q1 / 5", "● 3 joined", a mini QR with the link and an expand icon, close X.
  - Body: numbered question, "0 answered" / "3 answered" counter, option list.
- After reveal:
  - The correct option is shown in green with a ✓. Each option has a horizontal bar with "67% · 2", "0% · 0", "33% · 1" and so on.
  - Winner box: crown icon, **"Fastest: Krishna"**, "Also correct: Varun".
- Footer controls:
  - "<" prev, "Q1 / 5", ">" next, **Reveal all**.
  - **Reveal answers** / **Hide answers** toggle.
  - **Hide correct** / show correct toggle.
  - **Finalise** (✓) at the right.

**Activity summary (`/app/engage/<id>`):** lists every question with its options, the correct option in green with a ✓, and an "N answered" counter per question.

**Control room (word cloud "Adhithya-1", `/app/engage/<id>`):**
- "← Polls" link and status badge **"Waiting to start"**. **Present** button at top right.
- **RUNS:** pills such as "Run 1 · current". Multiple runs are supported.
- **RUN** card: **Start poll** (play icon), then **Finalise** (✓) once started, and a **Rerun** (sparkle) button.
- **SHARED SCREEN:** **Reveal word cloud** / **Hide word cloud** toggle, **Preview privately** (eye icon) and a question pager "< Q1/1 >" with a link icon. Status text: "Question shown — answers hidden" or "Answers are shown to the room".
- Question card: "1. Name the best model you are aware of?" with "0 responses" / "2 responses". Before reveal it reads "Responses are coming in — reveal to show the word cloud." After reveal the word cloud renders (e.g. "CV").
- **SHARE TO JOIN:** QR code, link, **Copy**, **Email**, **Present on big screen**.
- **LIVE** stats: "● 3 Joined", "2 Voted", "0 Total votes".

### 2.6 Paths Manager: AI-generated learning paths, path editor and allocation
**Role:** Admin/Instructor. **Time:** 39:05 – 42:21. **URL:** `/app/paths-manager`, `/app/paths-manager/<pathId>`

**Paths list ("Learning Paths"):**
- Subtitle "Design guided paths of … articles, assignments and assessments" (partly hidden).
- Buttons: Import (unclear), **Generate with AI**, **+ New path**. "Search paths…" field and a grid/list toggle.
- Path cards: title, description, "N steps", "N credits", hours (e.g. "20h", "10h", "28h"). Buttons: **Open** and a delete icon.
- Examples: ABAP Object-Oriented Programming, Beginner French Communication, AI Evaluation: Past, Present…, Beginner English Prefixes Mas…, Mastering English Tenses and…, Spring Framework – Beginners, Senior Java Developer Intervi…, Python for Experienced Java….

**"Generate a path with AI" modal:**
- Banner: "[platform] drafts the path structure — you attach the actual content and allocate afterwards."
- **Topic / goal \*** (value "Core Python").
- **Path style:**
  - **Mixed**: "Videos, readings, articles, assignments and assessments"
  - **Textbook**: "Every step is a written chapter, in order — like a modern textbook"
- **Level** dropdown (value "beginner"; other values not shown). **Target total hours** (40). **Approx steps** (8).
- **Guidelines (optional)** textarea ("Make sure all the content is valid").
- Footnote: "Each article's depth follows its hours and your guidelines. Videos are only kept when a real, on-topic one is found — otherwise [platform] writes and fact-checks an article instead."
- Buttons: **Cancel**, **Generate**. A progress state follows: "[platform] is designing your path… Reading your guidelines…" with a progress bar.
- Toast: "AI path created — review & attach content." Then the editor opens.

**Path editor (`Core Python Fundamentals Path`):**
- Steps are numbered cards with up/down reorder arrows, a type icon and a delete (trash) icon. Examples:
  - "4. ASSIGNMENT": title "Hands-On Project: Personal Task Manager CLI". Selector "Assignment (given to the batch when the path is allocated)" set to "Hands-On Project: Personal Task Manager CLI Assignment · 32 marks". Fields: "5 hrs" and "25 credits".
  - "5. ASSESSMENT": title "Core Python Comprehensive Knowledge Assessment". Selector "Exam (given to the batch when the path is allocated)" set to "Core Python Comprehensive Knowledge Assessment · 180min". Fields: "3 hrs" and "20 credits".
- Add-step buttons: **+ Reading**, **+ Video**, **+ Article**, **+ Assignment**, **+ Assessment**, **+ Super-step** (layers icon, a grouping step).
- **ALLOCATED TO** section, hint "Save first, then allocate to a batch or learner.", **Allocate** button, empty state "Not allocated yet".

**"Allocate — <path name>" modal:**
- **Allocate to:** **Batch** | **Individual** tabs.
- **Batch** dropdown ("Choose a batch…"; a batch code like "2025_0…" was selected (unclear)).
- **Flow:**
  - **Lenient**: "Own pace · credits always count"
  - **Strict**: "On timeline · delays penalise credits"
- **Progression:** **Sequential** toggle. When off it reads "Any step, any order". When on, the sub-text is blurred, roughly "Must complete … before the next" (unclear).
- **Start date (optional)**: date picker, placeholder "Defaults to now". Hint: "The study plan below counts from here. Defaults to now."
- **Study pace** ("how much time the learner/batch studies each day"):
  - Chips: **Every day** (selected), **Weekdays**, **Weekends**, **Weekdays + weekends**, **Custom**.
  - **Hours per day** (2).
  - Per-day grid Mon–Sun, each set to 2. Sat and Sun are highlighted.
- Computed summary: "14h/week · path is 20h · finishes in ≈ 10 days (14 Nov 2026)".
- Mode note: "Lenient: this is a suggested plan — time is tracked but never penalised."
- Buttons: **Cancel**, **Allocate**.

### 2.7 Student home and learning-path player
**Role:** Student. **Time:** 39:00 (empty state), 43:00 – 44:23. **URL:** `/`, `/app/paths`, `/app/paths/<pathId>`
- **Student home:**
  - Greeting "Hi Srikrishna, what's next?" and "Pick an app to get started."
  - Banner card **My Assignments**: "Assignments allocated to your batches — take them and see results."
  - "APPS" cards: **Co-practice** ("Practice coding with a mentor beside you"), **Exam** ("Sit your scheduled exams"), **Paths** ("Follow your learning path"). Each card has an "Open →" link.
- **My Paths (empty state):** "Guided learning paths assigned to you." / "No paths yet" / "Learning paths assigned to you or your batch will appear here."
- **My Paths list:**
  - Cards show a pace badge ("Own pace"), title, "N steps · N credits", "x/N done", % and a progress bar.
  - Action is **Start →** or **Continue →** when in progress (e.g. Spring Framework – Beginners, "5/15 done", 33%).
- **Path player:**
  - "← My paths" link and a **Refresh** button.
  - Header: path title, description, badges "Own pace" and "Any order", credits earned ("0 credits") and a % completion ring ("0%").
  - Left rail of numbered steps. Each step has a type icon (video / reading-doc / article-book / assignment / assessment), a truncated title, credits (e.g. 5, 10, 25) and hours (1h, 1.5h, 2h, 5h).
  - Steps in this path: 1 video, 2 reading, 3 article, 4 reading, 5 video, 6 article, 7 reading, 8 article, 9 assignment ("Hands-On Project: Personal Task Ma…", 25 credits, 5h), 10 assessment ("Core Python Comprehensive Knowle…").
  - A completed or visited step shows a filled green number.
- **Step content pane:**
  - Step title, description and a status badge ("Available" → "In progress").
  - **Video step:** embedded YouTube player, "5 credits on completion" and a **Mark as watched** button.
  - **Reading step:** the external documentation page is embedded inline (iframe of the official Python tutorial).
  - **Article step:** "Loading article…", then a rendered long-form article with headings, bold terms and code blocks that have a **Copy** button. "10 credits on completion" is shown.

---

## 3. Not observed in this segment
- No webcam, fullscreen enforcement, question randomisation or attempt-count settings were visible. Proctoring evidence is limited to tab-switch and window-inactive counters, a live warning banner and flag-for-review.
- Assignment Manager, Assess Studio, Assessment Manager, Surveys, Options, Reports, Articles and Co-practice appear only as console tiles; their screens are not shown in this range.
- The Poll and Word Cloud create forms share the same settings blocks as the quiz. Poll-specific question types were not shown.
