# Reference LMS demo — Part 3 (video ≈ 44:23 – 47:30)

Source: frames c_00079910 … c_00085482 (59 frames, cropped to the shared screen). Transcript for this range was empty, so everything below comes from what the screen shows. The reference product's name and branding are left out on purpose. Product areas are described by what they do: "Paths app" (learner path player) and "Articles app" (AI-generated, verified lesson library).

Notes:
- Video time = frame number / 30. The on-screen macOS clock reads 10:49 PM to 10:52 PM.
- Frames 80079, 81220, 81225 and 81248 are near-duplicate scroll positions of the frames next to them. They add nothing new.
- A Google Meet "sharing your screen" bar and a floating "Talking:" widget cover parts of every frame. Text behind them is marked (unclear).

---

## 1. Timeline

| Video time | Screen / URL path | What the presenter does |
|---|---|---|
| 44:23 – 44:32 | `/app/paths/<pathId>` (Paths app, learner view), step 3 "Understanding Variables and Dyna…" | Scrolls through an inline article step. The article has code blocks with Output panels, a diagram, a "Key idea" callout, a "Watch out" callout, a comparison table, a flowchart, a "Note" callout, a "Tip" callout and "Common Mistakes…" sections. |
| 44:33 – 44:36 | same, step 4 "Official Python Tutorial: More Contro…" | Clicks step 4. The content area loads an embedded external documentation page (the official Python tutorial, chapter "4. More Control Flow Tools"). The top of the page shows the path header. |
| 44:43 | same, step 4, bottom | Shows the step footer: "Open in a new tab if it doesn't load above", "10 credits on completion" and the **Mark as read** button. |
| 44:45 | same, step 5 "Python Functions and Scope Explain…" | Clicks a video step. A YouTube embed loads ("Python Tutorial for Beginners 8: Func…"). Footer: "10 credits on completion" and **Mark as watched**. |
| 44:59 – 45:00 | same, step 6 "Writing Clean Functions with Argum…" | Clicks step 6. The step card shows its title, description and status "In progress", the placeholder "Loading article…" and "5 credits on completion". |
| 45:07 – 45:18 | same, step 6 | Scrolls the inline article: "Positional and Keyword Arguments", a Tip, "Setting Sensible Default Parameters", "The Danger of Mutable Default Arguments" (Watch out), a "Function Interface Comparison" table, a return-flow flowchart and "Exercises with Solutions". Scrolls back to the top. |
| 45:23 – 45:24 | same, step 7 "Official Python Tutorial: Data Structu…" | Clicks step 7. An embedded external doc ("5. Data Structures") loads. Footer: "10 credits on completion" and **Mark as read**. |
| 45:25 | same, step 9 "Hands-On Project: Personal Task Ma…" | Clicks the assignment step. The card shows the evaluator-gated message and a **Start assignment** button. |
| 45:41 – 45:44 | same, step 1 | Returns to the top of the path. Step 1 (video) is selected with status "Available". |
| 45:47 | `/app/paths` | Clicks "← My paths". The path list page is loading (blank). |
| 46:00 | `/login` | The sign-in page appears. The presenter is switching accounts: the learner avatar showed "S", and after login it shows "V". |
| 46:51 – 46:54 | `/app/articles/<articleId>` (Articles app) | Scrolls the same "Understanding Variables…" content as a stand-alone article. A right-hand "On this page" table of contents is visible. |
| 47:00 | same, top of article | Shows the article header with its status chips ("Verified", "Not published"), **Regenerate**, a delete icon and **Publish & share**. |
| 47:01 | same, "Publish & share" modal | Opens the publish dialog with the visibility options and the share link. Publishes. |
| 47:10 | same | A toast reads "Article published." The status chip changes from "Not published" to "Public". |
| 47:20 | same, modal reopened | The modal now shows **Unpublish**, **Cancel** and **Save** instead of Publish. |
| 47:29 | same | The modal is closed. The article is public. |

---

## 2. Features

### 2.1 Learning-path player (student / learner view)
**Role:** Learner. The account avatar is "S" and the org switcher reads "Skillyheads".
**URL:** `/app/paths/<pathId>`. The back link goes to `/app/paths` ("My paths").

#### App chrome
- App header: an app icon, the app name, and the subtitle "Follow your learning path". There is a back arrow (←) on the far left.
- Top right: an **organisation switcher** (building icon + "Skillyheads" + up/down chevron) and a **user avatar menu** (initial + chevron).

#### Path header card
- "← My paths" link (top left) and a **Refresh** button with a circular-arrow icon (top right).
- Title: "Core Python Fundamentals Path".
- Description: "A complete 20-hour beginner learning path covering foundational Python syntax, control structures, data collections, file operations, and practical project implementation."
- Two chips that show the path's pacing and ordering settings:
  - **"Own pace"**: self-paced, as opposed to scheduled.
  - **"Any order"**: steps are not locked to a sequence. The learner opened steps 4, 5, 6, 7 and 9 directly and out of order.
- On the right side:
  - a **credits earned** counter (credits icon + "0" + the label "credits");
  - a circular **progress %** ring showing "0%". It stayed at 0% even after several steps were opened, because opening a step does not complete it.

#### Step list (left rail, scrollable)
Each row shows:
- a step number in a circle. The circle is outlined when not started and turns **filled green once the step has been opened or started**;
- a **type icon**;
- the title, truncated with "…";
- a meta line: credits icon + credit value, and clock icon + estimated duration.

The selected step has a green outline.

Steps in this path:

| # | Type icon | Title (as shown) | Credits | Duration |
|---|---|---|---|---|
| 1 | Video (camera) | Installing Python and Running Your Fi… (full: "Installing Python and Running Your First Script") | 5 | 1h |
| 2 | Document / external page | Official Python Tutorial: Basic Data T… | 10 | 1.5h |
| 3 | Article (open book) | Understanding Variables and Dyna… | 10 | 1.5h |
| 4 | Document / external page | Official Python Tutorial: More Contro… (full: "…More Control Flow Tools") | 10 | 1.5h |
| 5 | Video | Python Functions and Scope Explain… | 10 | 1.5h |
| 6 | Article | Writing Clean Functions with Argum… (full: "Writing Clean Functions with Arguments and Return Values") | 5 | 1h |
| 7 | Document / external page | Official Python Tutorial: Data Structu… | 10 | 2h |
| 8 | Article | Working with Files: Reading, Writing, … | 10 | 2h |
| 9 | Assignment (pencil/edit-square) | Hands-On Project: Personal Task Ma… (full: "Hands-On Project: Personal Task Manager CLI") | 25 | 5h |
| 10 | (unclear icon; possibly a quiz/assessment) | Core Python Comprehensive Knowle… | 20 | 3h |

The durations add up to 20h, which matches "20-hour" in the description. The credits add up to 115.

**Step types seen:** video, external document, article, assignment, and an unclear tenth type that is probably a knowledge check (not opened in this range).

#### Step content panel (right)
- Step title and a one-line description, for example "Study conditional statements, loop structures, and function definitions from official docs."
- A **status label** at the top right of the card. Values seen:
  - **"Available"**: the step was not started (step 1);
  - **"In progress"**: the step was opened but not completed (steps 4, 6 and 9).
- The body depends on the step type:
  - **Video step:** an embedded YouTube player (title, channel, share and watch-later icons, "Watch on YouTube"). The footer shows "N credits on completion" and a green **Mark as watched** button.
  - **External document step:** the external page is embedded in an iframe. Below it is a link, "Open in a new tab if it doesn't load above", with an external-link icon. The footer shows "10 credits on completion" and a green **Mark as read** button.
  - **Article step:** "Loading article…" with an animated four-colour dot loader, then the platform's own article renders inline. It uses the same rich format described in 2.3. The footer shows "5 credits on completion" for step 6 (the button was not visible in these frames).
  - **Assignment step:** a grey card with the text **"Open and complete the assignment to progress. Credits release once your evaluator marks it complete."** and a green **Start assignment** button with an external-link icon (it opens the assignment elsewhere). Rule shown: **assignment credits are held until an evaluator marks the work complete.** Learners cannot self-complete it.
- Completion rule shown: credits are earned "on completion", and completion is a learner action ("Mark as read" / "Mark as watched") for content steps, or an evaluator's sign-off for assignments.

### 2.2 Sign-in page (all roles)
**URL:** `/login`. Appears at 46:00 when the presenter switches to another account.
- A logo illustration, four coloured dots, the heading "Welcome to …" (product name omitted here), and the subtitle "Sign in to reach your apps." This implies one sign-in for several apps (Paths, Articles, and others).
- Fields: email (envelope icon), **Password** (lock icon).
- Button: **Sign in**. It is disabled (pale) until a password is entered.
- Footer: "New organization? **Register your institution**", a self-service flow for an organisation or tenant to sign up.

### 2.3 Articles app: AI-generated, verified article viewer and publishing (author / instructor / admin)
**Role:** Author or admin. The avatar after re-login is "V" and the org is still "Skillyheads". The org switcher has no chevron in this account.
**URL:** `/app/articles/<articleId>`. App subtitle: "Verified lessons, ready to share".

#### Article header / toolbar
- "← Articles" back link to the article library.
- Status chips:
  - **"Verified"** (check icon);
  - **"Not published"** (lock icon), which becomes **"Public"** (globe icon) after publishing.
- **Regenerate** button with a refresh icon. It re-creates the article with AI.
- **Delete** button (red trash icon).
- **Publish & share** button (green, with a share icon).
- A notice banner: **"1 sample output(s) were replaced with the real program output."** The system runs the code samples and swaps any AI-guessed output for the real output.

#### Article body
- Title: "Understanding Variables and Dynamic Typing in Python".
- Subtitle: "Master Python's memory model, object references, and dynamic typing to write clean, reliable, and bug-free code."
- Meta chips: level **"Beginner"** (cap icon) and **"About 1.5 h of study"** (clock icon).
- Verification bar (green, check icon): **"Fact-checked by a second AI review (2 fixes applied) · 7 of 7 code samples run and match their output"**.
- **"On this page"** table of contents on the right with anchor links:
  - Variables Are References, Not Containers
  - Memory Allocation and Object Identity
  - How Dynamic Typing Works in Python
  - Type Inspection and Type Hints
  - Common Mistakes and How to Avoid Them
  - Summary of Key Points
  - Exercises
  - What's Next
- Content building blocks, seen here and in the path's article steps:
  - H2 and H3 headings. Numbered sub-headings are styled as coloured links, for example "1. Expecting Reassignment to Modify Other Bound Variables".
  - **Code block** with a language label ("python") and a **Copy** button, followed by a separate **"Output"** panel showing the program output.
  - **Callout boxes**, each with its own colour and icon:
    - **"Key idea"** (blue, key icon);
    - **"Watch out"** (amber, warning-triangle icon);
    - **"Note"** (blue, info icon);
    - **"Tip"** (green, lightbulb icon).
  - **Tables**, for example a "Feature / Statically Typed Languages / Dynamically Typed Languages" comparison, and "Argument Type / Definition Syntax Example / Best Used For".
  - **Diagrams**: box-and-arrow diagrams such as "Variable Names (References)" pointing to "Computer Memory (Objects)", vertical flowcharts, and a decision-diamond flowchart ("Is return reached?", with Yes/No branches).
  - Inline code chips, bold key terms, numbered lists and bullet lists.
  - An **"Exercises with Solutions"** section: "Test your understanding with these hands-on coding exercises." Exercise content was not scrolled into view.
  - Cross-references to earlier chapters in the text ("Remember Chapter 3 where we discussed dynamic…", "In Chapter 1… In Chapter 2…"). This suggests articles are generated as a chapter series.

#### Publish & share modal
- Title "Publish & share", with a close (×) button.
- **"Who can read it"**: radio cards, one choice only.
  - **Anyone with the link**. Selected in the demo. Sub-text (unclear): roughly "No sign-in needed — share the link anywhere".
  - **Chosen batches**. Sub-text (unclear): roughly "Signed-in members of the batches you pick".
  - **Chosen people**. Sub-text (unclear): roughly "Only the people you pick".
- **Link**: a read-only public URL of the form `https://<host>/read/<articleId>`, with **copy** and **open in new tab** icon buttons. Helper text below it (unclear), roughly: "Learners on a path that includes this article can always read it, whether or not it's published." The wording is not fully legible.
- Buttons for an unpublished article: **Cancel** and **Publish** (green).
- After publishing:
  - a toast at the bottom right: **"Article published."** (check icon, close ×);
  - the status chip changes to **"Public"**.
- Reopening the modal on a published article shows the same options plus a red **Unpublish** link (left), **Cancel** and **Save** (green). Visibility can be changed after publishing, and the article can be unpublished.

---

## 3. Not shown in this range
- No assessment, quiz, poll or exam creation screens.
- No proctoring settings (fullscreen, tab-switch limits, webcam), randomisation, time limits or attempt limits.
- No path-builder or admin editing UI, and no reports or analytics.
- Step 10 (likely a knowledge-check or assessment step) and step 8 were not opened.
- The assignment's own page (behind "Start assignment") was not opened.
