#!/usr/bin/env bash
# watchdog.sh — keep the public stage reachable, and never claim a URL that is not serving.
#
# Why this exists: a quick tunnel can leave the cloudflared PROCESS alive while the edge
# connection dies, which makes the public URL return HTTP 530 — a link that resolves, so
# it looks alive, and fails for everyone who tries it. A watchdog must therefore probe the
# PUBLIC path end-to-end, never just check that a process is running.
#
#   bash tools/watchdog.sh            # loop: probe, republish, re-mint URL when it breaks
#   bash tools/watchdog.sh --once     # single check, exit 0 if serving, 1 if not
set -uo pipefail
REPO=${STORYOS_REPO:-$HOME/storyos}
HOME_DIR=${STORYOS_HOME:-$HOME/storyos-home}
SITE=${STORYOS_SITE_DIR:-$HOME/storyos-site}
RUNTIME="${STORYOS_RUNTIME:-$HOME/storyos-runtime}"     # NEVER /tmp: a sandbox recycle wipes it
CF=${CF_BIN:-$RUNTIME/bin/cloudflared}
CFLOG="$RUNTIME/tunnel.log"
SRVLOG="$RUNTIME/server.log"
PORT=${PUBLIC_PORT:-4180}
STATE=${WATCHDOG_STATE:-$RUNTIME/state}
URLF="$STATE/url"
PUBF="$STATE/current_url.txt"          # the human/agent-readable "where is it now" file
mkdir -p "$STATE"
export STORYOS_HOME="$HOME_DIR" STORYOS_SITE_DIR="$SITE" PYTHONUNBUFFERED=1

log() { echo "[$(date +%H:%M:%S)] $*"; }

origin_up() { curl -so /dev/null --max-time 8 "http://127.0.0.1:$PORT/agents.md"; }

ensure_origin() {
  origin_up && return 0
  log "origin down — restarting server on :$PORT"
  for p in $(ps -eo pid,args | awk -v p="tools/server.py" '$0 ~ p && !/awk/ {print $1}'); do
    kill -9 "$p" 2>/dev/null || true
  done
  setsid nohup env STORYOS_HOME="$HOME_DIR" STORYOS_SITE_DIR="$SITE" \
    STORYOS_KEY="${STORYOS_KEY:-}" python3 "$REPO/tools/server.py" --port "$PORT" \
    --bind "${STORYOS_BIND:-0.0.0.0}" >"$SRVLOG" 2>&1 </dev/null &
  sleep 3; origin_up
}

tunnel_ok() {
  # Free quick tunnels drop roughly 1 request in 12 (instant 000/reset) at BOTH http/1.1 and
  # h2 — measured, not assumed. A single failed probe therefore proves nothing, and re-minting
  # on a blip would destroy a URL people are already using. Require N consecutive failures.
  local u=${1:-} tries=${2:-4} i c
  [ -n "$u" ] || return 1
  for i in $(seq 1 "$tries"); do
    c=$(curl -so /dev/null -w '%{http_code}' --max-time 25 "$u/agents.md")
    [ "$c" = "200" ] && return 0
    [ "$i" != "$tries" ] && sleep 2
  done
  # Last resort before declaring death: the origin itself. If the origin answers and the edge
  # does not, this is edge flapping or a dead tunnel — either way the caller decides.
  origin_up || return 2          # 2 = origin ALSO down: not a flap
  return 1
}

mint_tunnel() {
  for p in $(ps -eo pid,args | awk '/cfb tunnel|cloudflared tunnel/ && !/awk/ {print $1}'); do
    kill -9 "$p" 2>/dev/null || true
  done
  [ -x "$CF" ] || { log "no cloudflared at $CF — cannot mint a URL"; return 1; }
  mkdir -p "$RUNTIME"; rm -f "$CFLOG"
  # QUIC is the default and it DROPS in this environment (sandbox UDP buffers), leaving the
  # cloudflared process alive with a dead connector — the edge answers 530/1033 and the URL
  # looks configured but serves nothing. http2 survives; HA connections add redundancy.
  setsid nohup "$CF" tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate \
    --protocol "${CF_PROTOCOL:-http2}" --ha-connections "${CF_HA:-2}" \
    > "$CFLOG" 2>&1 </dev/null &
  local u=""
  for _ in $(seq 1 25); do
    u=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CFLOG" | head -1)
    if [ -n "$u" ] && grep -q "Registered tunnel connection" "$CFLOG" \
       && tunnel_ok "$u" 2; then echo "$u"; return 0; fi
    sleep 2
  done
  [ -n "$u" ] && tunnel_ok "$u" && { echo "$u"; return 0; }
  log "tunnel mint failed"; return 1
}

republish_stage() {
  python3 "$REPO/scripts/publish_stage.py" --out "$SITE" >>"$STATE/build.log" 2>&1 || return 1
  python3 "$REPO/scripts/verify_stage.py" "$SITE" >>"$STATE/build.log" 2>&1 || {
    log "REFUSING to publish: stage failed verify_stage (see $STATE/build.log)"; return 1; }
  return 0
}

publish_pointer() {
  # The pointer is the only address an agent caches, so it must carry the current tunnel URL,
  # the mirror (authority) AND a measured health number. A pointer that merely asserts "up"
  # is what let a retired URL sit there for 7 minutes while an agent burned 45 retries.
  local u=$1
  mkdir -p "$STATE"
  printf '%s\n%s\n' "$u" "$(date -Is)" > "$PUBF"
  MIRROR=""
  [ -f "$HOME_DIR/.mirror_url" ] && MIRROR=$(cat "$HOME_DIR/.mirror_url")
  POINT="$HOME_DIR/.pointer_url"
  PREV=""
  [ -f "$POINT" ] && PREV=$(cat "$POINT")

  {
    echo "StoryOS pointer — measured, not promised"
    echo "updated: $(date -Is)"
    echo
    echo "AUTHORITY (read first; byte-verifiable, no key, survives session death):"
    echo "  ${MIRROR:-  (none published — ask the human to run publish_stage)}"
    echo
    echo "LIVE TUNNEL (fresh read; drops ~12s on each connector re-registration):"
    echo "  ${u:-  (none)}"
    [ -n "$u" ] && echo "  agents route table: $u/agents.md"
    echo
    echo "There is no /health, /api, /api/state or /state — a 404 there is a wrong route,"
    echo "not an outage. A 530/1033 means the CONNECTOR is detached while the origin is fine:"
    echo "fall back to the mirror above instead of retry-looping."
    echo
    if [ -f "$STATE/health.json" ]; then
      python3 - "$STATE/health.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
print("last window: {}/{} served 200 = {}%  ({} x HTTP 530), longest gap {}s".format(
    d["served_200"], d["probes"], d["availability_pct"], d["edge_failures_530"],
    d["longest_outage_s"]))
print("connector log: {} registrations / {} lost-edge events  |  origin {}".format(
    d["connector"]["registered"], d["connector"]["lost"], d["origin_local"]))
print("measured at: {}".format(d["checked_at"]))
PYEOF
    else
      echo "last window: no measurement recorded yet"
    fi
    [ -n "$PREV" ] && echo "previous pointer (may be stale): $PREV"
  } > "$STATE/pointer.txt"

  NEWP=$(curl -s --max-time 40 -X POST -H "content-type: text/plain; charset=utf-8" \
    --data-binary @"$STATE/pointer.txt" https://paste.rs/ 2>/dev/null | tail -1)
  case "$NEWP" in
    https://paste.rs/*)
      want=$(sha256sum "$STATE/pointer.txt" | cut -c1-16)
      got=$(curl -s --max-time 30 "$NEWP" | sha256sum | cut -c1-16)
      if [ "$want" = "$got" ]; then
        echo "$NEWP" > "$POINT"
        echo "  pointer: $NEWP (readback verified)"
      else
        echo "  pointer readback MISMATCH (got $got want $want) — kept $PREV"
      fi ;;
    *) echo "  pointer upload failed — kept ${PREV:-none}" ;;
  esac
}

measure() {
  # probe the public path and the connector log; health.json is what the pointer quotes
  python3 "$REPO/tools/health.py" --url "$(current_url)" --n "${MEASURE_N:-6}" \
    --sleep 2 >"$STATE/health.out" 2>&1 || true
  cp -f "$HOME_DIR/health.json" "$STATE/health.json" 2>/dev/null || true
}

current_url() { [ -f "$URLF" ] && cat "$URLF" || echo ""; }
set_url() { echo "$1" > "$URLF"; publish_pointer "$1"; }

once() {
  ensure_origin || { echo "DOWN: origin not serving"; return 1; }
  local u; u=$(current_url)
  if tunnel_ok "$u" 6; then echo "OK: $u"; return 0; fi
  log "public URL not serving after retries (${u:-none}) — re-minting"
  republish_stage || log "warn: stage rebuild/verify failed, serving previous files"
  u=$(mint_tunnel) || { echo "DOWN: no public URL available"; return 1; }
  set_url "$u"
  echo "OK: $u"; return 0
}

if [ "${1:-}" = "--once" ]; then once; exit $?; fi

log "watchdog started (origin :$PORT, state $STATE)"
fails=0
while :; do
  if ! ensure_origin; then
    log "origin down"; sleep 15; continue
  fi
  u=$(current_url)
  if ! tunnel_ok "$u" 6; then
    fails=$((fails+1))
    log "URL check failed (attempt $fails)${u:+ on $u}"
    if [ "$fails" -ge 3 ]; then
      republish_stage || true
      if nu=$(mint_tunnel); then set_url "$nu"; log "new URL: $nu"; fails=0
      else log "re-mint failed, retrying in 60s"; sleep 60; fi
    else
      sleep 8   # ~8% of requests fail at the free edge; give it several chances first
      continue
    fi
  else
    [ "$fails" != 0 ] && { log "recovered — no re-mint needed"; publish_pointer "$u"; }
    fails=0
  fi
  if [ "${REFRESH_POINTER:-1}" = "1" ]; then
    measure; publish_pointer "$u"
    # refresh the fixed-path copies on EVERY cycle, not only on recovery — "rewritten only when
    # the tunnel breaks" is precisely what let a pointer sit stale while an agent retried it
    # deliberately NOT copying health.json: the raw record has host paths. Re-generate the
    # redacted public view through the builder, which is the only place that knows how.
    python3 "$REPO/scripts/publish_stage.py" --out "$SITE" >/dev/null 2>&1 || true
    cp -f "$STATE/pointer.txt" "$SITE/pointer.md" 2>/dev/null || true
  fi
  log "healthy: $u  ($(grep -m1 'public path' "$STATE/health.out" 2>/dev/null || echo 'unmeasured'))"
  sleep "${WATCHDOG_INTERVAL:-45}"
done
