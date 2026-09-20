# Correction patch — APPLIED 2026-09-18 — stale live-edge claims in the active tree

Live edge of record: **after Chapter51** — `The Cost of Quiet`, declared 2026-09-18 by foundation/CURRENT_STATE_MANIFEST.json (native, authoritative). Canon consumed through source Chapter176; next source Chapter177.

Each line below asserts a DIFFERENT edge. I am not editing your project without your word, so this is the patch list, not a fait accompli. Every edit preserves the old number as labelled history — nothing is deleted, and no canon value, lock or firewall rule moves.

| file | line | says | behind | proposed replacement |
|---|---|---|---|---|
| `bible/YAN_SHUOER_IDENTITY_AND_APPEARANCE.md` | 182 | after Chapter33 | 18 | `Historical Chapter33 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `bible/PROTAGONIST.md` | 86 | after Chapter34 | 17 | `Historical Chapter34 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `bible/PROTAGONIST.md` | 98 | after Chapter35 | 16 | `Historical Chapter35 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `canon_coverage/Phoenix_Dragon_Canon_Dossier.md` | 1 | after Chapter35 | 16 | `Historical Chapter35 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `bible/ADAPTATION_TALENT_LOCAL.md` | 129 | after Chapter49 | 2 | `Historical Chapter49 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `bible/FIRST_RING_ACQUISITION.md` | 99 | after Chapter49 | 2 | `Historical Chapter49 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `foundation/DAWNFLAME_FORM_AND_SOUL_SPIRIT_FUSION_RULES.md` | 143 | after Chapter49 | 2 | `Historical Chapter49 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `foundation/FIRE_LIGHT_ATTRIBUTE_LOCK.md` | 103 | after Chapter49 | 2 | `Historical Chapter49 note (recorded when that was the edge). Current live edge is after Chapter51.` |
| `foundation/PRECISION_AND_GROWTH_LOCKS.md` | 109 | after Chapter49 | 2 | `Historical Chapter49 note (recorded when that was the edge). Current live edge is after Chapter51.` |

## Explicitly NOT touched
- The five `Historical ChapterNN note … Current live edge is after ChapterMM` lines — already correct; flagging them was the external agent's false positive.
- `foundation/CANON_LEDGER.md`, `foundation/SERIAL_LOG.md`, dated `audits/*_before/` snapshots — history by construction; excluded from the sweep deliberately.
- Source-chapter pointers (Chapter130/135/177) — a source chapter number is not a fic live-edge claim.
- Every lock, firewall, forbidden literal and power value.

Say **do it** and I apply exactly these 9 line edits, re-run the validator and the native `perfect_continuation_skill_check.py --phase post`, then republish.


## Result (measured, not asserted)

- 9/9 targets edited; every edit is one clause, `bytes_delta` per file is in the manifest.
- Re-scan: `stale_edge_claims` went 9 → **0**; `stale_claims` 10 → 1 (the remaining entry is
  a dated SKILL_CHECK receipt that *should* read as history, so 1 is the correct residue).
- Canon values verified still present in the edited files: Rank34, SP689, 2,050, Rank29,
  SP392, cocoon day twenty-one. Nothing was deleted; the six lines opening
  `Historical Chapter35 note:` kept their history and only their stale trailing clause moved.
- `storyos_validate.py --phase full`: GATE clear. Native `perfect_continuation_skill_check.py
  --phase post`: PASS. Backups: `storyos-patch-backups/edge_claims_2026-09-18/` (outside the
  project, so the agent bundle cannot ship them as a stale copy — the mistake that put 325
  superseded files into the last bundle).
