# Adopted universal laws — StoryOS

Generated from `/home/user/storyos-home/laws/UNIVERSAL_LAWS.json` by `scripts/gen_laws_doc.py`. Do not hand-edit this file; edit the
JSON, or file a contribution under `intake/drop/`.

- **imported from:** github:gm5206663-bit/the-universal-storyline-creation-@7da59a52 state/laws.json
- **status:** ADOPTED into the authority ladder at level 3 (kit laws). These are DATA for the validator and for agents; the human's explicit words and project locked documents still outrank them. Their selftest (102/102) passed as delivered, which is why they were accepted rather than re-derived.

## Authority order (which source wins when they disagree)

1. The user's explicit words
2. Project locked documents
3. Kit laws
4. Kit canon spine
5. Earlier projects - craft only, never canon

## The twelve locks (a chapter is not writable until each is answerable)

- **1. ERA** — Which series, which years, which DC range
- **2. PROTAGONIST** — Who they are - and explicitly what they are NOT
- **3. CANON ENTRY** — The specific canon beats this serial touches. Name at least five.
- **4. SPINE** — Who wants what from the protagonist, and what they will do to get it
- **5. POWER CEILING** — The strongest the OC becomes, and what they never get
- **6. IDENTITY** — Public name versus true name; what the reveal costs
- **7. ABSOLUTES** — What the protagonist will never do, ever
- **8. CANON IMMUNITY** — Which canon characters' fates may not be rerouted
- **9. MEASUREMENT** — How rank and rings are shown on the page
- **10. VOICE** — POV, tense, register rules
- **11. CADENCE** — Chapters per pass, words per chapter, when audits run
- **12. HANDOFF** — What a fresh agent must read first

> Lock 4 rule: Write it as a full sentence with all three blanks filled: '______ wants ______ from my protagonist, and will ______ to get it.' If you cannot fill all three, there is no story yet - there is only a setting.

## Pipeline (LOAD → … → RECORD)

1. **LOAD** — Read the live edge and the locks
2. **VERIFY** — Reconstruct canon scene by scene
3. **MAP** — Timeline, location, prop, knowledge
4. **FORECAST** — Butterfly effects from real changes
5. **BLUEPRINT** — Beat order, registers, panel range
6. **DRAFT** — Prose carries the chapter
7. **AUDIT** — Run all seven hard gates
8. **REPAIR** — Fix, then re-run the gates
9. **DELIVER** — Ship the chapter
10. **RECORD** — Update ledgers and the serial log

## Pre-draft gate

1. **Reconstruct** — Rebuild the relevant canon scene by scene. Not from memory - from receipts. If a scene is missing, say it is missing.
2. **Verify exact detail** — Event order, location, timing, positions, clothing, objects, environment, dialogue style, motivations, character knowledge.
3. **Build the ledgers** — Timeline, location, prop, power and adaptation, knowledge - who knows what, and since when.
4. **Firewall** — Hide information from characters who have not earned it. Author knowledge is never character knowledge. Check every speaking character against the registry.
5. **Resolve conflicts** — Use the authority hierarchy. User words beat project docs beat kit laws. Record the resolution, not just the result.
6. **Then blueprint** — Only now set beat order. Set the panel year range first. Then draft.

## Knowledge-firewall states (the only legal values)

- `KNOWN` — Verified knowledge
- `KNOWN PARTLY` — Partial knowledge
- `SUSPICION` — Suspects, unproven
- `DISBELIEF` — Actively rejects it
- `UNKNOWN` — No knowledge at all
- `FALSE BELIEF` — Believes something untrue
- `HIDDEN` — Known by author, withheld

## Leak paths (never do these)

- Never convert suspicion, intuition, rumour, or prophecy fragments into factual character knowledge without evidence. Never give a character information earlier than the earliest valid change recorded in their firewall. Predetermined destiny does not pre-install personal memories or trust. Instinctive power control after an awakening does not equal encyclopaedic lore.

## Failure modes this system was built to prevent

- **1. No canon spine** — The serial never asked what canon says happens in that forest. Canon says people hunt there for rings.
- **2. Nothing contested** — No antagonist pressure. The protagonist was never wanted by anyone for anything.
- **3. No felt progression** — Rank and ring changes were asserted in panels but never earned on the page.
- **4. One register repeated** — Fifteen chapters in a single interior-meditation voice. Dialogue vanished from seven of them.
- **5. Apparatus outgrew story** — Panels, ledgers and codex entries became the product; the story became the appendix.

## Two rules about the checker itself

- **Self-referential trap.** A check must not match its own description. Five confirmed instances: a blanket non-ASCII gate flagging the em dashes in the prose law that explains the rule; a case-insensitive substring flagging 'placeholder' inside 'no placeholder text left'; gate 6 over templates flagging every slot token; gate 6 over an audit log flagging its own zero-count report; and documenting that last case inside the audit law re-tripping the same class. Scope the gate, do not reword the file.

- **Negative test rule.** Ship the negative test with the gate. tools/selftest.py exists because verify.py once reported fifteen failures against a proven 33,100-word serial - every one of them a false positive. A gate nobody has tested is a guess.

- **Gate scope.** Gate 6 must never be applied to templates, law files, or audit logs. A template with no slot tokens is not a template. A law file that cannot show the panel format cannot teach it. An audit log reports on placeholder counts - a line reading 'TODO/FIXME/TBD = 0' is the log doing its job, not a leftover. Gates 1 and 2 are the only ones that apply everywhere, because they are the ones that indicate a file is broken rather than a file being what it is.

## How StoryOS applies these

- `tools/storyos_validate.py` loads the firewall-state vocabulary from this file, so the
  gate and the laws cannot disagree. `SUSPECTED` is accepted as a legacy alias for
  `SUSPICION` and produces a warning, so existing project data is not newly failed.
- `tools/intake.py` enforces the reserved-field list and the firewall/canon vocabularies
  for contributions from other agents.
- Gate 3 (`zero digits in prose`) is **not** adopted: this project's own locks require exact
  figures (Rank20/SP505, Dawnflame 3,100) and its validator enforces them. Adopting that
  gate would contradict the human's explicit requirements, and the authority order says the
  project's locked documents outrank kit laws.

_source file sha256: `ad764325bca11442…_
