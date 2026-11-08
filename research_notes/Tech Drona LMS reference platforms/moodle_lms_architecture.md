# Moodle (plus Canvas and Open edX) as Reference LMS Architectures for Tech Drona

> **How these notes were sourced (read first).** docs.moodle.org returned HTTP 403 / Cloudflare "Moodle challenge" pages to every automated fetch on 2026-11-03, so I could not read the docs pages in full. To get primary facts I read **Moodle's own source on GitHub (`moodle/moodle`, branch `main`)**: settings files, English language strings and the DB schema. In that branch `version.php` reads `$release = '6.0dev (Build: 20261030)'`, and the codebase has moved under a `public/` directory. Each finding is tagged:
> - **[SRC]**: verified by reading Moodle source or strings in this session (GitHub link given).
> - **[WEB]**: verified from search-result text in this session.
> - **[DOC-UNVERIFIED]**: well-established Moodle behaviour, cited to its canonical docs.moodle.org page, but this session could not re-read that page. Check it before quoting verbatim.
>
> Source base: `https://github.com/moodle/moodle/blob/main/public/...` (abbreviated below as `GH:` followed by the path).

## 1. Course structure and authoring workflow

### Takeaway
Moodle content sits in a strict tree: site → course categories (nestable) → courses → sections (topics/weeks) → activities and resources, which are "course modules". The same tree is the permission "context" hierarchy. Each course runs one "course format" plugin that decides how its sections are presented.

### Cited Findings
- The context levels are implemented as classes `system`, `coursecat`, `course`, `module`, `block`, `user` — [SRC] [GH: public/lib/classes/context/](https://github.com/moodle/moodle/tree/main/public/lib/classes/context)
- Current core activity/resource modules (the `mod/` directory): assign, bigbluebuttonbn, book, choice, data (database), feedback, folder, forum, glossary, h5pactivity, imscp, label, lesson, lti, page, **qbank**, quiz, resource (file), scorm, **subsection**, url, wiki, workshop — [SRC] [GH: public/mod](https://github.com/moodle/moodle/tree/main/public/mod)
  - `mod_subsection` adds nested sections inside a section. `mod_qbank` is the module that implements the shared question banks introduced in 5.0 (see §3).
- Course categories organise courses and can nest. Category-level role assignments, for example a Manager or Course creator, apply to every course below that category — [DOC-UNVERIFIED] [docs: Course categories](https://docs.moodle.org/en/Course_categories)
- Authoring workflow: create the course in a category, pick a course format (Topics, Weekly, Single activity, Social), turn editing on, then use "Add an activity or resource" inside a section. Each module has common settings (availability, restrict access, activity completion, group mode, grade category) — [DOC-UNVERIFIED] [docs: Course formats](https://docs.moodle.org/en/Course_formats), [Restrict access](https://docs.moodle.org/en/Restrict_access)
- Reusing courses depends on Backup/Restore and Import (copying content from another course) and on "Course copy" — [DOC-UNVERIFIED] [docs: Course backup](https://docs.moodle.org/en/Course_backup)

### Inferences
- For Tech Drona the model maps as: **Category = program/track** (e.g. "Placement Prep 2027"), **Course = module/subject** (Aptitude, DSA, HR interview), **Section = week/topic**, **Activity = test/assignment/video/coding problem**. Store all of these as one polymorphic "course_module" table plus per-type tables, the way Moodle does with `course_modules` + `quiz`/`assign`. That keeps completion, logging and permissions generic.
- Moodle's coupling of the content tree to the permission tree is powerful but over-general for a placement-prep product. A thinner scope model (org → batch → course → item) is probably enough.

### Gaps
- I could not read the current 5.x docs text for course formats and the course-copy UI.

## 2. Enrolment, cohorts, groups and groupings (mapping to college batches)

### Takeaway
In Moodle, enrolment is a per-course **instance of an enrolment plugin**. One course can run several methods at once, such as manual + self + cohort sync. **Cohorts** are site- or category-wide groups of users (the natural fit for a college batch). **Groups/groupings** are per-course subdivisions used for separate visibility and grading.

### Cited Findings
- Core enrolment plugins in `enrol/`: category, cohort, database, fee, flatfile, guest, imsenterprise, ldap, lti, manual, meta, paypal, self — [SRC] [GH: public/enrol](https://github.com/moodle/moodle/tree/main/public/enrol)
- "Enrolment on payment" (`enrol_fee`) works through the payment subsystem with payment-gateway plugins. The older `enrol_paypal` still ships in `main` — [SRC] for the plugin presence; payment subsystem behaviour [DOC-UNVERIFIED] [docs: Enrolment on payment](https://docs.moodle.org/en/Enrolment_on_payment), [Payment gateways](https://docs.moodle.org/en/Payment_gateways)
- Manual enrolment: a teacher or admin adds users and can set an enrolment start/end. Self enrolment: the student joins, optionally with an enrolment key, and can also be given a group enrolment key that puts them in a group on joining. Guest access allows viewing without enrolling, optionally with a password — [DOC-UNVERIFIED] [docs: Manual enrolments](https://docs.moodle.org/en/Manual_enrolments), [Self enrolment](https://docs.moodle.org/en/Self_enrolment), [Guest access](https://docs.moodle.org/en/Guest_access)
- Cohort sync enrols every member of a cohort and keeps the enrolment in step as the cohort changes. It can also add the members to a chosen course group. Cohorts exist at system or category context and can be filled by CSV upload — [DOC-UNVERIFIED] [docs: Cohort sync](https://docs.moodle.org/en/Cohort_sync), [Cohorts](https://docs.moodle.org/en/Cohorts)
- Course meta link enrols users from a parent course into a child course — [DOC-UNVERIFIED] [docs: Course meta link](https://docs.moodle.org/en/Course_meta_link)
- Groups are per course. Group mode can be No groups, Separate groups or Visible groups, set at course level with an option to force it on all activities. A grouping is a named set of groups that an activity can be limited to — [DOC-UNVERIFIED] [docs: Groups](https://docs.moodle.org/en/Groups), [Groupings](https://docs.moodle.org/en/Groupings)
- MFA has a `cohort` factor, so cohorts are also reused as policy targets — [SRC] [GH: public/admin/tool/mfa/factor](https://github.com/moodle/moodle/tree/main/public/admin/tool/mfa/factor)

### Inferences
- **College batch → cohort** (cross-course, managed centrally, e.g. "VIT-CSE-2027-A"). **Section/lab group inside a course → group**. **"All batches from College X" → grouping or category-scoped cohort.** Make enrolment its own table with `method`, `status`, `time_start`, `time_end`, and a source reference such as `cohort_id` or `payment_id`, rather than a flag on the user. That reproduces Moodle's multi-method model cleanly.
- For paid courses in India, put a payment-gateway abstraction (Razorpay/Cashfree/UPI) behind an "enrol on payment" method, the same pattern as `enrol_fee` + payment gateway plugins. Moodle ships no Indian gateway in core. This is inferred: I found no Razorpay plugin in core, and checked only the core `enrol/` list.

### Gaps
- I did not confirm the exact list of payment gateways shipped in 5.x core because the `payment/gateway` path was not listed.

## 3. Roles, capabilities and permission model

### Takeaway
Moodle RBAC = **roles** (bundles of **capabilities**, each set to Inherit/Allow/Prevent/Prohibit) **assigned to a user in a context**. Permissions resolve down the context tree (system → category → course → module/block), and **role overrides** can change a role's capabilities in a specific context. Prohibit cannot be overridden lower down.

### Cited Findings
- The permission values are "inherit, allow, prevent or prohibit" — [SRC] `privacy:metadata:role_capabilities:permission` in [GH: public/lang/en/role.php](https://github.com/moodle/moodle/blob/main/public/lang/en/role.php)
- "Permissions overrides enable selected capabilities to be allowed or prevented in a specific context." (`overridepermissions_help`) — [SRC] same file
- Standard roles: Manager, Course creator, Teacher (editingteacher), Non-editing teacher, Student, Guest, Authenticated user, Authenticated user on frontpage. A non-editing teacher can grade and view but cannot change course content — [DOC-UNVERIFIED] [docs: Standard roles](https://docs.moodle.org/en/Standard_roles), [Capabilities](https://docs.moodle.org/en/Capabilities), [Override permissions](https://docs.moodle.org/en/Override_permissions)
- Since the 5.0 question-bank change, upgraded sites must allow `moodle/question:useall` and `moodle/question:usemine` for non-editing teachers — [WEB] [docs: Question banks in upgraded sites](https://docs.moodle.org/en/Question_banks_in_upgraded_sites)

### Inferences
- Tech Drona roles map as: Platform admin = Manager@system; College TPO/coordinator = Manager@category (their college); **Trainer = editingteacher@course**; **Evaluator/TA = non-editing teacher**; Student; Recruiter (read-only on reports) = custom role.
- Lesson: Moodle's four-state capability model with per-context overrides is notoriously hard for admins to debug. Moodle needs dedicated tools ("Check permissions", "This role's permissions in context") — [DOC-UNVERIFIED] [docs: Check permissions](https://docs.moodle.org/en/Check_permissions). A new system should use allow-only scoped permissions and avoid Prevent/Prohibit, or keep them to a tiny set.

### Gaps
- I did not re-read the per-role default capability matrix (`lib/db/access.php`).

## 4. Quiz engine (question bank, types, randomisation, timing, attempts, grading, review, SEB, autosave/recovery)

### Takeaway
The Moodle quiz is a mature exam engine. It has a reusable question bank (shared via `mod_qbank` since 5.0), about 16 core question types, random selection from categories, timing with configurable overdue handling, multiple-attempt grading methods, a 4-phase review matrix, IP/password/browser restrictions with Safe Exam Browser, and **server-side periodic autosave** (default 60 s) so a resumed attempt survives a browser crash.

### Cited Findings
**Question bank**
- In Moodle 5.0+, "course question banks enable teachers to reuse and share questions across courses". Before 5.0, questions lived in categories in the course, course category or system context. Upgrades moved course-context questions to a course shared bank, category-context questions to a shared bank in a new course named after the category, and system-context questions to a shared bank on the site home. The categories and subcategories are kept. Each quiz also has a **private quiz bank** whose questions "can only be used in the quiz" — [WEB] [docs: Question banks in upgraded sites](https://docs.moodle.org/en/Question_banks_in_upgraded_sites), [Question banks (5.2)](https://docs.moodle.org/502/en/Question_banks)
- Known upgrade bugs: MDL-84466 (fixed 5.0.2), MDL-86226 — [WEB] same page

**Question types (core `question/type/`)**
- calculated, calculatedmulti, calculatedsimple, ddimageortext, ddmarker, ddwtos, description, essay, gapselect, match, multianswer (Cloze/embedded answers), multichoice, numerical, ordering, randomsamatch, shortanswer, truefalse — [SRC] [GH: public/question/type](https://github.com/moodle/moodle/tree/main/public/question/type). `ordering` is now in core.
- There is **no core coding/programming question type**. CodeRunner is the well-known third-party plugin — [DOC-UNVERIFIED] [plugin: qtype_coderunner](https://moodle.org/plugins/qtype_coderunner)

**Random questions, shuffling, navigation**
- Random questions draw from a bank category, optionally including subcategories and filtered by tags. Each student gets a different draw — [DOC-UNVERIFIED] [docs: Random questions](https://docs.moodle.org/en/Random_questions)
- "Shuffle within questions": "the parts making up each question will be randomly shuffled each time a student attempts the quiz" (applies to MCQ/matching) — [SRC] `shufflewithin_help`, [GH: public/mod/quiz/lang/en/quiz.php](https://github.com/moodle/moodle/blob/main/public/mod/quiz/lang/en/quiz.php)
- Sequential navigation: "a student must progress through the quiz in order and may not return to previous pages nor skip ahead" (`navmethod_help`) — [SRC] same file

**Timing**
- Time limit: "the time limit is stated on the initial quiz page and a countdown timer is displayed in the quiz navigation block" — [SRC] `timelimit_help`, same file
- "When time expires" (`overduehandling`) options include "Open attempts are submitted automatically" (`overduehandlingautosubmit`) and "There is a grace period when open attempts can be submitted, but no more questions answered" (`overduehandlinggraceperiod`). There is also an "attempts must be submitted before time expires, or they are not counted" option (abandon) — [SRC] same file (autosubmit/graceperiod strings read; abandon wording [DOC-UNVERIFIED])
- Site setting `quiz/graceperiodmin` ("Last submission grace period"): "we will accept responses for up to this long after time expires, so they are not penalised for the server being slow. However, the student could cheat and get this many seconds..." — [SRC] `graceperiodmin_desc`; setting registered in [GH: public/mod/quiz/settings.php](https://github.com/moodle/moodle/blob/main/public/mod/quiz/settings.php)
- `quiz/graceperiod` = the default submission grace period — [SRC] same files

**Attempts and grading**
- `configattemptsallowed`: "Restriction on the number of attempts students are allowed at the quiz." — [SRC] quiz.php lang
- Grading method across attempts: "Highest grade of all attempts", "Average (mean) grade", "First attempt", "Last attempt" — [SRC] `grademethod_help`
- Delay between attempts (`delay1st2nd`): "a student must wait for the specified time to elapse before being able to attempt the quiz a second time" — [SRC]
- Question behaviours: deferred feedback, immediate feedback, interactive with multiple tries, adaptive mode, with CBM variants — [DOC-UNVERIFIED] [docs: Question behaviours](https://docs.moodle.org/en/Question_behaviours)
- User and group overrides of dates, time limit and attempts exist, and the cache definition `quiz_overrides` is "User and group override information" — [SRC] quiz.php lang; [DOC-UNVERIFIED] [docs: Quiz overrides](https://docs.moodle.org/en/Quiz_settings)

**Review options**
- Four review phases: "**During the attempt** ... **Immediately after the attempt** settings apply for the first two minutes after 'Submit all and finish' is clicked. **Later, while the quiz is still open** ... **After the quiz is closed** ... If the quiz does not have a close date, this state is never reached." Controlled items include whether correct, marks, specific feedback, general feedback, right answer and overall feedback are shown — [SRC] `reviewoptionsheading_help`, quiz.php lang

**Extra restrictions / anti-cheating**
- `requiresubnet_help`: access "may be restricted to particular subnets ... useful for an invigilated (proctored) quiz" — [SRC]
- Browser security "Full screen pop-up with some JavaScript security": JS required, full-screen popup without navigation controls, "Students are prevented, as far as is possible, from using facilities like copy and paste" — [SRC] `browsersecurity_help`
- Safe Exam Browser integration is a quiz access rule (`quizaccess_seb`) in core since 3.9. It supports config keys / browser exam keys and uploaded or template configs — [DOC-UNVERIFIED] [docs: Safe Exam Browser](https://docs.moodle.org/en/Safe_Exam_Browser)

**Autosave / crash recovery**
- Site setting `quiz/autosaveperiod` ("Auto-save delay"), **default 60 seconds**: "Responses can be saved automatically during quiz attempts. The responses are saved whenever one is changed, and then after this delay. There is a trade-off: a shorter delay increases the server load, but reduces the chance that students lose their work... Setting the delay to 0 turns off au[to-save]" — [SRC] [settings.php line 92](https://github.com/moodle/moodle/blob/main/public/mod/quiz/settings.php) and `autosaveperiod_desc`
- Attempt state lives on the server (quiz_attempts + question_usages/question_attempt_steps), so after a browser crash the student logs in again and "Continue the last attempt" resumes with every saved response; the timer keeps running against the server-side start time — [DOC-UNVERIFIED] [docs: Quiz attempts](https://docs.moodle.org/en/Quiz_attempts)

### Inferences
- A browser crash costs at most the edits since the last autosave (≤ autosaveperiod). For Tech Drona, autosave on every answer change, with a debounce of a few seconds, plus a localStorage mirror to cover network loss. Moodle is server-only per the strings above; that it does no local caching is an inference.
- Copy these: a server-authoritative timer (deadline stored at attempt start), a grace-period concept, per-user/per-group overrides (extra time for accommodations), and the 4-phase review matrix. They are proven requirements.
- Placement prep needs coding questions, sectional timing and adaptive difficulty. Core Moodle has no coding question type or sectional timers, which is a gap a custom system should design in from day one.

### Gaps
- I could not verify the exact wording of the "abandon" overdue option or SEB config-key details from current docs.

## 5. Assignments, gradebook, completion, competencies, badges, certificates

### Takeaway
Grades flow from activities into a central gradebook (grade items → categories → course total, with aggregation methods). Activity completion and course completion form a separate tracking layer that drives restrict-access rules, badges and certificates. Competencies (learning plans/frameworks) are a third, optional layer.

### Cited Findings
- `mod_assign` supports file/online-text submissions, due/cut-off dates, rubric and marking-guide advanced grading, marking workflow and allocation, blind marking, extensions and group submissions — [DOC-UNVERIFIED] [docs: Assignment settings](https://docs.moodle.org/en/Assignment_settings)
- Quiz completion can require a passing grade. In that case "Grade to pass cannot be zero" (`gradetopassmustbeset`) — [SRC] quiz.php lang
- Gradebook: grade categories with aggregation (natural, mean, weighted mean, highest, etc.), a grader report, a user report, letters and scales — [DOC-UNVERIFIED] [docs: Grades](https://docs.moodle.org/en/Grades), [Grade aggregation](https://docs.moodle.org/en/Grade_aggregation)
- Activity completion (manual or automatic by view/grade/pass/submit) and course completion criteria — [DOC-UNVERIFIED] [docs: Activity completion](https://docs.moodle.org/en/Activity_completion), [Course completion](https://docs.moodle.org/en/Course_completion)
- Competency frameworks, learning plans, and evidence from activity/course completion — [DOC-UNVERIFIED] [docs: Competencies](https://docs.moodle.org/en/Competencies)
- Badges are Open Badges-compatible, awarded on completion criteria or manually — [DOC-UNVERIFIED] [docs: Badges](https://docs.moodle.org/en/Badges)
- Certificates: core has "Course certificate"/`tool_certificate`-based templates in Moodle Workplace and the popular plugins (mod_customcert). Core LMS has no long-standing native certificate activity, which is the reason customcert is widely used — [DOC-UNVERIFIED] [plugin: mod_customcert](https://moodle.org/plugins/mod_customcert)

### Inferences
- A placement platform should treat **completion + grade events** as the single source that triggers badges, certificates and "placement readiness" scores. Moodle's separate competency subsystem is heavy, so a simpler skill-tag score per question/category (aptitude, DSA, communication) is likely enough.

### Gaps
- None of the gradebook/completion/badge items could be re-verified against live docs this session.

## 6. Reports, logs, and session/auth security settings

### Takeaway
Moodle logs every action as an **event** into the standard log store (`logstore_standard_log`). That table feeds the Logs, Live logs, Activity report and Course participation reports. Sessions are server-side (DB-backed `sessions` table or Redis/Memcached), with idle timeout, an optional concurrent-login limit (the oldest session is killed), account lockout and a password policy. MFA has been core since 4.3.

### Cited Findings
**Logs/reports**
- Reports: Logs (filter by course/user/date/activity/action), Live logs (last hour, auto-refresh), Activity report (views per activity), Course participation (who did what per activity/role/time window), Activity completion report; legacy log stores have been deprecated in favour of the standard log store — [DOC-UNVERIFIED] [docs: Logs](https://docs.moodle.org/en/Logs), [Live logs](https://docs.moodle.org/en/Live_logs), [Course participation report](https://docs.moodle.org/en/Course_participation_report), [Logging](https://docs.moodle.org/en/Logging)
- Events API: each event carries crud (c/r/u/d), edulevel (teaching/participating/other), contextid, userid, relateduserid, objecttable/objectid and timecreated — [DOC-UNVERIFIED] [moodledev.io: Events API](https://moodledev.io/docs/apis/core/events)

**Session handling** ([GH: public/admin/settings/server.php](https://github.com/moodle/moodle/blob/main/public/admin/settings/server.php), strings in [GH: public/lang/en/admin.php](https://github.com/moodle/moodle/blob/main/public/lang/en/admin.php))
- `dbsessions` ("Use database for session information"): "If enabled, this setting will use the database to store information about current sessions. Note that changing this setting now will log out all current users... Other session drivers can be configured directly in config.php, see config-dist.php." It is only shown when `$CFG->session_handler_class` is empty — [SRC]
- `sessiontimeout`, **default 8 hours** (`8 * 60 * 60`): "If people logged in to this site are idle for a long time (without loading pages) then they are automatically logged out" — [SRC]
- `sessiontimeoutwarning`, **default 20 minutes**, validated to be less than `sessiontimeout` — [SRC]
- The `sessions` table ("Database based session storage - now recommended") has fields `id, state (0 = normal), sid char(128) unique, userid FK, sessdata text, timecreated, timemodified, firstip, lastip (char 45)` — [SRC] [GH: public/lib/db/install.xml](https://github.com/moodle/moodle/blob/main/public/lib/db/install.xml)

**Prevent multiple logins: `limitconcurrentlogins`**
- Setting name **`limitconcurrentlogins`**, label "Limit concurrent logins": "If enabled the number of concurrent browser logins for each user is restricted. **The oldest session is terminated after reaching the limit**, please note that users may lose all unsaved work. **This setting is not compatible with single sign-on (SSO) authentication plugins.**" — [SRC] [GH: public/lang/en/auth.php L129-130](https://github.com/moodle/moodle/blob/main/public/lang/en/auth.php) (it appears under Site admin > Plugins > Authentication > Manage authentication)
- Implementation `\core\session\manager::apply_concurrent_login_limit($userid, $sid)`: it runs "right after complete_user_login()", skips guests, returns when the setting is empty or <0, keeps the current sid, sorts the other sessions by `timecreated` DESC and destroys every session beyond the limit. Code notes: "Do not use from SSO auth plugins" and "Do not use from web services because they do not have sessions" — [SRC] [GH: public/lib/classes/session/manager.php ~L1119-1180](https://github.com/moodle/moodle/blob/main/public/lib/classes/session/manager.php)
- Related: `passwordchangelogout`: "when a password is changed, all browser sessions are terminated, apart from the one in which the new password is specified"; `passwordchangetokendeletion` deletes web-service tokens — [SRC] admin.php lang

**Login failure lockout** ([GH: public/admin/settings/security.php L89-91](https://github.com/moodle/moodle/blob/main/public/admin/settings/security.php))
- `lockoutthreshold` "Account lockout threshold" (default 0 = off): "number of failed login attempts that result in account lockout. This feature may be abused in denial of service attacks." — [SRC]
- `lockoutwindow` "Account lockout observation window" (default 30 min): "if there are no failed attempts the threshold counter is reset after this time." — [SRC]
- `lockoutduration` "Account lockout duration" (default 30 min): "Locked out account is automatically unlocked after this duration." — [SRC]

**Password policy** (same file L93-106)
- `passwordpolicy` (default **on**). Defaults: `minpasswordlength` 8, `minpassworddigits` 1, `minpasswordlower` 1, `minpasswordupper` 1, `minpasswordnonalphanum` 1; `maxconsecutiveidentchars` (0 disables); `passwordpolicycheckonlogin` (default off); `passwordreuselimit` (default 0): "Hashes of previously used passwords are stored in local database table". Enabling the policy "will not affect existing users until they ... change their password, or the 'Check password on login' setting is enabled" — [SRC]

**MFA (`tool_mfa`)**
- Core since **Moodle 4.3**. Before that it was a separate plugin — [WEB] [moodle.org/plugins/tool_mfa](https://moodle.org/plugins/tool_mfa), [docs 4.3: Multi-factor authentication](https://docs.moodle.org/403/en/Multi-factor_authentication)
- Factors in core (`admin/tool/mfa/factor/`): admin, auth, capability, cohort, email, grace, iprange, nosetup, role, sms, token (trusted device), totp, webauthn — [SRC] [GH: public/admin/tool/mfa/factor](https://github.com/moodle/moodle/tree/main/public/admin/tool/mfa/factor)
- Points model: "The weight of this factor if passed. **A user needs at least 100 points to log in.**" Separate MFA lockout: "Number of attempts a user can answer input factors before they are prevented from logging in" — [SRC] [GH: tool_mfa lang](https://github.com/moodle/moodle/blob/main/public/admin/tool/mfa/lang/en/tool_mfa.php)
- Security history: CVE-2025-62398 (MSA-25-0047), an MFA bypass for an attacker who already holds the password, fixed in 4.4.11 / 4.5.7 / 5.0.3. CVE-2026-58332 (MSA-26-0013, MDL-88767) affects the email factor — [WEB, third-party summaries] [HeroDevs CVE-2025-62398](https://www.herodevs.com/vulnerability-directory/cve-2025-62398), [HeroDevs CVE-2026-58332](https://www.herodevs.com/vulnerability-directory/cve-2026-58332). Check these against Moodle's MSA pages.

### Inferences
- Tech Drona's "single active session" rule for exams can copy `limitconcurrentlogins=1`: keep the newest session and kill older ones. Moodle's own warnings carry over: (a) unsaved work is lost, so pair it with aggressive autosave; (b) it conflicts with SSO; (c) API tokens bypass it. A per-user `sessions` table with `firstip/lastip/timecreated/timemodified` is a good minimal schema. Add `user_agent`/device fingerprint, which Moodle lacks, for proctoring audits.
- Moodle's default lockout is **off** (threshold 0) and its docs flag DoS abuse. Prefer progressive delay / per-IP throttling over hard account lockout.

### Gaps
- I did not verify the exact Live logs refresh interval or the participation report columns from live docs.

## 7. Data privacy (tool_dataprivacy, GDPR) and retention

### Takeaway
Moodle's privacy subsystem makes every plugin implement a Privacy API provider (metadata, export, delete). `tool_dataprivacy` adds a Data Protection Officer workflow for subject access and deletion requests, plus a **data registry** that assigns a *purpose* (lawful basis + retention period) and *category* to each context level/instance. A scheduled task flags expired contexts for deletion.

### Cited Findings
- `tool_dataprivacy` classes include `data_registry`, `purpose`, `purpose_override`, `category`, `contextlevel`, `context_instance`, `data_request`, `expired_context`, `expired_contexts_manager`, `expiry_info`, `metadata_registry` — [SRC] [GH: public/admin/tool/dataprivacy/classes](https://github.com/moodle/moodle/tree/main/public/admin/tool/dataprivacy/classes)
- Role-capability permissions themselves are declared as privacy metadata (e.g. `privacy:metadata:role_capabilities:permission`), which shows every component declares the personal data it stores — [SRC] role.php lang
- Workflow: users submit export/delete requests, the DPO approves them (automatic approval is configurable), exports are produced as zip files, and expired-context review happens before deletion. Purposes have retention periods and a "protected" flag that blocks deletion while active — [DOC-UNVERIFIED] [docs: Data privacy](https://docs.moodle.org/en/Data_privacy), [Data registry](https://docs.moodle.org/en/Data_registry), [Data requests](https://docs.moodle.org/en/Data_requests)

### Inferences
- India's **DPDP Act 2023** (outside this scope; verify separately) needs consent, access, correction and erasure flows. Moodle's pattern (each module declares and exports/deletes its own data, plus a central request queue and retention registry) is a good template. Build a `privacy_provider` interface per FastAPI module from day one, because retrofitting is expensive.

### Gaps
- I could not read the dataprivacy lang strings in this session (a regex error) or the live docs, so the workflow details are unverified.

## 8. Known limitations and lessons for a new custom system

### Takeaway
Moodle's strengths are a battle-tested quiz engine, a generic module/event/permission architecture and privacy plumbing. Its weaknesses for a placement-prep product are a complex RBAC, a PHP-session/DB-heavy runtime, no native coding assessments or Indian payment gateways, analytics limited to clicks, and large upgrade migrations (e.g. the 5.0 question-bank restructure).

### Cited Findings
- The 5.0 question-bank migration needed multi-step upgrade handling and produced tracked bugs (MDL-84466, MDL-86226) plus capability changes for non-editing teachers — [WEB] [docs: Question banks in upgraded sites](https://docs.moodle.org/en/Question_banks_in_upgraded_sites)
- Changing the session backend logs everyone out, and on MySQL `max_allowed_packet` must be ≥4M — [SRC] `configdbsessions`
- Concurrent-login limiting is incompatible with SSO and does not apply to web services — [SRC] auth.php lang and session manager comments
- The quiz grace period is an explicit trade-off between server load and cheating — [SRC] `graceperiodmin_desc`
- The source tree moved to a `public/` web root in the current `main` (6.0dev) — [SRC] [GH: moodle/moodle main](https://github.com/moodle/moodle/tree/main/public)

### Inferences
- **Copy:** the course-module abstraction; an event log with crud/edulevel; context-scoped role assignment; quiz attempt/step storage (an immutable step log per question makes regrading and dispute resolution possible); the 4-phase review matrix; overrides; per-module privacy providers.
- **Simplify:** permissions (no Prevent/Prohibit), and a single course format.
- **Add natively:** coding questions with sandboxed judges, sectional timers, proctoring signals (tab blur, fullscreen exit, IP/device change logged as events), Razorpay/UPI, and placement-specific entities (companies, drives, eligibility criteria) that Moodle lacks entirely.

### Gaps
- I found no authoritative Moodle performance/scale benchmark in this session.

## 9. Canvas and Open edX: notable differences (LTI, xAPI/Caliper, time-on-task)

### Takeaway
Canvas emits **Live Events** (Canvas-native or **Caliper 1.1** JSON-LD) and centres on LTI 1.3/Advantage for tool integration. Open edX keeps native tracking logs and derives **xAPI (default) or Caliper** through `event-routing-backends`, feeding the Aspects analytics stack. Every LMS "time spent" metric is a heuristic over click gaps, and research shows the heuristic choice changes analytic conclusions.

### Cited Findings
**Canvas**
- "Caliper live events are Canvas live events transformed into Caliper format... We are currently using version 1.1 of the Caliper specification." There is one message per event, with Canvas extensions for properties Caliper doesn't cover — [WEB] [Instructure: Caliper IMS 1.1](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/caliper-ims-1.1), [Canvas event format](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/canvas)
- LTI 1.3 Assignment and Grade Services sync grades, and Names and Roles Provisioning gives rosters, both configured as developer-key scopes — [WEB] [Canvas External Tools intro](https://canvas.colorado.edu/doc/api/file.tools_intro.html)
- Canvas "Total Activity": viewing time counts only when a view exceeds ~2 minutes; if the gap between activities is under 10 minutes the gap is included; video watching without intermediate page requests is not captured. Users report it keeps growing while a tab sits idle — [WEB, community/institutional, not official spec] [Canvas Community: What does Total Activity mean](https://community.canvaslms.com/t5/Admin-Group/What-does-Total-Activity-mean/m-p/71879), [Palomar College](https://www.palomar.edu/atrc/2017/12/05/canvas-student-activity-indicators/). I found no official Instructure specification of the algorithm.

**Open edX**
- Aspects ADR: "Aspects is designed to support xAPI as its default standard". Tracking-log events are transformed to xAPI by `event-routing-backends` and sent to an LRS. Tracking logs remain the "Open edX native" format — [WEB] [Aspects ADR 0002: xAPI](https://docs.openedx.org/projects/openedx-aspects/en/latest/technical_documentation/decisions/0002_xapi.html)
- `event-routing-backends` has `XApiProcessor` and `CaliperProcessor`. Caliper is off by default (`CALIPER_EVENTS_ENABLED`). Routing uses Celery tasks per router, with retries for business-critical events (enrolment, first-time grade pass), and there is an event-bus option in Ulmo — [WEB] [ERB getting started (Teak)](https://event-routing-backends.readthedocs.io/en/release-teak/getting_started.html), [ERB configuration (Ulmo)](https://event-routing-backends.readthedocs.io/en/ulmo/technical_documentation/quickstarts/configuration.html), [OEP-26](https://open-edx-proposals.readthedocs.io/en/latest/oep-0026-arch-realtime-events.html)

**Time-on-task research**
- Kovanović, Gašević, Dawson, Joksimović, Baker, Hatala (LAK 2015, "Penetrating the black box of time-on-task estimation") and the J. Learning Analytics 2015 paper "Does time-on-task estimation matter?": LMSs only log discrete actions, so time-on-task is estimated. The estimation method is rarely reported, and across two datasets (online and blended) the choice of estimation strategy significantly changed learning-analytics models of performance — [WEB] [Monash research portal](https://research.monash.edu/en/publications/penetrating-the-black-box-of-time-on-task-estimation/), [Adelaide repository](https://digital.library.adelaide.edu.au/items/277d3daa-8658-4e24-aaa2-627873ca080e)
- Later work: "Time-on-task estimation for tasks lasting hours spread over multiple days" (PLOS ONE, PMC12445496), and EDM 2021 "Fine-Grained Versus Coarse-Grained Data for Estimating Time-on-Task in Learning Programming" — [WEB] [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12445496/), [EDM 2021](https://educationaldatamining.org/EDM2021/virtual/static/pdf/EDM21_paper_176.pdf). I did not read the full texts.
- IntelliBoard documents its own differing time-spent heuristics per LMS. This is a vendor source — [WEB] [IntelliBoard: Tracking Time Spent in Different LMS Platforms](https://intelliboard.atlassian.net/wiki/spaces/KB/pages/2851176453/Tracking+Time+Spent+in+Different+LMS+Platforms)

### Inferences
- Tech Drona should emit **xAPI-shaped events** internally (actor, verb, object, context, result, timestamp), or at least store events in a shape that maps to xAPI/Caliper. That keeps analytics portable to an LRS or to recruiter/partner systems.
- For "time spent", don't rely on page-view gaps. Use **client heartbeats** (e.g. every 15–30 s while the tab is visible, using the Page Visibility API and an idle detector) and report the cutoff/heuristic used. The literature's criticism is that undisclosed heuristics produce non-comparable results. Keep raw events so the metric can be recomputed.
- Support **LTI 1.3 (as a platform)** to embed third-party coding judges or proctoring tools, and **LTI as a tool** so colleges on Moodle/Canvas can launch Tech Drona content. Moodle ships both `mod_lti` and `enrol_lti` — [SRC] module/enrol lists above.

### Gaps
- I did not verify Canvas's New Analytics current algorithm against an official Instructure document. Only community and institutional explanations were found.
- I did not obtain the specific estimation methods and outlier thresholds from the Kovanović paper's full text.
