#!/usr/bin/env bash
# Install or update Resume Maxer on the server. Run as root; safe to rerun.
#
#   bash /opt/resume-maxer/deploy/setup.sh resume.example.com   (first run)
#   bash /opt/resume-maxer/deploy/setup.sh                      (updates: domain remembered)
#
# Layout, matching the other apps on this server:
#   /opt/resume-maxer          code + .venv (root-owned, read-only to the app)
#   /var/lib/resume-maxer      data/master.json, runs/, Tectonic cache (app-owned, 0700)
#   /etc/resume-maxer/env      secrets, written by set-secrets.sh (root, 0600)
set -euo pipefail

APP=resume-maxer
REPO=https://github.com/jaysprogram/Resume_Maxer.git
CODE=/opt/$APP
STATE=/var/lib/$APP
ETC=/etc/$APP
PORT=8791
CLAUDE_DIR=/opt/$APP-claude
CLAUDE_CODE_VERSION=2.1.304  # the version the claude-code backend was tested with

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

# The public domain is kept on the server, not in the (public) repo.
install -d -m 0700 -o root -g root "$ETC"
if [[ -n ${1:-} ]]; then
  [[ $1 =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo "not a domain: $1" >&2; exit 1; }
  echo "$1" >"$ETC/domain"
fi
[[ -s $ETC/domain ]] || { echo "first run: give the domain, e.g. setup.sh resume.example.com" >&2; exit 1; }
DOMAIN=$(<"$ETC/domain")
echo "== domain: $DOMAIN"

echo "== code"
if [[ -z ${RESUME_MAXER_SETUP_UPDATED:-} ]]; then
  if [[ -d $CODE/.git ]]; then
    git -C "$CODE" fetch --quiet origin main
    git -C "$CODE" reset --quiet --hard origin/main
  else
    git clone --quiet "$REPO" "$CODE"
  fi
  # This script may itself have just changed. Bash keeps reading the old copy
  # it opened, so restart from the new one (once) to run the current steps.
  RESUME_MAXER_SETUP_UPDATED=1 exec bash "$CODE/deploy/setup.sh" "$@"
fi
git -C "$CODE" log --oneline -1
# System Python only: a uv-managed Python would live under /root, which the
# service cannot read (ProtectHome).
(cd "$CODE" && UV_PYTHON_PREFERENCE=only-system uv sync --locked --no-dev --quiet)

echo "== user and folders"
id -u "$APP" >/dev/null 2>&1 ||
  useradd --system --home-dir "$STATE" --shell /usr/sbin/nologin "$APP"
install -d -m 0700 -o "$APP" -g "$APP" "$STATE" "$STATE/data" "$STATE/runs" "$STATE/cache"

echo "== tectonic"
# shellcheck source=deploy/tectonic.env
. "$CODE/deploy/tectonic.env"
if ! /usr/local/bin/tectonic --version 2>/dev/null | grep -q "$TECTONIC_VERSION"; then
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/t.tar.gz" \
    "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-gnu.tar.gz"
  echo "${TECTONIC_SHA256}  $tmp/t.tar.gz" | sha256sum -c --quiet -
  tar -xzf "$tmp/t.tar.gz" -C "$tmp" tectonic
  install -m 0755 "$tmp/tectonic" /usr/local/bin/tectonic
  rm -rf "$tmp"
fi
/usr/local/bin/tectonic --version

echo "== claude code (for the claude-code backend)"
# The app's own copy, pinned, outside /root (the service cannot read /root) and
# apart from any other Claude Code on this server. Self-update is off in the
# unit, since this folder is read-only to the service.
backend=$(sed -n "s/^RESUME_BACKEND='\(.*\)'$/\1/p" "$ETC/env" 2>/dev/null || true)
if [[ $backend != api ]]; then
  if [[ ! -x $CLAUDE_DIR/node_modules/.bin/claude ]] ||
     ! "$CLAUDE_DIR/node_modules/.bin/claude" --version 2>/dev/null | grep -q "^$CLAUDE_CODE_VERSION "; then
    npm install --prefix "$CLAUDE_DIR" --no-fund --no-audit --loglevel=error \
      "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"
  fi
  "$CLAUDE_DIR/node_modules/.bin/claude" --version
fi

echo "== warm the Tectonic cache (first compile downloads fonts and packages)"
runuser -u "$APP" -- env XDG_CACHE_HOME="$STATE/cache" TECTONIC=/usr/local/bin/tectonic \
  "$CODE/.venv/bin/python" -c '
import json
from pathlib import Path
from resume_maxer.compile import compile_tex
from resume_maxer.render import render
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.schema import Master
ex = Path("'"$CODE"'/examples")
master = Master.model_validate(json.loads((ex / "sample_master.json").read_text()))
doc = ResumeDoc.model_validate(json.loads((ex / "sample_resume_doc.json").read_text()))
print("sample compiled:", compile_tex(render(doc, master)).pages, "page")
'

echo "== systemd"
install -m 0644 "$CODE/deploy/$APP.service" /etc/systemd/system/$APP.service
systemctl daemon-reload
systemctl enable --quiet $APP

echo "== caddy"
sed "s/^resume\.example\.com {$/$DOMAIN {/" "$CODE/deploy/resume.caddy" >/etc/caddy/sites/resume.caddy
chmod 0644 /etc/caddy/sites/resume.caddy
grep -q "^$DOMAIN {" /etc/caddy/sites/resume.caddy || { echo "domain not set in the Caddy site" >&2; exit 1; }
# Validate the whole config first: a broken file must never reach the live
# Caddy, which also serves the other sites on this server.
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl reload caddy

echo "== start"
missing=()
[[ -f $STATE/data/master.json ]] || missing+=("$STATE/data/master.json (copy it from your machine)")
key=$([[ $backend == api ]] && echo ANTHROPIC_API_KEY || echo CLAUDE_CODE_OAUTH_TOKEN)
for name in RESUME_WEB_PASSWORD_HASH RESUME_WEB_SECRET RESUME_BACKEND "$key"; do
  grep -q "^$name=" "$ETC/env" 2>/dev/null || missing+=("$name in $ETC/env (run deploy/set-secrets.sh)")
done
if ((${#missing[@]})); then
  printf 'not started yet; missing:\n'
  printf '  - %s\n' "${missing[@]}"
  exit 0
fi
systemctl restart $APP
sleep 2
curl -fsS "http://127.0.0.1:$PORT/healthz" && echo " <- $APP is up on 127.0.0.1:$PORT"
