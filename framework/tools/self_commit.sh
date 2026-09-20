#!/usr/bin/env bash
# self_commit.sh — the growth loop's memory. Run after any scan/learn/chapter; history is the audit trail.
set -euo pipefail
HOME_DIR="${STORYOS_HOME:-$HOME/storyos-home}"
REPO_DIR="${STORYOS_REPO:-$HOME/storyos}"
cd "$REPO_DIR"
if [ ! -d .git ]; then
  git init -q
  printf 'audits/\n__pycache__/\n*.pyc\nsite/*.bak\n' > .gitignore
  git add -A && git -c user.name=StoryOS -c user.email=storyos@local commit -qm "storyos baseline $(date +%F)" -q
  echo "initialised git at $REPO_DIR"
fi
# snapshot the accumulating home so decisions survive a lost workspace
if [ -d "$HOME_DIR" ]; then
  mkdir -p storyos-home
  rsync -a --delete --exclude '__pycache__' "$HOME_DIR/" storyos-home/ 2>/dev/null \
    || { rm -rf storyos-home; cp -r "$HOME_DIR" storyos-home; }
fi
git add -A
if git diff --cached --quiet; then echo "nothing new to record"; exit 0; fi
LEARNED=$(find "$HOME_DIR"/projects/*/decisions.jsonl 2>/dev/null -exec cat {} + | wc -l | tr -d ' ')
git -c user.name=StoryOS -c user.email=storyos@local commit -qm "state + ${LEARNED} decisions recorded ($(date +%F' '%H:%M))"
echo "committed · total decisions on record: $LEARNED"
git log --oneline | head -3
