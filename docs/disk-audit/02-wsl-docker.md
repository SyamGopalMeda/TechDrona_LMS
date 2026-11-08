# 02 - WSL and Docker storage audit (read-only)

Date: 2026-11-07. Nothing was deleted, pruned, stopped, compacted or restarted.

Drive state: **C: 360.7 GB used / 8.4 GB free** (fluctuating near 0), **D: 98 GB used / 7.5 GB free**.

## 1. WSL virtual disks (all on C:)

| Distro | State | VHDX path | Size on C: | LastWriteTime |
|---|---|---|---|---|
| docker-desktop (data) | Running | `C:\Users\SYAM\AppData\Local\Docker\wsl\disk\docker_data.vhdx` | **31.64 GB** | 2026-11-07 11:52 |
| docker-desktop (system) | Running | `C:\Users\SYAM\AppData\Local\Docker\wsl\main\ext4.vhdx` | 0.10 GB | 2026-11-06 14:25 |
| kali-linux | Running | `C:\Users\SYAM\AppData\Local\wsl\{6fc1805c-2fbd-4bf4-876f-d6c625d98885}\ext4.vhdx` | 2.09 GB | 2026-11-07 14:17 (in use) |
| Ubuntu | Stopped | `C:\Users\SYAM\AppData\Local\wsl\{84371609-f7dc-4210-9788-8f9f166ff946}\ext4.vhdx` | 1.89 GB | **2025-10-14** (unused ~13 months) |

Total WSL/Docker footprint on C: ~**35.7 GB**. `%LOCALAPPDATA%\Docker` total = 31.8 GB.

- No `%LOCALAPPDATA%\Packages\*Canonical*/*Kali*\LocalState` vhdx: both distros were installed via the new `wsl --install` layout (`%LOCALAPPDATA%\wsl\{GUID}`).
- `%APPDATA%\Docker\settings-store.json` has **no** `dataFolder`/`customWslDistroDir`/`diskSizeMiB` override -> defaults (disk image on C:, 1 TB virtual max). `UseContainerdSnapshotter: true`.
- `docker_data.vhdx` is **not sparse** (`fsutil sparse queryflag`). No `%USERPROFILE%\.wslconfig` (so no `sparseVhd=true`, no autoMemoryReclaim).
- Inside the VM the data disk (`/dev/sde`, mounted `/mnt/docker-desktop-disk`) reports **34.8 GB used** of 1006.9 GB virtual -> the vhdx is essentially full of live data; there is little "slack" to reclaim by compaction alone.

## 2. Distro usage

- **kali-linux**: running, vhdx written today -> in use (2 GB, small).
- **Ubuntu**: stopped, last written 2025-10-14 -> looks abandoned. Candidate for `wsl --export` (to another drive) + `wsl --unregister` **only if the user confirms nothing is needed inside** (frees 1.9 GB). Not started during this audit.
- **docker-desktop**: running but degraded (see section 6).

## 3. Docker resources

Daemon responds partly; `docker system df` and `docker ps -s` fail with
`snapshotter.Usage failed ... snapshots/480/fs: input/output error`. Sizes below come from `docker images` and from `du` inside the docker-desktop distro.

### Containers

| Project | Containers | State |
|---|---|---|
| **techdrona (KEEP)** | web, api, api-webhooks, worker, worker-judge, worker-maintenance, scheduler, audit-sealer, postgres, redis, redis-queue, s3 (seaweedfs), mailpit | Up (reported) |
| **techdrona (KEEP)** | migrate-1 (image `b899622d09ba`), s3-init-1 (aws-cli) | Exited 0 (one-shot jobs) |
| enterpriseaiknowledgeplatform | ea_platform_db (postgres:15), ea_platform_redis (redis:7), ea_platform_chromadb | Up 24 h |
| godavaripushkaralutrail4 | web-1, api-1, db-1 (postgres:16-alpine) | Exited (255) 6 days ago |
| student-security-system | student-security-system-postgres-1, student-db (both postgres:15-alpine) | Exited (255) 5 months ago |

### Images (21 tagged, 0 dangling)

| Image | Size | Owner | Verdict |
|---|---|---|---|
| techdrona/td-api:local | 600 MB | techdrona | **KEEP** |
| techdrona/td-web:local | 365 MB | techdrona | **KEEP** |
| techdrona/postgres-local:16 | 676 MB | techdrona | **KEEP** |
| redis:7.4-bookworm | 170 MB | techdrona | **KEEP** |
| chrislusf/seaweedfs:3.80 | 181 MB | techdrona (s3) | **KEEP** |
| axllent/mailpit:v1.27 | 51 MB | techdrona | **KEEP** |
| amazon/aws-cli:2.22.35 | 599 MB | techdrona (s3-init) | **KEEP** |
| rhysd/actionlint, hashicorp/terraform:1.9.8, grafana/k6:0.54.0, koalaman/shellcheck, hadolint/hadolint | ~384 MB total | techdrona Makefile/compose tooling | KEEP (re-pullable) |
| dental-ai-cloudrun:local | **2.44 GB** | other project, 4 weeks old | candidate |
| chromadb/chroma:latest | 826 MB | enterpriseai (running) | user decision |
| postgres:15 / redis:7 | 633 / 170 MB | enterpriseai (running) | user decision |
| pushkar-render:latest | 326 MB | godavari, 6 days | candidate |
| godavaripushkaralutrail4-api / -web | 325 / 75 MB | godavari (exited) | candidate |
| postgres:16-alpine | 420 MB | godavari db | candidate |
| postgres:15-alpine | 392 MB | student-security-system (5 months) | candidate |

Image list total ~9.1 GB (shared layers make real usage lower; containerd store `desktop-containerd` measured 5.8 GB, plus `docker/rootfs` 2.3 GB).

### Build cache
`docker buildx du`: **21.09 GB total, all reclaimable** (16.57 GB private, 4.52 GB shared). Largest single record 1.84 GB (4 weeks old). **This is the biggest safe win** - `docker builder prune` does not touch images, containers or volumes. (Note: on-disk `du` of buildkit could not see all of it because of the I/O errors; buildx's own accounting is the authoritative figure.)

### Volumes (du inside docker-desktop)

| Volume | Size | Verdict |
|---|---|---|
| techdrona_pgdata | **2.3 GB** | **KEEP** (contains dev DB + test DBs) |
| techdrona_s3-data | **5.3 GB** | **KEEP** (may contain test buckets - review inside app, not via Docker) |
| techdrona_redis-queue-data | 32 MB | KEEP |
| techdrona_redis-cache-data, techdrona_mailpit-data | ~0 | KEEP |
| enterpriseaiknowledgeplatform_postgres_data_new | 46 MB | user decision (running) |
| enterpriseaiknowledgeplatform_postgres_data / _chromadb_data | ~0 reported | user decision |
| godavaripushkaralutrail4_pgdata / _uploads | ~0 reported | candidate |
| student-security-system_postgres_data | ~0 reported | candidate |
| 4 anonymous volumes (248f.., 355c.., 4ac3.., d1b4..) | ~0 each | candidates (`docker volume prune` for unattached anonymous only) |

"~0 reported" volumes may be under-reported: `du` hit EXT4 read errors on some directories.

## 4. techdrona Postgres test databases

Postgres is **not reachable**: host port 15432 times out, `docker exec techdrona-postgres-1` returns "container is not running" even though `docker ps` says "Up (healthy)" (daemon state is stale; its log file cannot be opened - read-only FS). Port 5432 belongs to another Postgres (ea_platform_db) - auth failed, not touched further.

Fallback from the filesystem: `techdrona_pgdata/_data/base` holds **112 database directories**, **2.26 GB total**, each 21-29 MB (template DBs + dev `techdrona` + ~100 throwaway `techdrona_*` DBs). So dropping all throwaway test DBs would free roughly **2.0-2.2 GB inside the vhdx**. Names could not be mapped to OIDs without a live server. Rerun once Postgres is healthy:

```sql
SELECT datname, pg_size_pretty(pg_database_size(datname))
FROM pg_database WHERE datname LIKE 'techdrona%' ORDER BY pg_database_size(datname) DESC;
```
Keep `techdrona` (dev). Drop candidates: `techdrona_feat_*`, `techdrona_ws*`, `techdrona_audit_*`, `techdrona_fix_*`, `techdrona_review_*`, `techdrona_final_*` (and `techdrona_test` if the suite recreates it).

## 5. Key caveat: deleting inside a VHDX does not shrink it on C:

`docker_data.vhdx` is a dynamically expanding, non-sparse VHDX. Pruning images/cache/volumes or dropping DBs frees blocks *inside* ext4 but the file on C: stays 31.6 GB. To return the space to Windows you must compact it afterwards:

1. Free space inside Docker first (build cache prune, unused images, test DBs).
2. Quit Docker Desktop, then `wsl --shutdown` (this also stops kali-linux).
3. Compact: `Optimize-VHD -Path ...\docker_data.vhdx -Mode Full` (needs Hyper-V module, not available on Windows Home), **or** `diskpart` -> `select vdisk file="...\docker_data.vhdx"` -> `attach vdisk readonly` -> `compact vdisk` -> `detach vdisk`. Alternatively Docker Desktop > Troubleshoot > "Clean / Purge data" (destroys ALL images, containers and volumes, including techdrona - not recommended).
4. Long-term: `.wslconfig` `[experimental] sparseVhd=true` and/or `wsl --manage docker-desktop --set-sparse true` (Docker Desktop newer versions do this) so freed space returns automatically.

Estimated recovery after prune + compaction: build cache ~16-21 GB + other-project images ~3-5 GB + test DBs ~2 GB = **~20-27 GB** of the 31.6 GB file. Compaction itself needs a little free space on C: (diskpart works in place, but get at least a few GB free first).

Moving the disk image to D:: possible via Docker Desktop > Settings > Resources > Advanced > "Disk image location" (Docker copies the vhdx). But D: has only **7.5 GB free**, so it is only feasible *after* pruning + compacting to well under ~6 GB, which is unrealistic while techdrona volumes alone are ~7.7 GB. Not recommended now.

## 6. Warning: the Docker data disk is returning I/O errors

`dmesg` in docker-desktop shows `I/O error, dev sde ... EXT4-fs warning ... error -5 reading directory block`, and the snapshotter reports I/O errors on snapshot 480. Cause is almost certainly the host volume filling up while the VHDX was expanding. Data may be partially damaged. Before any destructive Docker/WSL action:
- Free space on C: by other means first (other audit sections), so the VHDX can grow and writes succeed.
- Then restart Docker Desktop once, confirm `techdrona-postgres-1` is healthy, and take a `pg_dump -Fc techdrona` to D: (dev DB is ~25 MB - fits easily).
- Only after a good backup: prune/compact.

## Recommended safe sequence

1. Free a few GB on C: from non-WSL sources (temp, caches, other audit items).
2. Restart Docker Desktop; verify techdrona stack is healthy; `pg_dump` the dev DB `techdrona` to D:.
3. `docker builder prune -a` (~21 GB; touches no images/volumes).
4. Drop throwaway `techdrona_*` test DBs (keep `techdrona`) (~2 GB).
5. With user approval: remove other-project containers/images (dental-ai-cloudrun 2.4 GB, godavari, student-security-system, pushkar-render) and their volumes; `docker volume prune` for anonymous volumes.
6. Quit Docker Desktop, `wsl --shutdown`, compact `docker_data.vhdx` with diskpart; optionally enable sparse VHD.
7. Optional: export + unregister the stale Ubuntu distro (1.9 GB) if the user confirms.

**Keep list (techdrona):** images td-api, td-web, postgres-local:16, redis:7.4-bookworm, seaweedfs:3.80, mailpit:v1.27, aws-cli:2.22.35, migrate image b899622d09ba, lint/tool images; volumes techdrona_pgdata, techdrona_s3-data, techdrona_redis-*, techdrona_mailpit-data; all `techdrona-*` containers; DB `techdrona`.
