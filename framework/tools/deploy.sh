#!/usr/bin/env bash
# deploy.sh — put StoryOS online, permanently. The preview URL is ephemeral; this is not.
set -euo pipefail
TARGET="${1:-}"
usage() { cat <<USAGE
Usage: deploy.sh <fly|docker|render|git>

  fly     Fly.io single container, persistent volume for STORYOS_HOME
  docker  write a Dockerfile + compose volume for any VPS
  render  render.yaml (free tier works, state on a disk)
  git     print the remote commands to version the whole system off-box

StoryOS keeps all accumulated state as plain files under \$STORYOS_HOME, so any host
with a persistent disk is enough — no database, no vendor lock-in.
USAGE
}
case "$TARGET" in
  docker) cat > Dockerfile <<'EOF'
FROM python:3.12-slim
WORKDIR /opt/storyos
COPY storyos /opt/storyos
ENV STORYOS_HOME=/var/lib/storyos
VOLUME /var/lib/storyos
EXPOSE 4180
CMD ["python3","tools/server.py","--port","4180","--bind","0.0.0.0"]
EOF
    cat > docker-compose.yml <<'EOF'
services:
  storyos:
    build: .
    ports: ["4180:4180"]
    volumes: ["storyos-state:/var/lib/storyos"]
volumes: { storyos-state: {} }
EOF
    echo "wrote Dockerfile + docker-compose.yml — `docker compose up -d` on any VPS";;
  fly) echo "brew install flyctl && fly launch --no-deploy && fly volumes create storyos_state --size 1 && fly deploy"
    echo "then mount:  [mounts] source=\"storyos_state\" destination=\"/var/lib/storyos\"";;
  render) echo "Blueprint: web service, root=repo, build='pip install -r requirements.txt || true',"
    echo "start='python3 storyos/tools/server.py --port \$PORT --bind 0.0.0.0', disk=/var/lib/storyos";;
  git) echo "git remote add origin <your-private-repo> && git push -u origin main"
    echo "PRIVATE repo only: it contains unreleased chapters and your full canon.";;
  *) usage; exit 1;;
esac
