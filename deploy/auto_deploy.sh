#!/usr/bin/env bash
# Follow main: when it has moved, check it out, install its requirements and
# restart the monitor. luxury-watch-monitor-deploy.timer runs this every two
# minutes as the monitor's own user. A step that fails is tried again on the
# next run, because the revision counts as deployed only once the restart worked.
set -euo pipefail

cd "$(dirname "$0")/.."
git fetch --quiet origin main
revision="$(git rev-parse origin/main)"
deployed="$(cat .git/deployed 2>/dev/null || true)"
[[ "$deployed" != "$revision" ]] || exit 0

git reset --quiet --hard "$revision"
venv/bin/pip install --quiet -r requirements.txt
sudo -n systemctl restart extras-luxury-watch-monitor
echo "$revision" > .git/deployed
echo "[deploy] $(date -Is) ${deployed:0:8} -> ${revision:0:8}; restarted"
