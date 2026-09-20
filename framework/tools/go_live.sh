#!/usr/bin/env bash
# go_live.sh — rebuild the stage, publish it, and hold a public URL open.
# The URL is a Cloudflare *quick* tunnel: free, no signup, and it only lives while this
# process runs. For a permanent URL, upload storyos-site/ to your own host instead.
set -uo pipefail
REPO=${STORYOS_REPO:-$HOME/storyos}
HOME_DIR=${STORYOS_HOME:-$HOME/storyos-home}
CF=${CF_BIN:-/tmp/cfb}
PORT=${PUBLIC_PORT:-4181}
export STORYOS_HOME="$HOME_DIR" STORYOS_SITE_DIR="$HOME/storyos-site"

[ -x "$CF" ] || { echo "cloudflared missing: fetch it first (see header)"; }

build() {
  python3 "$REPO/scripts/publish_stage.py" >/tmp/storyos_stage.log 2>&1
  python3 "$REPO/scripts/verify_stage.py" "$STORYOS_SITE_DIR" >>/tmp/storyos_stage.log 2>&1 \
    || { echo "REFUSING TO PUBLISH: stage failed verification — see /tmp/storyos_stage.log"; return 1; }
  return 0
}

publish_loop() {
  local last=""
  while :; do
    build || { sleep 30; continue; }
    [ -f /tmp/storyos_url ] && u=$(cat /tmp/storyos_url) && [ -n "$u" ] && \
      curl -so /dev/null --max-time 15 "$u/api/manifest.json" && { sleep 120; continue; }
    pkill -f "tunnel --url http://127.0.0.1:$PORT" 2>/dev/null; sleep 1
    ( "$CF" tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate >/tmp/storyos_cf.log 2>&1 ) &
    for i in $(seq 1 30); do
      u=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/storyos_cf.log | head -1)
      [ -n "$u" ] && break; sleep 2
    done
    if [ -n "$u" ]; then echo "$u" > /tmp/storyos_url
      echo "LIVE: $u   (agents: $u/agents.md)"; else echo "tunnel failed, retrying in 60s"; sleep 60; fi
  done
}

mirror() { python3 "$REPO/tools/public_site.py" "$PORT" >/tmp/storyos_mirror.log 2>&1 & }

case "${1:-up}" in
  up)    build || exit 1
         pgrep -f "public_site.py $PORT" >/dev/null || mirror
         publish_loop ;;
  once)  build || exit 1
         pgrep -f "public_site.py $PORT" >/dev/null || mirror
         "$CF" tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>&1 \
           | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 ;;
  down)  pkill -f "tunnel --url http://127.0.0.1:$PORT"; pkill -f "public_site.py $PORT"; echo "stopped" ;;
  *)     echo "usage: go_live.sh [up|once|down]" ;;
esac
