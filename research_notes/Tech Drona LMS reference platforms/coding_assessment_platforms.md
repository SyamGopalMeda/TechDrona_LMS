# Coding Assessment, Competitive-Programming & Proctoring Platforms: Reference for Tech Drona

Research date: 2026-11-03. Scope: HackerRank (primary), HackerEarth, LeetCode, Codeforces, Mercer|Mettl, plus open-source judges (Judge0, isolate, Piston, DMOJ) and sandbox tech (gVisor, Firecracker).
Note on method: about 16 search/fetch calls. Vendor help-centre pages were fetched directly where possible. Vendor accuracy numbers are vendor claims, and nobody has checked them independently. Anything marked [Inference] is my reasoning, not a sourced fact. Several third-party "how to beat HackerRank" blogs (aceround, interviewcoder, prachub) showed up in searches. I avoided them as primary evidence except where noted.

## 1. Coding challenge UX (problem statement, editor, languages, sample vs hidden tests, partial scoring, run vs submit, limits, verdicts)

### Takeaway
The standard pattern is visible sample tests on "Run" and hidden tests on "Submit", scored per test case. That gives partial credit by passed and weighted cases. Per-submission CPU, wall and memory limits are configurable. Judge0's defaults (5 s CPU, 10 s wall, 512 MB cap) are a useful starting point.

### Cited Findings
- HackerRank help (Dec 2024): a candidate's "Run test" does **not** show whether hidden test cases passed. Hidden files are added only at scoring time, after submission. Evaluators see all test cases, hidden ones included, in the candidate report — [HackerRank KB: Hidden Test Cases for FE/BE/Full Stack](https://hackerrank-knowledge-base.help.usepylon.com/articles/1626384486-hidden-test-cases-for-front-end%2C-back-end-and-full-stack-questions)
- Partial scoring: a third-party summary says HackerRank adds up points from passed test cases (each case is pass/fail, and case weights can differ, e.g. hard hidden cases worth 20 each). Employers configure this per test — [PracHub (secondary)](https://prachub.com/resources/do-partial-test-cases-count-in-an-oa-hidden-tests-weighted-scores-and-cutoffs). A LinkedIn post from a competing vendor claims hidden cases do run on "Run" with output shown. That **conflicts** with the HackerRank KB above and is unverified — [LinkedIn (vendor)](https://in.linkedin.com/in/aakashre)
- Another assessment vendor (WeCP) documents the same split: "Run Code" does not test against hidden cases and computes no score — [WeCP help](https://help.wecreateproblems.com/en/articles/5956962-what-is-the-difference-between-run-code-and-submit-code)
- Judge0 supports 90+ languages. Per submission it allows custom compiler options, CLI args, and time and memory limits. Two flavours exist, CE and "Extra CE", which differ mainly in their language sets — [Judge0 GitHub](https://github.com/judge0/judge0)
- Judge0 default limits from the CHANGELOG:
  - CPU_TIME_LIMIT 5 s, with CPU_EXTRA_TIME 1 s and MAX_CPU_EXTRA_TIME 5 s (v1.8.0)
  - WALL_TIME_LIMIT 10 s (v1.8.0); since v1.13.0 the wall limit must be at least 1 s
  - MAX_MEMORY_LIMIT 512000 KB (v1.7.0); minimum memory 2048 KB (v1.6.0)
  - MAX_PROCESSES_AND_OR_THREADS 60, with a hard maximum of 120 (v1.5.0)
  - Network is controlled by ENABLE_NETWORK / ALLOW_ENABLE_NETWORK (v1.13.0)

  — [Judge0 CHANGELOG](https://raw.githubusercontent.com/judge0/judge0/master/CHANGELOG.md)
- isolate's limit model: `--time` (CPU) with `--extra-time`, and `--wall-time` (catches programs that just sleep). Memory uses `--mem` (address space), `--stack` and `--cg-mem` (cgroup total). Processes default to 1, raised with `--processes`. Files use `--open-files`, `--fsize` and `--quota`. `--core` defaults to 0 — [isolate(1) man page](https://www.ucw.cz/isolate/isolate.1.html)

### Inferences
- [Inference] Tech Drona should copy this split: "Run" executes only sample or custom input and returns stdout/stderr, and "Submit" runs hidden cases server-side and returns per-case verdicts (AC, WA, TLE, MLE, RE, CE) and a weighted score. Hidden inputs should never reach the client.
- [Inference] Judge both CPU time and wall time. A CPU-only limit lets `sleep` or blocked I/O tie up workers.
- [Inference] Indian placement tests (TCS NQT, AMCAT Automata style) mostly use C, C++, Java and Python. Starting with about 6–8 languages limits the cost of maintaining compiler images.

### Gaps
- I could not fetch HackerRank's own pages on candidate-side editor features (autocomplete, custom input, language list) or the exact names of its verdicts.
- I found no official HackerRank documentation of default time and memory multipliers per language. HackerRank has published a per-language "environment" table in the past, but I did not verify it here.
- I did not research CodeChef's or HackerEarth's partial-scoring UX in detail.

## 2. Online assessment workflow, plagiarism detection, proctoring, integrity reports (with accuracy and privacy limits)

### Takeaway
The market has moved from MOSS-style similarity checks to ML signals: keystroke and code-evolution data, copy-paste, tab switches, webcam and screenshots. These are rolled into a High/Medium (or Low) integrity rating that a human reviews. HackerRank's own published precision is 85%, so roughly 1 in 7 flags is wrong. Independent research documents racial bias and false positives in automated proctoring. Flags must stay advisory, and consent is mandatory.

### Cited Findings
**HackerRank plagiarism detection**
- There are two layers. (a) Standard detection uses **MOSS**: it compares code against other submissions in HackerRank's database, with language-specific thresholds, and is on by default. (b) Advanced ML detection uses code-writing patterns, time taken, copy-paste and tab switching — [HackerRank KB: AI Plagiarism Detection](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection)
- The reasons shown to reviewers are "Code Similarity" and "Coding Patterns". Sub-patterns include "Suspicious Code Resetting" (large deletes or replacements with irregular typing or cursor movement) and "External Copy-Paste" — [same](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection)
- **Accuracy:** the help centre states an **overall precision of 85%**. Flags are rated High or Medium by confidence. HackerRank's marketing elsewhere claims "93% accuracy" and "3x" better than similarity checks — [HackerRank KB](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection); [HackerRank plagiarism detection page](https://www.hackerrank.com/features/plagiarism-detection). The two figures do not match (different metrics or dates). I found no independent validation of either.
- **Documented limitations:** detection is weaker for questions that take little effort to score fully and for very short solutions. Advanced detection covers Coding questions only. Writing code in an external IDE and pasting it in is "likely to be flagged" — [HackerRank KB](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection)
- Candidates must give consent before the test when advanced detection is on. Reviewers check a flag with the **Keystroke Codeplayer**, a replay of how the code was typed — [same](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection)

**HackerRank Proctor Mode** (available for tests created after the July 2025 release)
- The test launches full-screen. Tab switches and leaving full screen are flagged and logged, and copy-paste into the editor is disabled.
- Only one monitor is allowed: onboarding blocks if more than one is connected, and new connections are flagged.
- Webcam AI checks presence and multiple faces, and runs object detection for phones and tablets.
- "Conversation detection" flags type-and-delete patterns in the editor that may be messages to someone else, including regional languages typed in English.
- Screenshot analysis flags AI assistants, answer sites, collaboration tools and screen recorders.

  — [HackerRank KB: Proctor Mode](https://hackerrank-knowledge-base.help.usepylon.com/articles/5663779659-proctor-mode)
- Capture rates:
  - Webcam images every **5 s** (tests that collect personal information).
  - Screenshots every **15 s**, dropping to **5 s** after suspicious events.
  - Each screenshot is classified by a model as suspicious or not, with an explanation.

  — [same](https://hackerrank-knowledge-base.help.usepylon.com/articles/5663779659-proctor-mode). Third-party blogs give other frequencies (about 1/min). The official KB figure takes precedence.
- Integrity report: an overall High or Medium result, an Integrity Summary with drill-down evidence, and **Session Replay**. Session Replay is a timeline recording of the full browser screen with searchable events and synced screenshots and webcam images. Proctor Mode must be enabled at both company and test level, and it is **locked once candidates start** (changing it requires cloning the test) — [same](https://hackerrank-knowledge-base.help.usepylon.com/articles/5663779659-proctor-mode)
- Consent and privacy: candidates review the list of prohibited actions and must consent. They must grant webcam, screen share and full screen. The KB page does **not** state how long images or recordings are kept — [same](https://hackerrank-knowledge-base.help.usepylon.com/articles/5663779659-proctor-mode)

**Other vendors**
- Mercer|Mettl "Candidate Credibility Index": rated High, Medium or Low, built from proctoring flags and test-finish status. It was in Beta and enabled on request (2023 article). It is not shown in shared reports and can be used as a results filter — [Mettl support](https://support.mettl.com/portal/en/kb/articles/candidate-credibility-index-in-proctoring-reports-18-4-2023). Mettl's security document says experts review sessions — [Mettl Security Document V2](https://mettl.com/downloads/wp-content/uploads/sites/12/2020/05/MM_Security-Document_V2.pdf)
- HackerEarth (Mar 2024): upgraded snapshot proctoring and added a "candidate looking away" violation. Its integrity index summarises the number and severity of violations (tab switches, snapshot violations, plagiarism) — [HackerEarth release notes 7 Mar 2024](https://help.hackerearth.com/release-notes-march-7-2024)

**Accuracy and privacy research**
- Burgess, Ginsberg, Felten & Cohney, "Watching the Watchers" (AALS 2022 preprint, not peer-reviewed): an audit of the most widely used exam-proctoring suite. Its face detection performs worse than off-the-shelf classifiers, and faces from some racial groups are substantially more likely to cause false positives or false negatives. The paper also discusses privacy risks of software installed on personal machines — [Cohney et al. PDF](https://am.aals.org/wp-content/uploads/sites/4/2022/02/Cohney-Internet-and-Computer-Law.pdf); [Foley summary](https://www.foley.com/?p=47293)
- EFF: AI cheating detection is criticised for bias, accessibility impacts and significant false positives. EFF cites ExamSoft flagging about one-third of California Bar test-takers (advocacy source) — [EFF Deeplinks 2021](https://www.eff.org/deeplinks/2021/06/long-overdue-reckoning-online-proctoring-companies-may-finally-be-here)
- A systematic literature review of AI-proctored exams reports privacy violations, exam anxiety and algorithmic bias (full text not verified) — [Sinop Univ. repository](https://acikerisim.sinop.edu.tr/items/f48d1942-b826-4228-b4bd-a50a0b641b06/full)

### Inferences
- [Inference] India's DPDP Act 2023 and its Rules (notified 2025) apply to webcam images, screen recordings and keystroke data. Tech Drona needs explicit notice and consent, purpose limitation, a stated retention period (HackerRank's KB doesn't state one, which is a gap to avoid), and stricter handling for minors, since some students may be under 18. This was not researched here, so verify with counsel.
- [Inference] The MVP integrity stack can be cheap: full-screen and visibilitychange/blur logging, paste-event logging (rather than blocking, which hurts accessibility), keystroke and snapshot code history for replay, and MOSS or JPlag similarity within a cohort. Webcam AI and screenshot AI can come later.
- [Inference] Show integrity signals as "review recommended", never as automatic disqualification. Even HackerRank, a market leader, documents 85% precision.
- [Inference] Browser-based tab and paste detection can be bypassed with a second device or a phone. That is why vendors added webcam object detection and multi-monitor checks. For college placement drives, an invigilated lab plus a lockdown browser may beat remote AI proctoring on both cost and privacy.

### Gaps
- I did not fetch HackerRank's own pages on test creation (sections, MCQ+coding mix, invites, cut-offs, timed sections). HackerRank Test Integrity overview: https://hackerrank-knowledge-base.help.usepylon.com/articles/1079706165 (not fetched).
- I found no independent false-positive data for HackerRank, Mettl or HackerEarth.
- I did not research AMCAT/SHL or iMocha proctoring specifics.
- I did not fetch the MOSS primary sources (Aiken; Schleimer et al. 2003 "Winnowing").

## 3. Code execution architecture: sandboxing, limits, network isolation, queueing, Judge0 cost and licence, CVEs

### Takeaway
Most open-source judges rely on Linux namespaces, cgroups and rlimits, through isolate (used by Judge0) or plain Docker (Piston). That is a shared-kernel boundary. Judge0 had CVSS 10.0 sandbox escapes in 2024 caused by misconfiguration and host-side code around isolate, not by isolate itself. Judge0 is GPL-3.0 and its cloud plans cost about €27–107/month for 2k–10k submissions/day. For hostile, internet-facing code, layer gVisor or Firecracker under the judge.

### Cited Findings
**isolate**
- Uses a private filesystem namespace and a new network namespace (loopback only), so the network is isolated by default; `--share-net` disables that.
- `--cg` mode requires **cgroup v2** (v1 is incompatible), and memory reporting needs Linux 5.19+.
- Installed setuid-root, it drops to a per-box UID. It blocks `keyctl`, `AF_VSOCK`, `io_uring` and similar.
- It recommends disabling swap and setting `fs.protected_hardlinks=1`. Running isolate inside containers is discouraged because they usually don't delegate cgroups properly.
- Licence: GPL-2.0-or-later.

  — [isolate(1) man page](https://www.ucw.cz/isolate/isolate.1.html)

**Judge0**
- Latest release in the CHANGELOG is **v1.13.1 (2024-04-18)**.
- Linux only, Ubuntu 22.04 recommended. It requires **switching the host to cgroup v1** (`systemd.unified_cgroup_hierarchy=0` in GRUB).
- Runs with Docker Compose plus PostgreSQL and Redis; set REDIS_PASSWORD and POSTGRES_PASSWORD.

  — [Judge0 CHANGELOG](https://raw.githubusercontent.com/judge0/judge0/master/CHANGELOG.md)
- Licence **GPL-3.0**. Deployment options are self-host, Judge0 Cloud via RapidAPI, or direct contact with the team — [Judge0 GitHub](https://github.com/judge0/judge0)
- Cloud pricing on judge0.com: **Pro €27/mo, 2,000 submissions/day; Ultra €54/mo, 5,000/day; Mega €107/mo, 10,000/day**, plus €0.001 per extra submission — [judge0.com](https://judge0.com/). An older RapidAPI page lists tiers of 50, 500, 2,000 and 5,000/day with 1,000 req/hr (possibly out of date) — [RapidAPI Judge0 CE pricing](https://rapidapi.com/zh/judge0-official/api/judge0-ce/pricing)

**Judge0 2024 CVEs** (Tanto Security)
- **CVE-2024-28185** (CVSS 10.0): a symlink in the sandbox directory let `run_script` writes land outside the sandbox, giving code execution on the host. Reported 4 Mar 2024, patched 6 Mar.
- **CVE-2024-28189**: a patch bypass using `chown` on root-owned files. Patched 9 Mar.
- A further bypass via `/api/tmp/environment` was patched 10 Mar (no CVE listed).
- **CVE-2024-29021**: SSRF from sandboxed code to the internal PostgreSQL, where an altered `stack_limit` column injected shell commands. Fixed in v1.13.1 on 18 Apr 2024.

  — [Tanto Security write-up](https://tantosec.com/blog/judge0/); [Infosecurity Magazine](https://www.infosecurity-magazine.com/news/judge0-sandbox-flaws-systems/); [cvefeed CVE-2024-28185](https://cvefeed.io/vuln/detail/CVE-2024-28185)
- Root causes:
  - A deny-list filter that missed `\n`
  - Shell interpolation through Ruby backticks
  - Host-side file operations that followed symlinks (including symlinks in zip `additional_files`)
  - A **`--privileged` container** with the app running as root
  - **`--share-net` on by default**
  - A default Postgres password in the config

  The public ce.judge0.com had network sharing disabled, which blocked the SSRF path. The author says the underlying arbitrary-write primitive remained after the patches — [Tanto Security](https://tantosec.com/blog/judge0/)

**gVisor vs Firecracker**
- Firecracker runs code in a hardware-virtualised microVM with its own guest kernel. gVisor intercepts syscalls in a userspace kernel written in Go.
- Firecracker is near-native once booted. gVisor is near-native for CPU work but pays a cost on every syscall.
- Firecracker runs AWS Lambda and Vercel Sandbox. gVisor runs Cloud Run, GKE Sandbox and App Engine.

  — [Fly.io: Firecracker vs gVisor](https://fly.io/learn/firecracker-vs-gvisor/)
- Piston is described as Docker containers on a shared kernel (competitor marketing page, low reliability) — [cratera docs.rs](https://docs.rs/crate/cratera/1.0.0)

### Inferences
- [Inference] Judge0's need for cgroup v1 is a real operational problem in 2026. Current distros and managed Kubernetes default to cgroup v2, and isolate's own cg-mode now requires v2. Expect a dedicated VM per Judge0 host, not Kubernetes pods.
- [Inference] GPL-3.0 (not AGPL): running Judge0 unmodified as a separate network service called over HTTP generally does not trigger source disclosure. GPL obligations are triggered by distribution, and calling it over an API does not make Tech Drona's LMS a derivative work. Distributing modified Judge0 (e.g. on-prem installs for colleges) would trigger obligations. This is not legal advice; confirm with counsel.
- [Inference] Rough cost check: a placement drive of 2,000 students × 3 problems × about 10 submissions × 10–20 hidden tests. Whether a "submission" counts per test case depends on how batching is used, so test volumes can exceed 10k/day quickly. A self-hosted worker pool on 2–4 vCPU VMs is likely cheaper at peak, but you pay in ops and security.
- [Inference] Recommended defence-in-depth for a self-hosted judge:
  - Network off (no `--share-net`), and no route from sandboxes to the DB or Redis
  - No privileged containers; never change the DB default password
  - Workers on separate VMs, or in gVisor (runsc), or in Firecracker microVMs
  - Queue (Redis or SQS) with per-user rate limits
  - Pinned, patched versions, and subscription to GHSA advisories

### Gaps
- I did not verify DMOJ's judge architecture (it uses ptrace/seccomp-based "cptbox") or Piston's own docs. Check GitHub (DMOJ/judge-server, engineer-man/piston).
- I found no public figures on HackerRank's or LeetCode's internal sandbox stack or scale.
- I did not check whether Judge0 shipped a release after v1.13.1 (none appears in the CHANGELOG as fetched).

## 4. Account integrity: multiple accounts, sharing, cheating policies and detection (public evidence only)

### Takeaway
Competitive platforms enforce "one person, one account" and punish code similarity between accounts after the contest (rating rollback, then bans). LeetCode publishes an explicit ladder: a 1-month ban for a first offence, then permanent deactivation. Detection mostly means automated similarity checks after the contest plus user reports.

### Cited Findings
- LeetCode penalties, stated as applied "without prior warnings":
  - **First offence:** one-month contest ban, contest score zeroed, LeetCoins reset to zero (the Sep 2024 rule adds a one-month discussion-post ban).
  - **Second offence:** permanent account deactivation without appeal.

  — [LeetCode: New Contest Rule (Updated Sep 2024)](https://leetcode.com/discuss/post/951105/); [LeetCode: Maintaining Fairness announcement](https://leetcode.com/discuss/post/5232896/)
- LeetCode support lists "multiple accounts submitting similar code for the same problem" as a violation. Users can report violators through a support form — [LeetCode support: contest violations](https://support.leetcode.com/hc/en-us/articles/360011984933) (403 when fetched; content via search snippet); [LeetCode: report a violation](https://support.leetcode.com/hc/en-us/articles/7962266478227-How-do-I-report-a-user-for-a-contest-violation)
- Pre-written templates are allowed if written before the contest, but shared templates may be mistaken for cheating — [LeetCode contest rule](https://leetcode.com/discuss/post/951105/)
- Codeforces requires one account per person. Registering for a rated round confirms you are using your only account, and breaking the rules implies consent to punishment. Automatic plagiarism checks run after contests, and ratings are temporarily rolled back while checks run. Code that was public before the contest is not cheating — [Codeforces blog entry 113185 (user post quoting rules)](https://codeforces.com/blog/entry/113185); [Codeforces topic 133557 – plagiarism checker bug (2024)](https://codeforces.net/topic/133557/en1)
- In 2024 a Codeforces user reported a bug in the plagiarism checking system. Users also argue that evaders defeat the checks by inserting junk code — [Codeforces topic 133557](https://codeforces.net/topic/133557/en1)

### Inferences
- [Inference] For Tech Drona the practical controls are:
  - Verified phone or email plus college roll number at signup
  - Device and IP fingerprinting logged (not auto-banned)
  - Post-contest similarity (MOSS/JPlag) within a cohort, using normalised token comparison so junk-code padding doesn't defeat it
  - A published penalty ladder modelled on LeetCode's
  - A rule that leaderboard ranks are provisional until the plagiarism pass finishes, as Codeforces does

### Gaps
- I did not retrieve HackerRank's Terms or community policy text on multiple accounts and account sharing.
- I did not retrieve Codeforces' official rules page directly; the findings above come from blog posts quoting it.
- I found no public detail on device fingerprinting by any of these platforms.

## 5. Timed test resilience: autosave, reconnect after crash, server-authoritative timers

### Takeaway
I found no HackerRank documentation on this in the time available. Comparable assessment vendors document that the timer keeps running server-side after the browser closes, and that resume is allowed within a window, sometimes with re-verification.

### Cited Findings
- Xobin: the timer keeps running in the background when the browser is closed. Reconnecting within 30 minutes in the same browser session may allow continuing — [Xobin docs](https://docs.xobin.com/en-us/article/what-happens-if-a-candidate-closes-the-browser-1ud8fkd/)
- Bubble exam: the session isn't lost after a crash, the timer continues behind the scenes, and re-verification of identity may be required — [Bubble support](https://bubble.io/support/en/articles/8709063-what-happens-if-my-exam-crashes)
- One quiz platform saves answers locally in the browser every 10 s and clears them only on normal exit — [Wikibooks Question Writer manual](https://en.wikibooks.org/wiki/Question_Writer_Manual/Quiz_Options/Web_Settings/Browser_Options)
- A practice-exam product user reported losing answered questions on resume in timed mode, which shows the bug risk — [Tutorials Dojo forum](https://portal.tutorialsdojo.com/forums/discussion/bug-timed-mode-loses-many-answered-questions-on-resume/)

### Inferences
- [Inference] Recommended design:
  - Store `started_at` and `deadline_at` on the server. The client shows a countdown but never decides the deadline.
  - Debounce autosave of editor content and MCQ answers to the server every 5–10 s and on blur, mirrored to IndexedDB for offline gaps.
  - Store answers idempotently, keyed by (attempt, question) with a version number.
  - On reconnect, rehydrate from the server.
  - Auto-submit last saved state at the deadline from a server job.
  - Allow an admin to grant extra time.
  - Log disconnects as integrity events rather than penalties.

  Indian college Wi-Fi and power cuts make this essential.

### Gaps
- HackerRank's, HackerEarth's and Mettl's specific resume, autosave and timer behaviour is unverified here.

## 6. Lessons and build-vs-buy recommendation for Tech Drona (synthesis)

### Takeaway
Build the coding-practice UX, test authoring and integrity reporting in-house, since they are the product. Buy or reuse the execution engine at first. The options are the Judge0 Cloud plan (€27–107/mo) for the MVP, then a hardened self-hosted Judge0 or isolate setup on isolated VMs, or gVisor, once volume or data-residency needs justify it. Treat proctoring AI as advisory and privacy-sensitive.

### Cited Findings
- Judge0 is self-hostable or available as managed cloud, under GPL-3.0 — [Judge0 GitHub](https://github.com/judge0/judge0); prices — [judge0.com](https://judge0.com/)
- Self-hosting carries real security risk: CVSS 10.0 escapes caused by privileged containers, network sharing and host-side file handling — [Tanto Security](https://tantosec.com/blog/judge0/)
- Market leaders keep human review on top of AI integrity flags. HackerRank tells reviewers to use the codeplayer and cites 85% precision; Mettl uses expert review — [HackerRank KB](https://hackerrank-knowledge-base.help.usepylon.com/articles/7287334157-ai-plagiarism-detection); [Mettl Security Doc](https://mettl.com/downloads/wp-content/uploads/sites/12/2020/05/MM_Security-Document_V2.pdf)
- Automated proctoring has documented bias and false-positive problems — [Cohney et al.](https://am.aals.org/wp-content/uploads/sites/4/2022/02/Cohney-Internet-and-Computer-Law.pdf); [EFF](https://www.eff.org/deeplinks/2021/06/long-overdue-reckoning-online-proctoring-companies-may-finally-be-here)

### Inferences
- [Inference] **Phase 1 (MVP):** use Judge0 Cloud or RapidAPI behind your own backend proxy. Never expose the API key to the browser, and keep hidden tests on your server; send them as stdin batches. Build the integrity basics yourself: full-screen and tab events, paste logging, code snapshots for replay, MOSS/JPlag within a cohort. Build server-authoritative timers and autosave.
- [Inference] **Phase 2 (scale, or college on-prem or data-residency deals):** self-host Judge0 v1.13.1+ or a thin isolate-based runner on dedicated VMs in an Indian region. Turn network off, avoid privileged mode, use a separate DB network, set strong passwords, and keep a patch cadence. Put a queue in front, with autoscaling workers sized for drive peaks.
- [Inference] **Phase 3:** move workers to gVisor or Firecracker for a stronger boundary. Add webcam and screenshot AI only with DPDP-compliant consent, a stated retention period and an appeals process.
- [Inference] **Alternative "buy everything" route:** white-label or partner with HackerEarth, Mettl or iMocha for proctored placement drives, and keep practice in-house. This is faster for enterprise clients but costs per candidate and gives weaker product ownership. Pricing was not researched.
- [Inference] Licence choice: if Judge0's GPL-3.0 conflicts with plans to ship on-prem appliances, isolate (GPL-2.0+, used as a separate binary) or a custom runner on gVisor avoids embedding GPL code in proprietary software. Get legal review.

### Gaps
- I did not research pricing for HackerRank, HackerEarth, Mettl, iMocha or SHL/AMCAT, or their partner and white-label programmes.
- I found no benchmark of self-hosted Judge0 throughput per vCPU.
