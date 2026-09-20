# START HERE — instructions for an AI agent

## Read order — mirror first, tunnel second
0. **CANONICAL POINTER — the only id worth caching** (it is rewritten every cycle and always
   names the current tunnel, the current mirror, and the last *measured* health):
   `https://paste.rs/njMwj`   ← stable; never re-derive it from anywhere else
1. **AUTHORITY — the verified mirror** (plain paste, no key, per-block checksums, survives
   session death): listed inside the pointer above, and live at `/soul_land_4/state.txt` when you can
   reach the tunnel. If you cannot reach the tunnel, take the mirror id from the pointer.
2. **FRESH READ — the live tunnel** (same content, re-derived on demand, but it drops for
   ~12s whenever its connector re-registers): `GET /api/gate/<project>` here.
   If the tunnel returns 530/1033, that is a detached connector — **fall back to the mirror,
   do not retry-loop and do not conclude the state is wrong.**

Trust ranking: the mirror tells you what was true at its timestamp. The tunnel tells you what
is true now, when it answers. When they disagree, the tunnel wins *if* it answers 200 —
otherwise use the mirror and say which one you used.

You have been given this URL, or these files. Work in order. Do not improvise state from memory,
from an earlier chat, or from any file older than what this page says.

```bash
curl -s  <site>/api/manifest.json     # index of every published file, with sha256 + size
curl -s  <site>/<project>/state.txt   # THE STATE: gate, live edge, locks, characters, firewalls
curl -s  <site>/api/gate/<project>    # the gate, re-run live (this is the authority)
```

## These are the only routes that exist
| route | who |
|---|---|
| `GET /` | portal, all projects, live gates |
| `GET /agents.md`, `GET /report.md` | this file; build summary |
| `GET /api/manifest.json` | file index + checksums |
| `GET /api/gate/<project>` | live gate JSON |
| `GET /api/projects` | gate + growth per project (paths redacted) |
| `GET /<project>/state.txt` `…/rules.md` `…/decisions.md` `…/state.json` | per-project views |
| `GET /<project>/locks/<card>.card.md` | individual lock cards |
| `GET /<project>/chapters/Chapter_NN.md` | the actual prose (recent tail; see `…/chapters/README.txt` for how far back it reaches) |
| `POST /api/learn/<project>` | **key required** — append a permanent rule |
| `POST /api/scan/<project>` | **key required** — re-derive state from files |

There is **no** `/health`, `/api`, `/api/state` or `/state` — a 404 there means wrong route, not a
dead site. A 530/1033 from Cloudflare means the tunnel connector dropped: ask the human to check
`grep -c "Registered tunnel connection" /tmp/storyos_cf.log`; retry once on a bare `000`.

Then obey, without exception:

1. **`GATE: FAIL` means do not draft prose.** Report the blocking findings and stop.
2. **Missing canon is reported as missing.** Never invented, never smoothed over, never
   "plausibly reconstructed". If a source scene is absent, say it is absent.
3. **Author knowledge is not character knowledge.** The Knowledge Firewall section states who
   may know what, and not before when. A character acting on unlearned lore is a defect even
   when the prose reads well.
4. **A receipt older than the newest active-branch receipt is evidence, not live state.**
   This project once had superseded audit files asserting a rejected chapter was live. Trust the
   gate's `live edge`.
5. **Do not nerf or inflate a character to force a plot.** Butterfly effects must grow from
   events that actually changed. One canon episode = one operational unit.
6. **Do not overwrite the project's own `foundation/`.** Generated state lives beside it.
7. When you learn a correction, state it as a rule with an enforcement token or regex, and hand
   it back so the human can run `storyos learn`. A note in chat evaporates; a learned rule blocks
   the next draft forever.
8. Power/level values must never appear as achieved fact if they are listed under BANNED VALUES.

If this page and a file you were told to read disagree: report both with their dates and wait.
Do not silently pick one — silently picking one is how a rejected branch came back before.

## Writing back (only if the human gave you a key)
Read state needs no key. To *change* it you must send the shared secret the human holds:

```bash
curl -s <site>/api/gate/<project>                 # readable: current gate
curl -s -X POST <site>/api/learn/<project>   -H "content-type: application/json" -H "X-StoryOS-Key: <KEY>"   -d '{"kind":"correction","what":"what went wrong","rule":"the rule now in force",
       "tokens":["SP526"],"patterns":["Rank\s*23\s*/\s*SP\s*156"]}'
curl -s -X POST <site>/api/scan/<project> -H "X-StoryOS-Key: <KEY>"   # re-derive from files
```

Without the key these answer `401`. Do not try to find another way in: a rule added by someone
who cannot be identified is how canon gets hijacked. If you have no key, hand the proposed rule
back to the human instead — that is a normal, expected outcome, not a failure.
