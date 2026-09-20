# Framework copy — provenance and what is NOT here

Synced by the StoryOS agent (Arena.ai) on 2026-09-19 into this public repo, alongside (never
overwriting) the hand-built control centre that was already here: `app/index.html`,
`scripts/build.py`, `scripts/drift.py`, `scripts/server.py`, `seed/`, `bin/serve-tunnel.sh`,
`README.md`, `HANDOFF.md`.

Contents: validator (`tools/storyos_validate.py`), scanner (`scripts/scan_project.py`),
publisher (`scripts/publish_stage.py`, `publish_mirror.py`), the interactive server, the
project template, and both project states under `storyos-home/`.

Deliberately excluded:

- The shared write key. It is only ever read from `$STORYOS_HOME/.public_key`, and this
  repo is public; `grep` finds no key value and no credential anywhere in `framework/` or
  `published-site/`.
- The ephemeral tunnel hostname (scrubbed — see published-site/GENERATED.md).
- `__pycache__`, `.env`, `*.key`, `*.pem`.

Verification at the time of sync: `STORYOS_VALIDATE: PASS (errors=0, warnings=0)`,
`SELFTEST: 5/5`, `TEST_AUTH: PASS`, `MIRROR_VERIFY: PASS`, native project checker PASS.
