# This directory is a GENERATED SNAPSHOT — not a source of truth

Produced by `storyos/scripts/publish_stage.py` on 2026-09-19, containing the 119-file
static stage (all 52 accepted chapters, per-project views, locks, gate and API JSON).

Why it is published despite the repo policy against committing generated payloads
(see `.gitignore`): the human asked for the whole system, including prose, to be on
GitHub. Consequences to accept:

1. This snapshot goes stale the moment the project moves. The live edge at the time of
   writing is **after Chapter52**. The regenerable source is
   `../framework/scripts/publish_stage.py` + `$STORYOS_HOME`.
2. The permanent, always-fresh authority is the paste mirror referenced in `pointer.md`
   (paste.rs ids are immutable, so every publish mints a new one and publishes it).
3. The ephemeral tunnel hostname has been REMOVED from every file here by design. Quick
   tunnels are re-minted on each start; publishing one would create a false claim sitting
   next to a permanent URL.
4. Nothing in here is secret: no key value, no credential. That was verified by an
   explicit scan (the live key lives outside the repo at `$STORYOS_HOME/.public_key`).
