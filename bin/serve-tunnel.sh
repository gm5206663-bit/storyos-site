#!/usr/bin/env bash
# StoryOS Site — serve behind a Cloudflare quick tunnel.
#
# Uses --protocol http2 because QUIC drops inside sandboxes/containers and leaves a
# connector that is *alive but detached*: Cloudflare then answers HTTP 530 / error 1033
# for a hostname that still resolves. Measured: 14/20 requests served over QUIC vs
# 15/15 and 10/10 over http2 with 2 HA connections.
#
# Usage:
#   bin/serve-tunnel.sh                 # build, serve on :8080, tunnel it, publish pointer
#   PORT=9000 bin/serve-tunnel.sh
#
# Env:
#   STORYOS_ROOT   project source root   (default /home/user/project/workspace-HANDOFF.md)
#   STORYOS_KEY    write key. If unset, reads data/.key. If neither, writes are disabled.
#   POINTER_CMD    command that publishes the pointer paste (see publish_pointer below)

set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
ROOT="${STORYOS_ROOT:-/home/user/project/workspace-HANDOFF.md}"
LOG=/tmp/storyos_cf.log
SRVLOG=/tmp/storyos_srv.log

echo "== build =="
python3 scripts/build.py --root "$ROOT"

# key: env wins, else data/.key, else generate a local one so write routes are testable
if [ -z "${STORYOS_KEY:-}" ]; then
  if [ ! -f data/.key ]; then
    python3 -c "import secrets;print('LOCALTEST-'+secrets.token_urlsafe(18))" > data/.key
    chmod 600 data/.key
    echo "generated a local key at data/.key (mode 600)"
  fi
  STORYOS_KEY="$(tr -d '\n' < data/.key)"
  export STORYOS_KEY
fi

echo "== server on $HOST:$PORT =="
pkill -f "scripts/server.py" 2>/dev/null || true
sleep 0.5
PORT="$PORT" HOST="$HOST" STORYOS_ROOT="$ROOT" \
  nohup python3 scripts/server.py > "$SRVLOG" 2>&1 &
sleep 1.5

# local health check BEFORE minting a tunnel: a tunnel to a dead app is the 1033 trap
if ! curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/projects" > /dev/null; then
  echo "server did not answer locally — see $SRVLOG" >&2
  tail -20 "$SRVLOG" >&2
  exit 1
fi
echo "local check OK"

echo "== tunnel (http2, 2 HA connections) =="
command -v cloudflared >/dev/null || { echo "cloudflared not installed" >&2; exit 1; }
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 0.5
nohup cloudflared tunnel --url "http://127.0.0.1:$PORT" \
  --protocol http2 --ha-connections 2 > "$LOG" 2>&1 &

URL=""
for i in $(seq 1 40); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "no tunnel URL — see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }

# verify END TO END through the public edge, not just locally.
# A registered connector is not the same as a serving one.
ok=0
for i in $(seq 1 6); do
  code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$URL/api/projects" || echo 000)"
  [ "$code" = "200" ] && ok=$((ok+1))
  sleep 1
done
echo "public edge: $ok/6 requests served 200"
if [ "$ok" -lt 3 ]; then
  echo "WARNING: tunnel registered but the edge is not serving reliably." >&2
  echo "  grep -c 'Registered tunnel connection' $LOG" >&2
  grep -iE "error|failed|retry" "$LOG" | tail -5 >&2 || true
fi

cat > data/current_url.txt <<EOF
$URL
updated $(date -u +%Y-%m-%dT%H:%M:%SZ)
public edge check: $ok/6
EOF

echo
echo "LIVE: $URL"
echo "  agents entry : $URL/agents.md"
echo "  manifest     : $URL/api/manifest.json"
echo "  gates        : $URL/api/projects"
echo
echo "Re-publish your pointer paste so it names this URL, e.g.:"
echo "  printf 'CURRENT LIVE URL: %s\\n' '$URL' | curl -sS -X POST --data-binary @- https://paste.rs/"
