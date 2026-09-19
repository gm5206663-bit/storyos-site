# StoryOS Site

Everything about your projects and your agents, on one host. Built so that a **new agent
can arrive knowing nothing** and still get the live edge, the locks, the firewalls, the
learned rules and the thing it is not allowed to do — without a human re-explaining.

Standard library only. No node_modules, no CDN, no framework, no build step at runtime.
Python 3.9+.

```
scripts/build.py     scan the projects -> data/*.json (with sha256 for every file)
scripts/drift.py     independent stale-edge scanner (does not trust the project's checker)
scripts/server.py    static app + JSON API + proposal inbox + key-gated writes + audit log
app/index.html       the whole UI, one self-contained file (no external assets)
bin/serve-tunnel.sh  build + serve + cloudflared (http2) + end-to-end edge verification
data/                generated. index.json, state/, chapters/, vault/, issues.json
```

## Run it

```bash
python3 scripts/build.py --root /home/user/project/workspace-HANDOFF.md
PORT=8080 python3 scripts/server.py
```

Tunnel it (uses `--protocol http2 --ha-connections 2`; QUIC drops in sandboxes and leaves
a connector that is alive but detached, which Cloudflare reports as 530/1033):

```bash
bin/serve-tunnel.sh
```

## What each view is

| view | route | what it gives |
|---|---|---|
| Overview | `#/home` | every project, its gate, live edge, counts, and gate findings |
| Reader | `#/read/<project>` | all chapters as a reading experience. Production notes and the canon-coverage receipt are folded away, not deleted. Reading progress in localStorage. `/` focuses search across prose + notes. |
| State | `#/state/<project>` | edge, characters, firewalls, learned rules, lock cards |
| Vault | `#/vault/<project>` | every file with kind, bytes, sha256, and an open link |
| Integrity | `#/integrity/<project>` | your own validator's live output, side by side with the independent drift scan, plus a derived explanation of why they disagree |
| Growth | `#/growth` | propose → inbox → promote. Plus the write model and the key-gated actions |
| Agent contract | `#/agents` | the live `/agents.md` and `/report.md` |

## API

```
GET  /agents.md                     the contract, with the exact route table
GET  /report.md                     build summary
GET  /api/manifest.json             every published file: path, bytes, sha256
GET  /api/projects                  all gates + counts
GET  /api/gate/<project>            THE GATE. drafting_permitted is the authority
GET  /api/state/<project>           edge, characters, firewalls, locks, decisions
GET  /api/issues[/<project>]        drift findings + scanner-gap proof
GET  /api/chapters/<project>        chapter index
GET  /api/chapter/<project>/<n>     prose, footer, coverage receipt, sha256
GET  /api/file/<project>/<path>     any vault file (traversal-safe)
GET  /api/vault/<project>           the file index
GET  /api/proposals                 the growth inbox
POST /api/propose/<project>         PUBLIC. Queues a proposal. Writes nothing to canon.
POST /api/learn/<project>           KEY. Append a learned rule.
POST /api/promote                   KEY. Promote a proposal into decisions.
POST /api/scan/<project>            KEY. Re-run build.py.
GET  /api/audit                     KEY. The write/deny journal.
```

Anything not listed returns **404** — not 401. Unknown routes must be distinguishable from
protected ones, or nobody can tell a typo from a wall.

## The write model, and why it is shaped like this

**There is no public write path to canon.**

An earlier test suite wrote a fake rule into real canon and then *passed* while leaving it
behind. A public `POST /api/learn` makes that mistake available to anyone on the internet.
So:

- anyone may `POST /api/propose/<project>` — it lands in `data/proposals.jsonl`, inert
- only `X-StoryOS-Key` may `learn`, `promote` or `scan`
- every authenticated write **and every denial** is appended to `data/audit.log`
- `data/.key` is mode 600, never served (`/data/.key` → 404), never embedded in the static
  export, and the UI only sends it when you press a key-gated button

### Local rule ids cannot shadow canon ids

Canon rules are `D0001…Dnnnn` and live in your `storyos-home/`, which this server sees only
through the merged external state. A local counter starting at `D0001` **collides with your
real D0001** — this was observed in testing, not theorised. So `next_local_id()` takes the
highest D-number visible anywhere (local + merged) and allocates site-created rules in a
separate `S0001…` series. Provenance stays unmistakable.

## Provenance

Two kinds of value appear in the state views:

- **derived** — computed from the project's own files in this build (`foundation/`,
  `bible/`, `chapters/`, `canon_coverage/`, `tools/`)
- **external** — merged from the published, checksummed source, because the learned rules
  and the 38 generated `.card.md` lock cards live in `storyos-home/`, *not* inside the
  project folder. A project ZIP alone therefore reports `learned=0, locks=0`, which
  understates the real canon. Merged records carry `"provenance": "external"`.

Refresh the merge with `data/external_state.json` (see `load_external` in `build.py`).
37 of 38 lock-card bodies were fetched and hash-verified from the live site; one returned
no body and is listed with `body_error`.

## Independent drift scan

`scripts/drift.py` does **not** trust the project's own validator. It scans the active tree
(`archive/` and `audits/` excluded as receipts) plus workspace-root handoff files, and
reports statements asserting a *current* live edge that disagrees with
`foundation/CURRENT_STATE_MANIFEST.json`.

Four rules keep it honest — each exists because a naive scan gets it wrong:

1. **Section context.** A claim under a dated heading
   (`## 2026-09-13 — Chapter32 written and synced` → `- Current after Chapter32:`) is a
   receipt, not drift. Without this, `CANON_LEDGER.md` produces three false positives.
2. **Self-file.** `Canon_Coverage_Chapter_36.md` saying "Current after Chapter36" documents
   its own chapter. Same for a chapter's own `## Footer`.
3. **Sentence scope.** One line can describe history *and then* assert the current edge:
   *"At that historical point, X had not fused. Current live edge is after Chapter34."*
   Exempting the line hides the stale claim, so only the sentence carrying the claim is
   judged. `:` is deliberately not a sentence splitter — it introduces a claim.
4. **Claim class.** Directives (`Live edge: after…`, `Live edge is after…`,
   `CURRENT OVERRIDE after…`) are instructions about *now* and are never exempted.

Current result on the Soul Land 4 corpus: **11 findings across 9 active files**, all SEV-1,
while the project's own validator reports `active_stale_issues=0`. The Integrity view
derives *why* by replaying the validator's own declared scope
(`active_markdown_dirs`, `top_level_active_files`) and its own two live-edge regexes
against each finding — nothing is asserted. Three causes, all fixable in the manifest:

| cause | files |
|---|---|
| outside the project dir | the workspace-root `NEXT_STEPS_FOR_CONTINUATION.md` |
| dir not scanned | `canon_coverage/` is not in `active_markdown_dirs` |
| regex no match | 7 files saying `Current live edge is after ChapterNN` |

The suggested `active_stale_regexes` entries are printed in the Integrity view, ready to
paste into `foundation/CURRENT_STATE_MANIFEST.json`.
