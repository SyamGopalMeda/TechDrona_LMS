# 03 – Temp files and caches on C: (read-only audit)

Measured 2026-11-07. Nothing was deleted or changed. C: had 8.38 GB free (360.7 GB used); D: had 7.48 GB free.
Sizes are recursive file totals. The shell was **not elevated**, so C:\Windows\Temp, C:\Windows\Prefetch and Delivery Optimization show 0 or MISSING. Re-measure them from an admin shell, or use Settings > System > Storage > Temporary files.

Classification legend:
- **safe** — disposable cache. It rebuilds by itself or is never needed again.
- **safe-slow** — safe to delete, but rebuilding takes a re-download or re-index.
- **not-safe** — app state or config, installer store, or something a project needs. Do not delete.

Run every clean command with the owning app closed.

## Summary

| Bucket | GB |
|---|---|
| safe (total) | **~7.8** |
| safe-slow (total) | **~3.6** |
| Docker WSL disk (needs review first, see below) | up to ~31.6 |
| not-safe (reported for context only) | ~22+ |

## Detail table

| Path | Size GB | Files / newest | What | Classification | How to clean safely | Rebuild impact |
|---|---|---|---|---|---|---|
| `%LOCALAPPDATA%\Temp` (total) | 8.13 | 99,216 / today | User temp | mixed (see rows below) | — | — |
| `%TEMP%\claude\**` | 5.42 | 85,569 / today | Active Claude Code session state | **not-safe (excluded)** | Do not touch | — |
| `%TEMP%` excluding `claude`, files **older than 24 h** | **2.44** | 13,377 | Everything below combined | safe | `Get-ChildItem $env:TEMP -Force \| ? { $_.Name -ne 'claude' } \| Get-ChildItem -Recurse -File -Force -EA 0 \| ? LastWriteTime -lt (Get-Date).AddHours(-24) \| Remove-Item -Force -EA 0` (locked files are skipped). Or use Storage Sense > Temporary files. | None |
| `%TEMP%\y1rery5b` | 0.94 | 289 / 2026-11-03 | Leftover Visual Studio installer payload extraction | safe | Included in the command above | None |
| `%TEMP%\puppeteer_dev_chrome_profile-*` (18 dirs) | 0.65 | 5,256 / 2026-11-04 | Throwaway Puppeteer/Chrome profiles from test runs. Not the real Chrome profile. | safe | Included above | None |
| `%TEMP%\DiagOutputDir` | 0.34 | 28 / today | Remote Desktop client auto-trace (RdClientAutoTrace) | safe once older than 24 h | Included above | None |
| `%TEMP%\scoped_dir*` (99 dirs) | 0.17 | 2026-11-03 | Chromedriver scratch dirs | safe | Included above | None |
| `%TEMP%\{GUID}\swap.vhdx` (6) | 0.24 (0.20 older than 24 h) | — | WSL/Docker utility-VM swap files from past sessions. WSL is running now, so the current one is locked. | safe if older than 24 h and unlocked | Included above. The locked file fails harmlessly. | None |
| `%TEMP%\*.tmp` loose | 0.21 | 372 | Misc tmp files | safe | Included above | None |
| `%TEMP%\node-compile-cache` | 0.03 | 5,395 / today | Node V8 compile cache | safe | Included above | Slightly slower first Node start |
| `C:\Windows\Temp` | 0 (no admin access) | — | System temp | safe | Admin: Storage Sense or `cleanmgr /sagerun` | None |
| `C:\Windows\Prefetch` | 0 (no admin access) | — | App-launch prefetch | safe, but little benefit (usually under 100 MB) | Leave alone | Slower app launches until it rebuilds |
| `%LOCALAPPDATA%\CrashDumps` | 0.00 | 0 | User crash dumps | safe | — | — |
| `C:\ProgramData\Microsoft\Windows\WER` | 0.00 | 1 / 2026-11-03 | Error reports | safe | Storage Sense > Windows error reports | None |
| Delivery Optimization cache | n/a (needs admin) | — | Windows Update peer cache | safe | Settings > Storage > Temporary files > Delivery Optimization Files, or admin `Delete-DeliveryOptimizationCache -Force` | None |
| `C:\Windows\SoftwareDistribution\Download` | 0.00 | 4 / today | WU download | safe | — | — |
| `%LOCALAPPDATA%\Microsoft\Windows\Explorer` (thumbcache/iconcache) | 0.03 | 32 | Thumbnail cache | safe, negligible | Disk Cleanup > Thumbnails | Thumbnails regenerate |
| `C:\$Recycle.Bin` | 0.00 | 12 | Recycle bin | safe | `Clear-RecycleBin -DriveLetter C -Force` | None (gone for good) |
| `%LOCALAPPDATA%\npm-cache` | **1.00** | 4,119 / today | npm tarball cache | safe | `npm cache clean --force` | Next installs re-download |
| `%USERPROFILE%\.bun\install\cache` | **1.85** | 91,265 / 2026-10-09 | Bun package cache | safe | `bun pm cache rm` | Next `bun install` re-downloads |
| `%LOCALAPPDATA%\pip\cache` | 0.11 | 220 / 2026-11-06 | pip wheels/http | safe | `pip cache purge` | Re-download on install |
| pnpm / yarn / uv / poetry caches | — | MISSING | Not present | — | — | — |
| `%USERPROFILE%\.cache` (total) | 3.83 | 22,568 | Mixed | see below | — | — |
| `.cache\codex-runtimes\codex-primary-runtime.previous-*` (8 dirs) | **0.88** | 2026-10-22 to 2026-11-06 | Old Codex runtime versions kept after upgrades | safe (close Codex first) | `Remove-Item "$HOME\.cache\codex-runtimes\codex-primary-runtime.previous-*" -Recurse -Force` | None. The current runtime is kept. |
| `.cache\codex-runtimes\codex-primary-runtime` | 1.35 | 2026-11-06 | Current Codex runtime | not-safe (in use) | — | — |
| `.cache\huggingface\hub` | 1.47 | 105 / 2026-11-06 | Models: Kokoro-82M 0.31, whisper-base 0.27, siglip2 0.35, MiniLM 0.09, loose blobs 0.45 | safe-slow | `hf cache delete` (interactive), or `huggingface-cli delete-cache` | Models re-download on next use |
| `.cache\firebase` | 0.13 | 1 | Firebase CLI emulator jar | safe-slow | Delete the file | Re-downloaded when the emulator starts |
| `.cache\chroma, gdown, graphiti, opencode, tooling, chrome-devtools-mcp` | about 0 | — | Tiny | ignore | — | — |
| `%LOCALAPPDATA%\ms-playwright\chromium-1248` + `chromium_headless_shell-1248` + ffmpeg/winldd | 0.70 | 605 / 2026-11-03 | Playwright browsers. `apps/web` (`@playwright/test ^1.56`) pins chromium **1248**. | **not-safe – needed by project** | Keep. No stale versions exist. | Re-download about 0.7 GB, and e2e breaks offline |
| `%USERPROFILE%\.cargo\registry` | 0.70 | 20,155 / 2026-08-08 | Rust crate cache | safe-slow | `cargo cache -a` (needs cargo-cache), or delete `registry\cache` and `registry\src` | Crates re-download |
| `%USERPROFILE%\.rustup` | 0.57 | 155 | Rust toolchains | not-safe (installed toolchain) | `rustup toolchain list` and remove unused toolchains only | — |
| `%USERPROFILE%\.m2` | 0.52 | 6,918 / 2026-09-15 | Maven repository | safe-slow | Delete `.m2\repository` (keep `settings.xml`) | Maven re-downloads dependencies |
| `%USERPROFILE%\.gradle` | 0.17 | 321 / 2026-10-16 | Gradle caches | safe-slow | `Remove-Item $HOME\.gradle\caches -Recurse -Force` (keep `gradle.properties`) | Re-download |
| NuGet / Go build / Go mod | — | MISSING | — | — | — | — |
| `%APPDATA%\Code\CachedExtensionVSIXs` | **0.61** | 33 / 2026-11-02 | Copies of downloaded VS Code extension installers | safe | Close VS Code, then `Remove-Item "$env:APPDATA\Code\CachedExtensionVSIXs\*" -Recurse -Force` | None |
| `%APPDATA%\Code\CachedData` | 0.11 | 208 | V8 cache for old and current VS Code builds | safe | Close VS Code, then delete the contents | Slightly slower first start |
| `%APPDATA%\Code\{Cache, Code Cache, GPUCache, logs}` | 0.02 | — | Electron caches and logs | safe | Close VS Code, then delete the contents | None |
| `%APPDATA%\Cursor\{CachedData, logs, Cache, Code Cache}` | 0.07 | 2026-10-13 | Cursor caches | safe | Close Cursor, then delete the contents | None |
| `%USERPROFILE%\.vscode\extensions` / `.cursor\extensions` | 1.62 / 1.32 | — | Installed extensions | not-safe | Uninstall unused extensions in the IDE | — |
| `%LOCALAPPDATA%\JetBrains\IdeaIC2025.1\log` | 0.12 | — | IDE logs | safe | Delete the contents | None |
| `%LOCALAPPDATA%\JetBrains\IdeaIC2025.1\{caches, index}` | 0.59 | 2026-09-18 | IntelliJ caches/indexes | safe-slow | IDE: File > Invalidate Caches. If IDEA CE 2025.1 is no longer used, uninstall it instead. | Re-index on next open |
| Teams `...\MSTeams_8wekyb3d8bbwe\LocalCache\...\EBWebView\WV2Profile_*\{Cache, Code Cache, Service Worker}` | 0.54 | today | Teams WebView caches only | safe (quit Teams first) | Delete only the `Cache`, `Code Cache` and `GPUCache` folders inside each `WV2Profile_*`. Do not delete the other folders (they hold sign-in data). | Teams reloads its UI assets |
| `%APPDATA%\discord\{Cache, Code Cache, GPUCache}` | 0.05 | 2026-08-08 | Discord caches | safe | Quit Discord, then delete those 3 folders | None |
| Slack caches | — | MISSING | — | — | — | — |
| `%LOCALAPPDATA%\Docker\log` | 0.04 | 64 / today | Docker Desktop logs | safe | Docker Desktop > Troubleshoot > Clean/Purge data is too broad. Instead, quit Docker and delete old `*.log` files. | None |
| `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx` | **31.64** | today | Docker Desktop WSL disk: images, build cache, containers, **volumes** | **review first** (may contain DB volumes) | 1) `docker system df -v`. 2) `docker builder prune -a` and `docker image prune -a` (do **not** add `--volumes` unless no volume holds data you need). 3) The VHDX does not shrink by itself: quit Docker, run `wsl --shutdown`, then compact it (admin `Optimize-VHD -Path <vhdx> -Mode Full` with Hyper-V, or diskpart `select vdisk file=<vhdx>` / `compact vdisk`). Or move it to D: via Docker Settings > Resources > Disk image location. | Images re-pull and the build cache rebuilds |
| `%LOCALAPPDATA%\node-gyp` | 0.05 | 2,369 / 2026-02-17 | Node headers | safe-slow | Delete | Re-downloaded at the next native build |
| `%LOCALAPPDATA%\Microsoft\TypeScript` | 0.08 | 12,605 | VS Code ATA type cache | safe-slow | Delete | Re-downloads types |
| winget `DesktopAppInstaller\LocalState`, `%TEMP%\WinGet` | about 0 | — | — | ignore | — | — |
| Chocolatey lib-bad/temp | — | MISSING | — | — | — | — |
| `%LOCALAPPDATA%\Package Cache` | 0.05 | 25 | Per-user Burn installer cache | not-safe (repair/uninstall) | — | — |
| `C:\ProgramData\Package Cache` | 0.60 | 287 | Burn/VS installer cache | **not-safe** (needed for repair/uninstall) | — | — |
| `C:\Windows\Installer` | 3.51 | 515 | MSI/MSP store | **not-safe** | Never delete manually | Breaks uninstall/patching |
| `%LOCALAPPDATA%\Programs\Python` | 6.06 | 149,323 | Installed Python interpreters and site-packages | not-safe (installed software) | Uninstall unused Python versions through Apps & features | — |
| `%USERPROFILE%\.gemini` | 5.73 | 22,585 / today | Gemini/Antigravity config and state (including `antigravity-ide\browser_recordings` 2.83 GB and `brain` 1.50 GB) | **not-safe – app config/state** | If the recordings are unwanted, remove them from within Antigravity | — |
| `%USERPROFILE%\.claude` | 2.79 | 4,292 / today | Claude Code config and session history (`projects` 2.74 GB) | **not-safe – app config/state** | — | — |

## Explicitly excluded (protected, not measured)
- Chrome and Edge profiles, caches, cookies and sessions.
- Credential Manager, `%APPDATA%\Microsoft\Protect`, Vault, and any credential or keychain stores.
- Desktop, Downloads, `.ssh`, `.gnupg`, `.aws`, `.azure`, `.config`.
- `%TEMP%\claude`, and any file modified in the last 24 h or locked by a running process.

## Suggested order (largest safe wins first)
1. `%TEMP%` files older than 24 h, excluding `claude` (2.44 GB)
2. Bun cache (1.85)
3. npm cache (1.00)
4. Old codex-runtime versions (0.88)
5. VS Code CachedExtensionVSIXs and CachedData (0.72)
6. Teams WebView caches (0.54)
7. Smaller safe items (about 0.4 GB in total)

Then decide on Docker (`docker system df` first) and the Hugging Face models.
