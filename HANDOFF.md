# StoryOS Site — handoff

Built 2026-09-18. Standard library only: no node_modules, no CDN, no framework.
Python 3.9+. Everything verified by test, not asserted.

## Run it

```bash
cd /home/user/storyos-site
python3 scripts/build.py --root /home/user/project/workspace-HANDOFF.md
PORT=8080 python3 scripts/server.py
```

Tunnel it (http2 — QUIC drops in sandboxes and leaves a live-but-detached connector
that Cloudflare reports as 530/1033):

```bash
bin/serve-tunnel.sh
```

`serve-tunnel.sh` builds, starts the server, **health-checks it locally before minting a
tunnel** (a tunnel to a dead app is the 1033 trap), then verifies the **public edge**
end-to-end and prints `N/6 requests served 200`. It refuses to hand you a URL it could
not reach itself.

## Key

```bash
export STORYOS_KEY=...        # or put it in data/.key, mode 600
```

`data/.key` currently holds a **LOCALTEST-** key generated for verification. Replace or
delete it. It is never served (`/data/.key` → 404) and never embedded in the export.

## What was verified

| check | result |
|---|---|
| All 7 UI views render headless (jsdom) | no JS errors, no suspect content |
| Chapter 51 prose | 124 paragraphs, title once, footer + coverage folded |
| Vault | 653 files listed with sha256 |
| Unknown routes | **404**, not 401 (unknown ≠ protected) |
| `data/.key`, `data/audit.log` over HTTP | 404 |
| `/api/audit` without key | 401 |
| `POST /api/learn` with no key / wrong key | 401 / 401 |
| `POST /api/propose` (public) | 202, canon untouched |
| `POST /api/promote` with key | wrote `S0003`, **not** `D0003` |
| Gate | `WARN` — 11 drift findings, drafting permitted |

## Bugs found and fixed during the build

1. **Local rule ids shadowed canon ids.** A local counter starting at `D0001` collided with
   the real canon `D0001`. `next_local_id()` now reads the highest D-number visible anywhere
   (local + merged external) and allocates site rules in an `S0001…` series.
2. **Vault view crashed** — it read `$('#vq').value` before its own HTML was in the DOM.
3. **Chapter titles rendered twice** — the prose block kept its `# Chapter N —` line while
   the reader added its own H1. Now stripped at build time; the title is metadata.
4. **Drift scanner false positives** — `CANON_LEDGER.md` is a dated changelog; its
   `Current after Chapter32:` entries are correct receipts. Added section-context exemption.
5. **Drift scanner false negative** — `:` was treated as a sentence boundary, which severed
   `Live edge:` from the chapter number that follows it. The ZIP-root
   `NEXT_STEPS_FOR_CONTINUATION.md` (claiming Ch35) was invisible as a result.

## Gap you should know about

The ZIP you sent is the **project**, not the state layer:

- 0 `.card.md` files — the 38 lock cards live in `storyos-home/`
- 0 learned rules — `D0001`/`D0002` are not in any project file (`grep -rl D0001` → nothing)
- 0 StoryOS scripts — only `tools/perfect_continuation_skill_check.py` came across

So `build.py` alone reports `learned=0, locks=0`, which understates your canon. The build
therefore merges `data/external_state.json`, captured from your live checksummed site:
38 lock cards (37 bodies fetched and hash-verified) + D0001/D0002. Every merged record
carries `"provenance": "external"` so nothing is mistaken for a value derived from the
project's own files. Refresh it whenever you re-publish.

## Still blocking Chapter 52

Source **Chapter177 `1,000-year Purple Zoysia`** is not in the ZIP — only pointers to it.
Your own docs require it before `canon_coverage/Canon_Coverage_Chapter_52.md` can be
written. Reported missing, not invented.
