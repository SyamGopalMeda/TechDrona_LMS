#!/usr/bin/env bash
# Tech Drona LMS GCP demo — helper run ON THE VM as root (sudo bash vm.sh <cmd>).
#   build   build postgres, td-api and td-web images on the VM
#   up      start / update the whole stack (runs migrations first)
#   seed    load the DEV/DEMO seeds (APP_ENV=dev for this one-off container only)
#   rotate  replace the public seed passwords/TOTP secrets; prints new credentials as JSON
#           on stdout (capture it on your PC, never store it on the VM)
#   otp <email>  newest code/link mailed to <email> (mail stays on the VM, Mailpit internal)
#   portal-import <file.db>  load a College Data Portal SQLite DB into its volume (stops/starts it)
#   portal-backup            consistent copy of the College Data Portal DB to /opt/techdrona/backups/
#   ps | logs [svc] | down
set -euo pipefail
# Absolute paths BEFORE cd: arguments may be relative to the caller's directory.
SELF="$(realpath "$0")"
ARG2_ABS="$( [ -n "${2:-}" ] && realpath -m -- "$2" 2>/dev/null || true)"
cd "$(dirname "$SELF")"
ENV=/opt/techdrona/server.env
DC=(docker compose -p techdrona --env-file "$ENV")
SRC=/opt/techdrona/src
case "${1:-}" in
  build) "${DC[@]}" build postgres migrate && "${DC[@]}" build college-portal web ;;
  up) "${DC[@]}" up -d --remove-orphans ;;
  seed)
    RUNNER='import runpy, sys; from app.core.models_registry import import_all_models; import_all_models(); m = sys.argv[1]; sys.argv = [m]; runpy.run_module(m, run_name="__main__", alter_sys=True)'
    for s in rbac_seed dev_users catalog_demo placement_demo coding_demo commerce_demo security_demo e2e_demo company_demo; do
      echo "==> seed $s" >&2
      "${DC[@]}" run --rm --no-deps -T -e APP_ENV=dev -e TD_SERVICE_NAME=seed \
        -v "$SRC/apps/api/app/seeds:/srv/api/app/seeds:ro" migrate python -c "$RUNNER" "app.seeds.$s" >/dev/null
    done
    echo "seeds done" >&2 ;;
  rotate)
    shift
    "${DC[@]}" run --rm --no-deps -T -e TD_SERVICE_NAME=rotate \
      -v "$SRC/infra/gcp-demo/rotate_demo_accounts.py:/tmp/rotate_demo_accounts.py:ro" \
      migrate python /tmp/rotate_demo_accounts.py "$@" ;;
  create-admin)
    # sudo bash vm.sh create-admin --email <email> --name "<full name>"   (credentials as JSON on STDOUT)
    shift
    "${DC[@]}" run --rm --no-deps -T -e TD_SERVICE_NAME=create-admin       -v "$SRC/infra/gcp-demo/create_admin.py:/tmp/create_admin.py:ro"       migrate python /tmp/create_admin.py "$@" ;;
  set-login)
    # printf '%s' '<password>' | sudo bash vm.sh set-login --email <email>   (password on STDIN only)
    shift
    "${DC[@]}" run --rm --no-deps -T -e TD_SERVICE_NAME=set-login -v "$SRC/infra/gcp-demo/set_login.py:/tmp/set_login.py:ro" migrate python /tmp/set_login.py "$@" ;;
  reset-devices)
    # "Device limit reached" at sign-in: free the account's trusted-browser slots
    #   sudo bash vm.sh reset-devices --email <email> [--keep N]
    shift
    "${DC[@]}" run --rm --no-deps -T -e TD_SERVICE_NAME=reset-devices -v "$SRC/infra/gcp-demo/reset_devices.py:/tmp/reset_devices.py:ro" migrate python /tmp/reset_devices.py "$@" ;;
  otp)
    # Mail never leaves the VM (internal Mailpit). Show the newest sign-in/verification code
    # sent to one address:  sudo bash vm.sh otp student@dev.techdrona.local
    to="${2:?usage: vm.sh otp <email>}"
    id=$(docker exec techdrona-web-1 wget -qO- "http://mailpit:8025/api/v1/search?query=to:${to}&limit=1" \
      | python3 -c 'import sys,json; m=json.load(sys.stdin)["messages"]; print(m[0]["ID"] if m else "")')
    [ -n "$id" ] || { echo "no mail for $to" >&2; exit 1; }
    docker exec techdrona-web-1 wget -qO- "http://mailpit:8025/api/v1/message/$id" \
      | python3 -c 'import sys,json,re; m=json.load(sys.stdin); c=re.search(r"\b(\d{6})\b", m.get("Text","")); print(m["Date"], "|", m["Subject"], "|", c.group(1) if c else "(no 6-digit code; open the link in the text)"); print(m.get("Text","")[:600] if not c else "")' ;;
  portal-import)
    # sudo bash vm.sh portal-import ~/college.db   (replaces the portal DB; a backup of the current one is taken first)
    # The file must be a consistent SQLite file: export it with VACUUM INTO (or copy it while the server is stopped).
    f="${ARG2_ABS:?usage: vm.sh portal-import <file.db>}"
    [ -f "$f" ] || { echo "no such file: $f" >&2; exit 1; }
    if [ -n "$("${DC[@]}" ps -q college-portal)" ]; then bash "$SELF" portal-backup; fi
    "${DC[@]}" stop college-portal || true
    # Streamed in on stdin: the file never needs to be world-readable for the container's node user.
    "${DC[@]}" run --rm --no-deps -T --entrypoint sh college-portal -c '
      set -e
      cat > /data/techdrona.db.import
      node -e "
        const {DatabaseSync}=require(\"node:sqlite\");
        const d=new DatabaseSync(\"/data/techdrona.db.import\");
        const ok=d.prepare(\"pragma integrity_check\").get().integrity_check;
        const n=d.prepare(\"select count(*) n from colleges\").get().n;
        d.close();
        console.log(\"integrity_check:\", ok, \"colleges:\", n);
        if (ok !== \"ok\") process.exit(1);
      " || { rm -f /data/techdrona.db.import; echo "import refused: integrity check failed" >&2; exit 1; }
      rm -f /data/techdrona.db-wal /data/techdrona.db-shm
      mv /data/techdrona.db.import /data/techdrona.db' < "$f"
    "${DC[@]}" up -d college-portal ;;
  portal-backup)
    mkdir -p /opt/techdrona/backups && chmod 0700 /opt/techdrona/backups
    out="/opt/techdrona/backups/college-portal-$(date -u +%Y%m%dT%H%M%SZ).db"
    "${DC[@]}" exec -T college-portal node -e "require('node:fs').rmSync('/data/backup.tmp.db',{force:true});new (require('node:sqlite').DatabaseSync)('/data/techdrona.db').exec(\"VACUUM INTO '/data/backup.tmp.db'\")"
    ( umask 077; "${DC[@]}" exec -T college-portal cat /data/backup.tmp.db > "$out" )
    "${DC[@]}" exec -T college-portal rm -f /data/backup.tmp.db
    [ -s "$out" ] || { echo "backup failed: $out is empty" >&2; exit 1; }
    echo "$out" ;;
  ps) "${DC[@]}" ps -a ;;
  logs) shift; "${DC[@]}" logs --tail 100 "$@" ;;
  down) "${DC[@]}" down ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
