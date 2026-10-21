#!/usr/bin/env bash
# Write /etc/resume-maxer/env: the web password's hash, a fresh session secret,
# and how to reach Claude: an Anthropic API key (billed per run), or a Claude
# subscription token from `claude setup-token` (run on a machine where you are
# logged in to Claude Code). Run as root, interactively, on the server:
#
#   ssh -t <server> bash /opt/resume-maxer/deploy/set-secrets.sh
#
# Nothing typed here is echoed, put on a command line, or logged.
set -euo pipefail

ENV_FILE=/etc/resume-maxer/env
PY=/opt/resume-maxer/.venv/bin/python

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -x $PY ]] || { echo "run deploy/setup.sh first" >&2; exit 1; }

read -rsp "Web password (8+ characters): " password; echo
[[ ${#password} -ge 8 ]] || { echo "too short" >&2; exit 1; }
read -rsp "Again: " again; echo
[[ $password == "$again" ]] || { echo "the passwords do not match" >&2; exit 1; }
read -rsp "Anthropic API key (Enter to use a Claude subscription instead): " api_key; echo
if [[ -n $api_key ]]; then
  [[ $api_key == sk-ant-* ]] || { echo "that does not look like an Anthropic API key" >&2; exit 1; }
  backend=api key_name=ANTHROPIC_API_KEY key=$api_key
else
  # Either paste a token, or give the path of an env file on this server that
  # already holds one (another service's), so it is copied here without
  # passing through a clipboard. A setup-token token never rotates, so services
  # can share one safely.
  read -rsp "Claude subscription token, or a path to an env file holding CLAUDE_CODE_OAUTH_TOKEN: " token; echo
  if [[ -f $token ]]; then
    token=$(sed -n "s/^CLAUDE_CODE_OAUTH_TOKEN=//p" "$token" | tail -1 | tr -d "\"'")
  fi
  [[ $token == sk-ant-* ]] || { echo "no setup-token token found" >&2; exit 1; }
  backend=claude-code key_name=CLAUDE_CODE_OAUTH_TOKEN key=$token
fi

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
  echo "RESUME_BACKEND='$backend'"
  echo "$key_name='$key'"
} >"$tmp"
mv "$tmp" "$ENV_FILE"
echo "wrote $ENV_FILE (root only; backend: $backend). Now run: bash /opt/resume-maxer/deploy/setup.sh"
