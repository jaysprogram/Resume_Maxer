#!/usr/bin/env bash
# Write /etc/resume-maxer/env: the web password's hash, a fresh session secret,
# and the Anthropic API key. Run as root, interactively, on the server:
#
#   ssh -t <server> bash /opt/resume-maxer/deploy/set-secrets.sh
#
# Nothing typed here is echoed, put on a command line, or logged.
set -euo pipefail

ENV_FILE=/etc/resume-maxer/env
PY=/opt/resume-maxer/.venv/bin/python

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -x $PY ]] || { echo "run deploy/setup.sh first" >&2; exit 1; }

read -rsp "New web password (12+ characters): " password; echo
[[ ${#password} -ge 12 ]] || { echo "too short" >&2; exit 1; }
read -rsp "Again: " again; echo
[[ $password == "$again" ]] || { echo "the passwords do not match" >&2; exit 1; }
read -rsp "Anthropic API key: " api_key; echo
[[ $api_key == sk-ant-* ]] || { echo "that does not look like an Anthropic API key" >&2; exit 1; }

# The password goes to Python on stdin, never as an argument (arguments show in ps).
hash=$(printf '%s' "$password" |
  "$PY" -c 'import sys; from resume_maxer.auth import hash_password; print(hash_password(sys.stdin.read()))')
secret=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')

umask 077
tmp=$(mktemp "$ENV_FILE.XXXXXX")
# Single quotes: the hash contains "$", which must reach the app literally.
# None of these values can contain a quote (base64, url-safe token, sk-ant- key).
{
  echo "RESUME_WEB_PASSWORD_HASH='$hash'"
  echo "RESUME_WEB_SECRET='$secret'"
  echo "ANTHROPIC_API_KEY='$api_key'"
} >"$tmp"
mv "$tmp" "$ENV_FILE"
echo "wrote $ENV_FILE (root only). Now run: bash /opt/resume-maxer/deploy/setup.sh"
