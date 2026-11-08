# 01 - Drive C: Disk Usage Audit (read-only)

- Date: 2026-11-07. Machine: Windows 11 Home 10.0.26300, profile `C:\Users\SYAM`.
- Drive C at scan time: **360.7 GiB used, 8.4 GiB free** (free space fluctuates; it was ~2 GB earlier).
- Method: non-elevated PowerShell (`Get-ChildItem -Recurse -Force | Measure-Object`). Nothing was deleted, moved or modified.
- Caveat: the shell was **not elevated**, so access-denied folders (System Volume Information, parts of `C:\Windows`, Delivery Optimization, Minidump, `C:\Windows\Temp`) under-report. WinSxS over-reports (hard links). Sizes are GiB.
- Out of scope here (covered by other audits): WSL/Docker virtual disks and temp/package caches. Their totals are noted for context only.

Categories: **protected** (never clean), **user-decision** (personal files, user's choice only), **app data**, **system**, **likely-safe-cache**.

## 1. Top-level of C:\

| Path | Size GB | What it is | Category | Recoverable estimate |
|---|---:|---|---|---|
| C:\Users | ~236 | User profiles (SYAM ~234, Public 2.19; "All Users" is a junction to ProgramData) | mixed (see below) | see sections 2-3 |
| C:\Windows | 39.8 | OS (WinSxS 18.3 counted with hard links, DriverStore 5.2, Installer 3.5) | system | ~0-3 via built-in Disk Cleanup / DISM component cleanup only |
| C:\Program Files | 24.1 | 64-bit apps (Office 4.0, Docker 3.9, JetBrains 3.1, Visual Studio 2.7, PostgreSQL 1.8, MySQL 1.3, WSL 1.1) | app data | only by uninstalling unused apps |
| C:\pagefile.sys | 20.5 | Virtual memory page file (system-managed, 21008 MB allocated) | system | 0 recommended (can be capped, not removed) |
| C:\Program Files (x86) | 9.2 | 32-bit apps (Microsoft 6.0 = Edge/WebView2/Copilot, Windows Kits 1.8) | app data | small |
| C:\ProgramData | 6.1 | Machine-wide app data (Microsoft 1.6, SYAM\Postman 1.4, Package Cache 0.6, mingw64 0.6, chocolatey 0.5) | app data | ~0.5 |
| C:\flutter | 3.2 | Flutter SDK | app data (dev tool) | 3.2 if Flutter no longer used (user decision) |
| C:\xampp | 0.76 | XAMPP stack | app data | if unused |
| C:\edb, C:\ffmpeg, C:\Python313, C:\php-8.3.13, C:\platform-tools, C:\tmp | 0.26 / 0.25 / 0.15 / 0.08 / 0.02 / 0.01 | Dev tools / SDKs | app data | small |
| C:\swapfile.sys | 0.02 | UWP swap | system | 0 |
| C:\hiberfil.sys | not present | Hibernation is not available on this machine (S0 Modern Standby; no hibernate file) | system | 0 |
| C:\$Recycle.Bin | 0.00 (visible to current user) | Recycle Bin | likely-safe-cache | ~0 |
| C:\Windows.old | not present | Previous Windows install | system | 0 |
| System Volume Information | not readable (non-admin) | Restore points / shadow copies | system | unknown; check with elevated `vssadmin list shadowstorage` |
| Other root folders (Android, data, demo, models, inetpub, Voiceover, XboxGames, OneDriveTemp, Recovery, avast! sandbox, $SysReset) | ~0 | empty or near-empty | - | 0 |

Accounting gap: roughly 20 GB of used space is not visible to a non-elevated scan (System Volume Information / shadow copies, protected Windows folders, NTFS metadata).

## 2. C:\Users\SYAM top level (from earlier scan)

| Path | Size GB | What it is | Category |
|---|---:|---|---|
| AppData | 132.5 | Application data (breakdown below) | mixed |
| Downloads | 47.2 | Downloads folder | **protected** (size only) |
| Videos | 28.1 | Screen recordings and videos | user-decision |
| .gemini | 5.7 | Gemini CLI data | app data |
| Documents | 5.3 | Almost all is `Documents\Zoom` (5.25 GB of Zoom local recordings) | user-decision |
| Desktop | 4.3 | Desktop | **protected** (size only) |
| .cache | 3.8 | Tool caches (covered by caches audit) | likely-safe-cache |
| .claude | 2.8 | Claude Code data | app data |
| Pictures | 1.5 | Screenshots 1.08, workshop 0.22, trip 0.17 | user-decision |

### 2a. AppData\Local - top 25

| Subfolder | Size GB | What it is | Category | Recoverable estimate |
|---|---:|---|---|---|
| Docker | 31.78 | `Docker\wsl` 31.74 = Docker Desktop WSL virtual disks | app data (covered by WSL/Docker audit) | see other audit |
| Google | 29.42 | `Chrome\User Data` 28.73 (**70 Chrome profiles**: e.g. Profile 2 1.91, Profile 12 1.39, Default 1.26, OptGuideOnDeviceModel 2.67, Snapshots 1.08), Cloud SDK 0.66 | **protected** (Chrome) | not proposed |
| Programs | 13.21 | Per-user apps: Python 6.06 (Python310 3.48, Python312 2.58), VS Code 1.05, Cursor 0.94, Antigravity IDE 0.9, Bionic 0.85, Windsurf 0.73, OpenCode 0.72, Trae 0.68, antigravity 0.47, Freebuff 0.4, Linear 0.39 | app data | several overlapping AI IDEs / Python versions - user decision |
| Temp | 8.14 | Temp files | likely-safe-cache (covered by temp audit) | see other audit |
| Microsoft | 4.76 | Edge 1.89 (**protected**), Olk (new Outlook) 0.88, WinGet 0.6, OneDrive 0.47, Copilot 0.26 | mixed | WinGet ~0.6 cache |
| wsl | 3.98 | WSL distro disk(s) | app data (covered by WSL audit) | see other audit |
| BraveSoftware | 2.88 | Brave browser (User Data 1.78) | app data (browser profile - treat as sensitive) | not proposed |
| Packages | 2.6 | Store apps: MSTeams 0.92, Windows Client CBS 0.36, Office Hub 0.33, OpenAI Codex 0.22 | app data | small |
| JxBrowser-x64 | 1.26 | Embedded Chromium runtime used by an app (likely JetBrains/Java tool) | likely-safe-cache | ~1 (re-downloaded on demand) |
| npm-cache | 1.0 | npm cache | likely-safe-cache (covered by caches audit) | ~1 |
| MongoDBCompass | 0.93 | MongoDB Compass app | app data | - |
| Postman-Agent | 0.93 | Postman Agent (old versions possible) | app data | partial |
| JetBrains | 0.91 | JetBrains IDE caches/indexes | likely-safe-cache | ~0.5-0.9 |
| Discord | 0.76 | Discord app | app data | - |
| OpenAI | 0.74 | OpenAI desktop/Codex data | app data | - |
| ms-playwright | 0.70 | Playwright browser binaries | likely-safe-cache | 0.7 (re-installable) |
| Postman | 0.55 | Postman app | app data | - |
| JxBrowser | 0.38 | Embedded Chromium runtime | likely-safe-cache | 0.38 |
| @codebufffreebuff-desktop-updater | 0.22 | Updater cache | likely-safe-cache | 0.22 |
| Pandoc | 0.22 | Pandoc install | app data | - |
| @lineardesktop-updater | 0.20 | Updater cache | likely-safe-cache | 0.20 |
| agy | 0.19 | Antigravity data | app data | - |
| ms-playwright-go | 0.18 | Playwright Go drivers | likely-safe-cache | 0.18 |
| Firefoo | 0.15 | Firefoo app | app data | - |
| antigravity-updater | 0.13 | Updater cache | likely-safe-cache | 0.13 |

### 2b. AppData\Roaming - top 25

| Subfolder | Size GB | What it is | Category |
|---|---:|---|---|
| Python | 8.41 | User site-packages: Python313 6.73, Python310 1.63 (pip --user installs, likely ML libs such as torch) | app data (user decision) |
| Code | 2.18 | VS Code user data / caches | app data |
| Antigravity IDE | 1.98 | IDE user data | app data |
| OnVUE | 1.22 | Pearson OnVUE exam app | app data (user decision if exam done) |
| Cursor | 1.00 | Cursor user data | app data |
| Zoom | 0.99 | Zoom client | app data |
| Postman | 0.55 | Postman data | app data |
| npm | 0.44 | Global npm packages | app data |
| ai.opencode.desktop | 0.22 | OpenCode | app data |
| pgadmin4 | 0.19 | pgAdmin | app data |
| discord | 0.13 | Discord | app data |
| Windsurf | 0.11 | Windsurf | app data |
| Freebuff, nltk_data, Microsoft, kingsoft, Linear, JetBrains, Wondershare, .anaconda, MongoDB Compass, Grammarly, Firefoo, MI, Docker Desktop | 0.01-0.09 each | misc | app data |

### 2c. AppData\LocalLow

| Subfolder | Size GB | Category |
|---|---:|---|
| Intel | 0.38 | app data (shader cache, likely-safe-cache) |
| Microsoft | 0.02 | app data |
| Temp, Ookla, 360MenuMgr | ~0 | - |

### 2d. Videos (28.1 GB) - user decision

| Item | Size GB | Modified | Note |
|---|---:|---|---|
| Screen Recordings\ (323 files) | 20.75 | 2026-11-05 | folder |
| - Screen Recording 2026-08-20 212929.mp4 | 7.68 | 2026-08-20 | |
| - Screen Recording 2026-11-05 230416.mp4 | 7.18 | 2026-11-05 | **same byte size (7,704,101,589) and timestamp as `Videos\wiseman guide.mp4`** - likely a duplicate copy (not a hard link). Verify with a hash before acting. |
| - Screen Recording 2026-03-05 213951.mp4 | 0.53 | 2026-03-05 | |
| - other 320 recordings | ~5.4 | various | |
| wiseman guide.mp4 | 7.18 | 2026-11-05 | possible duplicate of the above (~7.2 GB) |
| everything else | <0.1 | | |

### 2e. Documents (5.3 GB) - user decision

| Item | Size GB | Note |
|---|---:|---|
| Zoom\ | 5.25 | Zoom local meeting recordings |
| Database.kdbx | ~0 | KeePass password database - **protected (credentials)** |
| other docs | ~0 | resumes, reports |

## 3. Largest 40 individual files in C:\Users\SYAM

Browser profile folders (Chrome 28.73, Edge 1.89, Brave 1.78 GB) are excluded and shown only as totals above. Files under Downloads/Desktop are **protected** - listed for visibility only.

| # | GB | Modified | Path (under C:\Users\SYAM) | Category |
|---:|---:|---|---|---|
| 1 | 31.64 | 2026-11-07 | AppData\Local\Docker\wsl\disk\docker_data.vhdx | app data (Docker audit) |
| 2 | 7.68 | 2026-08-20 | Videos\Screen Recordings\Screen Recording 2026-08-20 212929.mp4 | user-decision |
| 3 | 7.18 | 2026-11-05 | Videos\wiseman guide.mp4 | user-decision (likely duplicate of #4) |
| 4 | 7.18 | 2026-11-05 | Videos\Screen Recordings\Screen Recording 2026-11-05 230416.mp4 | user-decision |
| 5 | 3.28 | 2025-12-04 | Downloads\mic projects\m-tech\divya madam2 - Copy - Copy.tar | protected |
| 6 | 3.10 | 2026-01-02 | Downloads\mic projects\sentiment analysys project working keerthi mam.tar | protected |
| 7 | 2.09 | 2026-11-07 | AppData\Local\wsl\{6fc1805c-...}\ext4.vhdx | app data (WSL audit) |
| 8 | 2.09 | 2026-01-02 | Desktop\confirence papers\machine learning projects\ggae-steganography vijayalakashmi mam.tar | protected |
| 9 | 2.03 | 2026-05-02 | Downloads\Telegram Desktop\Pacific_Rim_Uprising_2018_...mkv | protected |
| 10 | 1.89 | 2025-10-14 | AppData\Local\wsl\{84371609-...}\ext4.vhdx | app data (WSL audit) |
| 11 | 1.87 | 2026-07-25 | Downloads\Telegram Desktop\The_Gangster_the_Cop_the_Devil_2019...mkv | protected |
| 12 | 1.47 | 2026-09-21 | Downloads\dental_study-main\...\evaluation\_download\Dataset.zip | protected |
| 13 | 1.29 | 2026-10-03 | Downloads\mic projects\dentel project\dentel v2\dental-ai\.venv\...\torch_cuda.dll | protected (venv inside Downloads) |
| 14 | 1.27 | 2026-05-02 | Downloads\Telegram Desktop\DTMW_RAMPAGE_2018...mkv | protected |
| 15 | 0.92 | 2025-12-22 | AppData\Roaming\Python\Python310\site-packages\tensorflow\...\_pywrap_tensorflow_common.dll | app data |
| 16 | 0.89 | 2025-04-20 | AppData\Local\Programs\Python\Python310\Lib\site-packages\tensorflow\...\_pywrap_tensorflow_internal.pyd | app data |
| 17 | 0.74 | 2026-03-27 | Downloads\mic projects\SIH evaluation222\SIH evaluation222 - pavani.tar | protected |
| 18 | 0.66 | 2026-10-03 | Downloads\...\dental-ai\.venv\...\torch\lib\dnnl.lib | protected |
| 19 | 0.65 | 2026-11-03 | .claude\projects\d--company-website-tech-drona\b1dbf3b3-....jsonl | app data (single Claude Code session transcript) |
| 20 | 0.61 | 2025-04-20 | AppData\Local\Programs\Python\Python310\Lib\site-packages\torch\lib\dnnl.lib | app data |
| 21 | 0.61 | 2026-04-28 | AppData\Roaming\Python\Python313\site-packages\torch\~=b\dnnl.lib | likely-safe-cache: `~`-prefixed folder = leftover from an interrupted pip upgrade/uninstall |
| 22 | 0.61 | 2026-04-28 | AppData\Roaming\Python\Python313\site-packages\torch\~%b\dnnl.lib | likely-safe-cache: same pip leftover |
| 23 | 0.55 | 2026-11-01 | Downloads\Unconfirmed 864395.crdownload | protected (incomplete browser download) |
| 24 | 0.55 | 2026-10-03 | Downloads\...\dental-ai\.venv\...\cudnn_engines_precompiled64_9.dll | protected |
| 25 | 0.53 | 2026-03-05 | Videos\Screen Recordings\Screen Recording 2026-03-05 213951.mp4 | user-decision |
| 26 | 0.53 | 2026-03-05 | Downloads\mic projects\SIH evaluation222\demo video.mp4 | protected (same size as #25 - possible copy) |
| 27 | 0.53 | 2026-01-19 | Downloads\mic projects\poojitha IT  - Copy.tar | protected |
| 28 | 0.51 | 2026-10-03 | Downloads\...\dental-ai\.venv\...\cublasLt64_11.dll | protected |
| 29 | 0.50 | 2026-08-07 | .lmstudio\extensions\backends\llama.cpp-win-...-cuda-avx2-2.27.1\ggml-cuda.dll | app data (LM Studio) |
| 30 | 0.45 | 2026-11-06 | .cache\huggingface\hub\blobs\42\429ffc... | likely-safe-cache (HF model, caches audit) |
| 31 | 0.42 | 2026-10-13 | AppData\Roaming\Cursor\snapshots\codebases\955e5aba-...\staging\pack-....pack | likely-safe-cache (Cursor codebase snapshot) |
| 32 | 0.40 | 2026-09-21 | Downloads\mic projects\dentel project\dentel v1\Dental Dataset.v1i.yolov8-obb.zip | protected (3 copies of this zip exist in Downloads) |
| 33 | 0.40 | 2026-09-22 | Downloads\dental_study-main\...\dental_kaggle\dataset\Dental Dataset.v1i.yolov8-obb.zip | protected |
| 34 | 0.40 | 2026-09-21 | Downloads\dental_study-main\...\_quarantine_2026-09-24\...\Dental Dataset.v1i.yolov8-obb.zip | protected |
| 35 | 0.36 | 2026-01-22 | Downloads\mic projects\GEC Projects\sentiment analysys updated new12.tar | protected |
| 36 | 0.35 | 2026-09-09 | .cache\huggingface\hub\models--prithivMLmods--tooth-agenesis-siglip2\blobs\... | likely-safe-cache |
| 37 | 0.34 | 2026-11-06 | AppData\Local\OpenAI\Codex\bin\...\codex.exe | app data |
| 38 | 0.34 | 2026-11-06 | .codex\plugins\.plugin-appserver\codex.exe | app data (second copy of codex.exe) |
| 39 | 0.32 | 2026-10-15 | AppData\Roaming\OnVUE\browser-lock.zip | app data |
| 40 | 0.32 | 2026-11-04 | .antigravity-ide\extensions\anthropic.claude-code-2.1.318-win32-x64\...\claude.exe | app data |

Note: the Python 3.13 user site-packages contains `torch\~=b` and `torch\~%b` folders (pip's renamed-old-version temp folders from an interrupted install). These are worth checking in the caches audit - potentially ~1-2 GB of dead torch files.

## 4. Installed applications (registry Uninstall keys, top 45 by EstimatedSize)

EstimatedSize is vendor-reported and often understated; 223 entries total. No "last used" data is available from the registry, so InstallDate is shown.

| App | GB | InstallDate | Location |
|---|---:|---|---|
| Docker Desktop | 3.30 | - | C:\Program Files\Docker\Docker |
| Windows SDK 10.0.26100.7705 | 2.26 | - | |
| Bionic 1.0.6+5 | 2.09 | - | |
| Copilot | 2.08 | 2026-11-02 | Program Files (x86)\Microsoft\Copilot |
| Microsoft Edge | 2.08 | 2026-11-01 | Program Files (x86)\Microsoft\Edge |
| Microsoft Edge WebView2 Runtime | 2.07 | 2026-11-02 | (system dependency - keep) |
| Cursor (User) | 1.25 | 2026-10-13 | AppData\Local\Programs\cursor |
| Windows Subsystem for Linux | 1.14 | 2026-10-13 | |
| Cursor (machine-wide) | 1.04 | 2026-07-08 | C:\Program Files\cursor - **second Cursor install** |
| PostgreSQL 18 | 1.04 | 2026-04-13 | |
| VS Code (User) | 0.97 | 2026-10-15 | |
| Windsurf (User) | 0.90 | 2026-05-07 | |
| Antigravity IDE (User) | 0.89 | 2026-11-02 | |
| Trae (User) | 0.83 | 2026-04-14 | |
| Linear 1.31.0 | 0.78 | - | |
| OpenCode 2.0.29 | 0.72 | - | |
| MySQL Shell 8.0 | 0.57 | 2025-02-25 | |
| Brave | 0.53 | 2026-11-06 | |
| MySQL Server 8.0 | 0.53 | 2025-02-25 | |
| Photos | 0.52 | - | |
| Microsoft OneDrive | 0.52 | - | |
| Voicebox | 0.52 | 2026-08-08 | |
| Google Chrome | 0.50 | 2026-11-03 | |
| Antigravity 2.2.1 | 0.49 | - | (also a separate "Antigravity IDE") |
| OfferGoose 1.1.8 | 0.48 | - | |
| Freebuff 0.0.71 | 0.40 | - | |
| AI-Navigator 0.8.3 | 0.37 | - | |
| Universal CRT Headers/Sources | 0.35 | 2026-08-08 | |
| Git | 0.34 | 2025-12-13 | |
| Java SE JDK 21.0.8 | 0.31 | 2025-10-15 | |
| Windows SDK Store Apps Headers | 0.25 | 2026-08-08 | |
| SQL Server 2019 LocalDB | 0.25 | 2024-11-23 | |
| Pandoc 3.8.3 | 0.22 | 2026-01-19 | |
| Windows SDK Store Apps Tools | 0.22 | 2026-08-08 | |
| .NET Desktop Runtime 8.0.33 | 0.21 | - | |
| qBittorrent | 0.20 | - | |
| AWS CLI v2 | 0.17 | 2025-03-28 | |
| Postman x64 12.22.8 | 0.16 | 2026-08-07 | |
| MySQL Workbench 8.0 CE | 0.16 | 2025-02-25 | |
| MongoDB Compass | 0.16 | 2026-06-15 | |
| Windows SDK Store Apps Libs | 0.16 | 2026-08-08 | |
| Python 3.13.7 | 0.16 | - | |
| Python 3.12.8 | 0.15 | - | |
| Quick Share | 0.14 | 2026-09-03 | |
| Postman Agent 0.4.87 | 0.13 | 2026-04-04 | |

Not in registry but large on disk: Microsoft Office 4.03 (Program Files), JetBrains 3.14 (Program Files), Visual Studio 2.69, Flutter SDK 3.2 (C:\flutter), Python 3.10 (3.48 in Local\Programs + 1.63 Roaming site-packages).

Observations (user decision, not instructions): many overlapping AI IDEs/editors (Cursor x2, VS Code, Windsurf, Trae, Antigravity + Antigravity IDE, OpenCode, Freebuff, Bionic) total ~8-9 GB including their Roaming data; three Python versions (3.10, 3.12, 3.13) plus C:\Python313 total ~15 GB with user site-packages; two database servers (PostgreSQL 18, MySQL 8) plus SQL LocalDB.

## 5. Windows-level reclaimables (information only)

| Item | Path | Size GB | Category | Note |
|---|---|---:|---|---|
| Hibernation file | C:\hiberfil.sys | 0 (absent) | system | Hibernate not available (Modern Standby) |
| Windows.old | C:\Windows.old | 0 (absent) | system | |
| Windows Update download cache | C:\Windows\SoftwareDistribution\Download | 0.00 | likely-safe-cache | already empty (whole SoftwareDistribution 0.06) |
| Delivery Optimization cache | NetworkService\...\DeliveryOptimization | access denied; `Get-DeliveryOptimizationPerfSnap` reports cache 0 bytes | likely-safe-cache | ~0 |
| Memory dumps | C:\Windows\Minidump, C:\Windows\MEMORY.DMP | 0 / not present (non-admin view) | likely-safe-cache | ~0 |
| Live kernel reports | C:\Windows\LiveKernelReports | 0 (non-admin view) | likely-safe-cache | verify elevated |
| User crash dumps | AppData\Local\CrashDumps | 0.00 | likely-safe-cache | |
| Windows Error Reporting | C:\ProgramData\Microsoft\Windows\WER | 0.00 | likely-safe-cache | |
| C:\Windows\Temp | | 0 (non-admin view) | likely-safe-cache | verify elevated |
| Windows Installer cache | C:\Windows\Installer | 3.51 | system | do NOT delete manually; only orphaned patches via official tooling |
| Package Cache (VS / SDK installers) | C:\ProgramData\Package Cache | 0.60 | system/app | needed for repair/uninstall; not recommended |
| Component store | C:\Windows\WinSxS | 18.32 (hard-link inflated) | system | `DISM /Online /Cleanup-Image /StartComponentCleanup` typically frees 0.5-3 GB |
| DriverStore | C:\Windows\System32\DriverStore | 5.21 | system | old driver packages; Disk Cleanup "Device driver packages" may free some |
| Windows logs | C:\Windows\Logs | 0.11 | likely-safe-cache | small |
| Page file | C:\pagefile.sys | 20.52 | system | system-managed; capping it (e.g. 8-12 GB) could free ~8-12 GB but affects stability under memory pressure - user decision |
| Shadow copies / restore points | System Volume Information | unknown (needs admin) | system | check `vssadmin list shadowstorage` elevated |

Windows-level conclusion: Windows itself is clean (no Windows.old, no hiberfil, update cache empty). Realistic Windows-side gain without touching settings is only ~1-3 GB (component cleanup); the only large system lever is the 20.5 GB page file, which is a user decision.

## 6. Summary - top consumers and best candidates

| # | Item | GB | Category |
|---|---|---:|---|
| 1 | Downloads | 47.2 | protected |
| 2 | Docker Desktop WSL disks (AppData\Local\Docker\wsl) | 31.7 | app data - other audit |
| 3 | Chrome User Data (70 profiles) | 28.7 | protected |
| 4 | Videos (Screen Recordings 20.8 + wiseman guide 7.2) | 28.1 | user-decision |
| 5 | pagefile.sys | 20.5 | system |
| 6 | WinSxS (inflated) | 18.3 | system |
| 7 | Python (Local\Programs 6.1 + Roaming 8.4 + C:\Python313 0.15) | 14.6 | app data |
| 8 | Temp (AppData\Local\Temp) | 8.1 | likely-safe-cache - other audit |
| 9 | .gemini | 5.7 | app data |
| 10 | Documents\Zoom recordings | 5.3 | user-decision |
| 11 | DriverStore | 5.2 | system |
| 12 | Desktop | 4.3 | protected |
| 13 | Microsoft Office | 4.0 | app data |
| 14 | AppData\Local\wsl | 4.0 | app data - other audit |
| 15 | Docker Desktop program files | 3.9 | app data |

Best candidates (all require the user's explicit choice; nothing has been touched):
1. Likely duplicate 7.2 GB video (`Videos\wiseman guide.mp4` vs `Videos\Screen Recordings\Screen Recording 2026-11-05 230416.mp4`) - user decision, verify hash first; moving Videos/Zoom recordings (~33 GB) to D: is the largest non-destructive option.
2. Docker WSL disk compaction/prune and Temp/npm caches - see the other two audits (~30+ GB potential).
3. Unused dev tools: duplicate Cursor install, unused AI IDEs, Python 3.10 (~5 GB incl. site-packages), Flutter SDK 3.2, OnVUE 1.2 - user decision via proper uninstall.
4. Regenerable caches: JxBrowser runtimes 1.6, ms-playwright 0.9, JetBrains caches ~0.9, updater caches ~0.55, WinGet cache 0.6, Intel shader cache 0.38 (~4-5 GB).
5. Windows component cleanup (DISM) ~1-3 GB; page file capping is optional (~8-12 GB) and a user decision.
