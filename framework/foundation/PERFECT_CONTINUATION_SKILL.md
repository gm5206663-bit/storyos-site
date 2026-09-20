# Perfect Continuation Skill — v3 (executable)

Purpose: continue an existing project so seamlessly that no reader, and no later agent,
can tell where the previous model stopped. The old skill was a document; this one is a
**gate**, because documents get skimmed and gates do not.

## The six gates
| Gate | Requirement | Failure mode it prevents |
|---|---|---|
| G1 State | `scan_project.py` re-run; manifest newer than the edge claim | drafting from stale state |
| G2 Branch | every superseded receipt marked `SUPERSEDED` or archived | re-importing rejected work |
| G3 Source | all chunks of the next canon chapter fetched; coverage file written first | paraphrase drift, invented beats |
| G4 Knowledge | every fact mapped to a firewall state before use | characters "somehow knowing" |
| G5 Power | locked floors/ceilings applied to all comparisons | nerf-by-convenience |
| G6 Regression | `--phase post --files <chapter>` passes | re-introducing deleted values |

## Continuation algorithm
1. Identify the exact live edge (chapter, scene, position, time, who is present).
2. Reconstruct the consumed canon beats scene-by-scene: order, location, timing, positions,
   clothing, objects, environment, dialogue register, motivation, character knowledge.
3. Build the working ledgers for this chapter only: timeline / location / prop / power / knowledge.
4. Apply firewalls: hide anything a character has not earned.
5. Choose which beats are *routine* (compress) and which are *meaningful* (expand). R18.
6. Blueprint scene-by-scene with the change each scene must cause.
7. Draft. No new facts outside the ledgers.
8. `--phase post`. Fix every error. Re-scan. Record a validation receipt.

## Output discipline
When asked to continue, first answer in three lines:
`CONFIRMED: …` / `MISSING: …` / `MUST RECONSTRUCT: …` — then, and only then, the chapter.
