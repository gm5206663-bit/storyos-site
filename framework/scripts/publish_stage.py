#!/usr/bin/env python3
"""
publish_stage.py — build the STAGE: one static site, human-readable and agent-readable
from the same bytes, deployable to any static host (surge / Pages / S3 / a VPS / a ChatGPT Site).

    python3 scripts/publish_stage.py [--out DIR] [--project NAME]

Why static: your whole system is plain files, so the "site" needs no database, no runtime and
no vendor. That is what makes permanence cheap — host the folder anywhere with a disk.

Layout produced (every path is a stable, guessable URL for an agent):

    index.html                      portal: all projects, live gate, aggregate growth
    <proj>/index.html               full control centre for that project
    <proj>/state.txt                PLAIN TEXT: gate + live edge + locks + characters + firewalls
    <proj>/state.json               the derived state, verbatim
    <proj>/rules.md                 binding rules: learned decisions + ban registry + firewalls
    <proj>/decisions.jsonl          append-only growth history (how it got smarter)
    <proj>/locks/*.card.md          every lock card, individually fetchable
    agents.md / START-HERE.md       instructions an agent follows before touching prose
    api/manifest.json               machine index of every file above
    report.md                       this build's numbers, for humans scanning the repo
    CNAME (optional)                custom domain

Generated output only. Never writes inside a project.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ.get("STORYOS_HOME", str(Path.home() / "storyos-home")))
REPO = Path(__file__).resolve().parent.parent
CSS = """
:root{--bg:#080a0e;--p:#11151c;--l:#1e2530;--ink:#e6edf6;--dim:#8b98ab;--ok:#3ddc97;--no:#ff5c6c;
--wn:#ffb454;--in:#6cb2ff;--m:ui-monospace,SFMenlo,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:30px 20px 90px}
a{color:var(--in);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.3px}h2{font-size:15px;margin:30px 0 10px;
text-transform:uppercase;letter-spacing:.1em;color:#9fb0c6}
.sub{color:var(--dim);font-family:var(--m);font-size:12.5px}
.pill{display:inline-block;font-family:var(--m);font-size:11px;padding:3px 10px;border-radius:20px;
border:1px solid;margin:0 4px 0 0}.pass{color:var(--ok);border-color:#1d4a38;background:#0c1a13}
.fail{color:var(--no);border-color:#4a2028;background:#180c10}.warn{color:var(--wn);
border-color:#4a3a18;background:#161109}.info{color:var(--in);border-color:#22405f;background:#0d1725}
.card{background:var(--p);border:1px solid var(--l);border-radius:14px;padding:16px;margin:0 0 12px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.k{font-family:var(--m);font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:#5d6b7e}
.v{font-size:27px;font-weight:640;font-family:var(--m);margin-top:3px}
pre{font-family:var(--m);font-size:12px;color:#c7d3e2;background:#0b1017;border:1px solid var(--l);
border-radius:10px;padding:12px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td,th{text-align:left;padding:7px 9px;border-bottom:1px solid #1a212c}th{color:#8fa0b6;font-size:11px;
text-transform:uppercase;letter-spacing:.08em;font-family:var(--m)}
code{font-family:var(--m);font-size:.92em;background:#0d141c;padding:1.5px 5px;border-radius:5px}
.note{border-left:3px solid var(--in);padding:11px 15px;background:#0c1520;border-radius:0 12px 12px 0}
.rule{border-left:3px solid var(--ok);padding:9px 14px;background:#0b1410;border-radius:0 10px 10px 0;
margin:0 0 9px;font-size:14px}
.mono a{font-family:var(--m);font-size:12.5px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--l);color:#5d6b7e;font-size:12.5px}
"""


def esc(x) -> str:
    return str("" if x is None else x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page(title: str, body: str) -> str:
    return ("<!DOCTYPE html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><div class=wrap>"
            f"{body}<footer>StoryOS · generated {dt.datetime.now():%Y-%m-%d} · "
            "static build, no external assets · every number here is derived from project files, "
            "never hand-typed</footer></div></body></html>")


def reg() -> dict:
    return json.loads((HOME / "registry.json").read_text())["projects"]


def load(name: str) -> dict:
    entry = reg()[name]
    proj = Path(entry["path"])
    if not proj.is_absolute():
        proj = (Path.cwd() / proj).resolve()
    sd = HOME / "projects" / name / "state"
    st_f = sd / "STORYOS_STATE.json"
    if not st_f.exists():
        st_f = proj / "storyos" / "STORYOS_STATE.json"
    st = json.loads(st_f.read_text()) if st_f.exists() else {}
    df = HOME / "projects" / name / "decisions.jsonl"
    ds = [json.loads(x) for x in (df.read_text().splitlines() if df.exists() else []) if x.strip()]
    gate = subprocess.run([sys.executable, str(REPO / "tools" / "storyos_validate.py"),
                           "--project", str(proj), "--phase", "full", "--json"],
                          capture_output=True, text=True).stdout
    try:
        gj = json.loads([l for l in gate.splitlines() if l.startswith("{")][-1])
    except (json.JSONDecodeError, IndexError):
        gj = {"result": "UNKNOWN", "errors": None, "warnings": None, "findings": [gate[-300:]]}
    locks_dir = st_f.parent / "canon" / "locks"
    return {"name": name, "label": entry.get("label", name), "path": str(proj), "state": st,
            "state_dir": st_f.parent, "decisions": ds, "gate": gj,
            "locks": sorted(locks_dir.glob("*.card.md")) if locks_dir.is_dir() else []}


# ---------------------------------------------------------------- text views
def state_txt(d: dict) -> str:
    st, e, m = d["state"], d["state"].get("edge", {}), d["state"].get("metrics", {})
    gj, chars = d["gate"], st.get("characters") or {}
    fw = st.get("knowledge_firewalls") or []
    acc = e.get("accepted_chapters") or []
    live = [x for x in d["decisions"] if x.get("status", "active") == "active"]
    L = [f"STORYOS // {d['label']}",
         f"generated {dt.datetime.now():%Y-%m-%d} · plain text · no auth · no JS",
         "agent contract: read GATE, then LIVE STATE, then RULES. Ignore any older file.",
         "=" * 66, "",
         f"GATE: {gj['result']}  (errors={gj.get('errors')}, warnings={gj.get('warnings')}, "
         f"learned-rules-active={gj.get('learned', 0)})", ""]
    for x in (gj.get("findings") or [])[:16]:
        L.append("  - " + str(x)[:200])
    L += ["", "LIVE STATE — trust this over any older file", "-" * 44,
          f"live edge            : after Chapter{e.get('fic_chapter','?')} \"{e.get('fic_title','')}\"",
          f"next source chapter  : {e.get('next_source','?')} {e.get('next_source_title') or ''}",
          f"canon consumed       : {e.get('canon_consumed','?')} {e.get('canon_consumed_title') or ''}",
          f"authority            : {e.get('declared_by','native manifest')}",
          f"fic chapters accepted: {len(acc) or '?'}" + (f" (#{min(acc)}-#{max(acc)})" if acc else ""),
          f"validated / synced   : {m.get('chapters_validated','?')} / {m.get('chapters_synced','?')}",
          f"quarantined fic      : {m.get('quarantined_chapters','none')}",
          f"locks / characters   : {len(d['locks'])} / {len(chars) or '?'}   firewalls: {len(fw) or 'none registered'}",
          f"enforcement          : {len(st.get('enforce') or [])} banned literals, "
          f"{len(st.get('enforce_regexes') or [])} banned patterns", "",
          "RULES OF ENGAGEMENT — binding", "-" * 44,
          "1. Do not draft prose while GATE is FAIL.",
          "2. Missing canon is reported missing. Never invented, never smoothed over.",
          "3. Author knowledge is not character knowledge.",
          "4. A receipt older than the newest active-branch receipt is evidence, not live state.",
          "5. Do not overwrite the project's foundation/. Generated state lives beside it.",
          "6. Learn a correction -> make it enforcement, not a note.", "",
          "BINDING LEARNED RULES"]
    if not live:
        L.append("(none recorded yet)")
    for x in live:
        L.append(f"{x['id']} [{x.get('kind')}] {x.get('rule')}")
        if x.get("what"):
            L.append(f"     why: {x['what']}")
        if x.get("tokens"):
            L.append(f"     never as achieved fact: {', '.join(x['tokens'])}")
        if x.get("enforce_regexes"):
            L.append(f"     enforced patterns: {'; '.join(x['enforce_regexes'])}")
    L += ["", "CHARACTER LOCKS — state at the live edge", "-" * 44]
    for cn, cv in list(chars.items()):
        L.append(f"- {cn}: {str(cv.get('state') if isinstance(cv, dict) else cv)[:200]}")
    L += ["", "KNOWLEDGE FIREWALLS — who may know what, not before when", "-" * 44]
    if not fw:
        L.append("(none registered). A GAP, not permission to assume characters know nothing.")
    for k in fw:
        if isinstance(k, dict):
            L.append(f"- {k.get('topic','?')} [{k.get('state','?')}] who: {k.get('character','?')}")
            if k.get("earliest_valid_change"):
                L.append(f"    earliest valid change: {str(k['earliest_valid_change'])[:180]}")
        else:
            L.append(f"- {str(k)[:200]}")
    stale = st.get("stale_edge_claims") or []
    if stale:
        L += ["", f"STALE LIVE-EDGE CLAIMS IN THE ACTIVE TREE ({len(stale)})", "-" * 44,
              "Each asserts a live edge other than the real one. Treat the gate's live edge as the",
              "truth; these files are documentation that was never updated. Do NOT copy a number",
              "out of them into a draft.", ""]
        for c in sorted(stale, key=lambda x: -(x.get("chapters_behind") or 0))[:14]:
            L.append(f"- {c.get('file')}:{c.get('line')}  says after Chapter{c.get('claims_chapter')}"
                     f"  ({c.get('chapters_behind')} behind)")
            if c.get("excerpt"):
                L.append(f"      “{str(c['excerpt'])[:120]}”")
        if len(stale) > 14:
            L.append(f"- …and {len(stale) - 14} more (state.json: stale_edge_claims)")
    for x in (st.get("missing_inputs") or []):
        L += ["", f"MISSING INPUT — {x.get('id')}", "-" * 44,
              f"required      : {x.get('requires')}",
              f"state         : {x.get('state')}",
              f"blocks        : {x.get('blocks')}",
              f"do not        : {x.get('do_not')}",
              "This is reported as MISSING. It is not to be reconstructed, paraphrased from",
              "memory, or fetched from an unofficial mirror.", ""]
    sc = st.get("drift_scan_scope") or {}
    if sc:
        L += ["", "DRIFT-GUARD SCOPE (what the bans actually cover)", "-" * 44,
              f"scans  : {sc.get('target')}",
              f"opt-in : {sc.get('opt_in')}",
              f"excludes: {sc.get('never_scanned')}",
              f"sweep  : {(sc.get('edge_sweep') or 'n/a')}", ""]
    L += ["", f"BANNED VALUES ({len(st.get('enforce') or [])} literals)", "-" * 44,
          ", ".join((st.get("enforce") or [])[:60]) or "(none)", "",
          f"BANNED PATTERNS ({len(st.get('enforce_regexes') or [])})", "-" * 44,
          *[(f"- {r}") for r in (st.get("enforce_regexes") or [])], "",
          "END OF STATE. No chapter prose here by design — the human hands over prose.", ""]
    return "\n".join(L)


def rules_md(d: dict) -> str:
    st = d["state"]
    live = [x for x in d["decisions"] if x.get("status", "active") == "active"]
    fw = st.get("knowledge_firewalls") or []
    L = [f"# Binding rules — {d['label']}", "",
         f"Derived {dt.date.today().isoformat()}. An agent that violates these must rewrite, not justify.", "",
         "## Learned rules (enforced by the gate)", ""]
    if not live:
        L.append("_None yet._")
    for x in live:
        L += [f"### {x['id']} · {x.get('kind')}", f"**{x.get('rule')}**", "",
              f"- what happened: {x.get('what','')}",
              f"- never as achieved fact: {', '.join('`%s`' % t for t in (x.get('tokens') or [])) or '—'}",
              f"- enforced patterns: {', '.join('`%s`' % r for r in (x.get('enforce_regexes') or [])) or '—'}", ""]
    L += ["## Knowledge firewalls", ""]
    if not fw:
        L.append("_None registered — a gap to close, not a licence to assume._")
    for k in fw:
        if isinstance(k, dict):
            L.append(f"- **{k.get('topic')}** — {k.get('state')}, who: {k.get('character')}"
                     + (f"; earliest change: {k.get('earliest_valid_change')}"
                        if k.get("earliest_valid_change") else ""))
    L += ["", "## Banned values", "",
          *[f"- `{t}`" for t in (st.get("enforce") or [])], "",
          "## Banned patterns", "", *[f"- `{r}`" for r in (st.get("enforce_regexes") or [])], ""]
    return "\n".join(L)


def decisions_md(d: dict) -> str:
    ds = d["decisions"]
    L = [f"# Growth history — {d['label']}", "",
         f"{len(ds)} decisions. Append-only: a decision is never deleted, only superseded by a "
         f"later one that cites it. This file is the proof that the system accumulates.", "",
         "| id | date | kind | rule | enforceable |", "|---|---|---|---|---|"]
    for x in ds:
        n = len(x.get("tokens") or []) + len(x.get("enforce_regexes") or [])
        L.append(f"| {x['id']} | {x.get('date')} | {x.get('kind')} | {str(x.get('rule'))[:90]} | {n} |")
    L += ["", f"Total machine-enforced rules: "
          f"**{sum(len(x.get('tokens') or []) + len(x.get('enforce_regexes') or []) for x in ds if x.get('status','active')=='active')}**", ""]
    return "\n".join(L)


AGENTS_MD_TMPL = """# START HERE — instructions for an AI agent

## Read order — mirror first, tunnel second
0. **CANONICAL POINTER — the only id worth caching** (it is rewritten every cycle and always
   names the current tunnel, the current mirror, and the last *measured* health):
   `https://paste.rs/njMwj`   ← stable; never re-derive it from anywhere else
1. **AUTHORITY — the verified mirror** (plain paste, no key, per-block checksums, survives
   session death): listed inside the pointer above, and live at `{MIRROR_PATH}` when you can
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
| `GET /LAWS.md` | the adopted universal laws: authority order, twelve locks, pipeline, firewall states, leak paths |
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
curl -s -X POST <site>/api/learn/<project> \
  -H "content-type: application/json" -H "X-StoryOS-Key: <KEY>" \
  -d '{"kind":"correction","what":"what went wrong","rule":"the rule now in force",
       "tokens":["SP526"],"patterns":["Rank\\s*23\\s*/\\s*SP\\s*156"]}'
curl -s -X POST <site>/api/scan/<project> -H "X-StoryOS-Key: <KEY>"   # re-derive from files
```

Without the key these answer `401`. Do not try to find another way in: a rule added by someone
who cannot be identified is how canon gets hijacked. If you have no key, hand the proposed rule
back to the human instead — that is a normal, expected outcome, not a failure.
"""


def portal(rows: list[dict]) -> str:
    tot_dec = sum(len(r["decisions"]) for r in rows)
    tot_enf = sum(len(x.get("tokens") or []) + len(x.get("enforce_regexes") or [])
                  for r in rows for x in r["decisions"] if x.get("status", "active") == "active")
    tot_locks = sum(len(r["locks"]) for r in rows)
    cards = []
    for r in rows:
        gj, e = r["gate"], r["state"].get("edge", {})
        cls = {"PASS": "pass", "FAIL": "fail"}.get(gj["result"], "warn")
        cards.append(f"""<div class=card>
<table><tr><td style=width:34%>
<div class=k>project</div><div style="font-size:17px;font-weight:600"><a href="{esc(r['name'])}/index.html">{esc(r['label'])}</a></div>
<div class=sub>after Chapter{esc(e.get('fic_chapter','?'))} · next source {esc(e.get('next_source','?'))}</div>
</td><td>
<span class="pill {cls}">GATE {esc(gj['result'])}</span>
<span class="pill warn">{gj.get('errors')} errors</span>
<span class="pill info">{gj.get('warnings')} warnings</span>
<span class="pill info">{len([x for x in r['decisions'] if x.get('status','active')=='active'])} learned</span>
<div class=sub style="margin-top:8px">
<a href="{esc(r['name'])}/state.txt">state.txt</a> ·
<a href="{esc(r['name'])}/state.json">state.json</a> ·
<a href="{esc(r['name'])}/rules.md">rules.md</a> ·
<a href="{esc(r['name'])}/decisions.md">growth</a> ·
{len(r['locks'])} lock cards</div></td></tr></table></div>""")
    body = f"""<h1>StoryOS</h1>
<div class=sub>canon discipline as an executable layer · {len(rows)} project(s) · static build</div>
<div style="margin:16px 0"><a class="pill info" href="agents.md">agents.md — read me first</a>
<a class="pill info" href="api/manifest.json">api/manifest.json</a>
<a class="pill info" href="report.md">report.md</a></div>
<div class=grid>
<div class=card><div class=k>projects</div><div class=v>{len(rows)}</div></div>
<div class=card><div class=k>decisions recorded</div><div class=v>{tot_dec}</div></div>
<div class=card><div class=k>machine-enforced rules</div><div class=v>{tot_enf}</div></div>
<div class=card><div class=k>lock cards</div><div class=v>{tot_locks}</div></div>
</div>
<h2>Projects</h2>{''.join(cards) if cards else '<p class=sub>none registered</p>'}
<h2>What this is</h2>
<p>A StoryOS page is not a summary of the project — it is <b>derived from</b> it. Every number was
read out of the project's own files by <code>scan_project.py</code>, then re-checked by
<code>storyos_validate.py</code>. Hand-typed dashboards drift silently; this one cannot, because
regenerating it either reproduces the state or fails loudly.</p>
<div class=note><b>If you are an agent:</b> fetch <a href="agents.md">agents.md</a> and
<code>&lt;project&gt;/state.txt</code>. Do not draft prose unless that file says <code>GATE: PASS</code>.</div>"""
    return page("StoryOS", body)


def proj_page(d: dict) -> str:
    st, e, m = d["state"], d["state"].get("edge", {}), d["state"].get("metrics", {})
    gj, chars = d["gate"], st.get("characters") or {}
    fw = st.get("knowledge_firewalls") or []
    live = [x for x in d["decisions"] if x.get("status", "active") == "active"]
    cls = {"PASS": "pass", "FAIL": "fail"}.get(gj["result"], "warn")
    rows_ch = "".join(f"<tr><td><b>{esc(c)}</b></td><td>{esc(cv.get('state') if isinstance(cv, dict) else cv)}</td>"
                      f"<td>{esc(cv.get('rank') if isinstance(cv, dict) else '')} / "
                      f"{esc(cv.get('sp') if isinstance(cv, dict) else '')}</td></tr>"
                      for c, cv in list(chars.items()))
    rows_fw = "".join(f"<tr><td>{esc(k.get('topic'))}</td><td>{esc(k.get('state'))}</td>"
                      f"<td>{esc(k.get('character'))}</td></tr>"
                      for k in fw if isinstance(k, dict)) or '<tr><td colspan=3 class=sub>none registered — a gap to close</td></tr>'
    rows_dec = "".join(f"<tr><td>{esc(x['id'])}</td><td>{esc(x.get('date'))}</td>"
                       f"<td>{esc(x.get('kind'))}</td><td>{esc(x.get('rule'))}</td></tr>"
                       for x in live) or '<tr><td colspan=4 class=sub>nothing learned yet</td></tr>'
    rows_locks = "".join(f"<tr><td><a href=\"locks/{esc(f.name)}\">{esc(f.stem)}</a></td></tr>"
                         for f in d["locks"][:80]) or '<tr><td class=sub>none</td></tr>'
    body = f"""<div class=sub><a href="../">← all projects</a></div>
<h1>{esc(d['label'])}</h1>
<div class=sub>path on the build machine: <code>{esc(d['path'])}</code> · derived, never hand-typed</div>
<div style="margin:14px 0"><span class="pill {cls}">GATE {esc(gj['result'])}</span>
<span class="pill warn">{gj.get('errors')} errors</span><span class="pill info">learned rules active: {gj.get('learned',0)}</span></div>
<pre>{esc(chr(10).join(str(x)[:200] for x in (gj.get('findings') or [])) or 'no findings')}</pre>
<div class=grid>
<div class=card><div class=k>live edge</div><div class=v>Ch{esc(e.get('fic_chapter','?'))}</div>
<div class=sub>{esc(e.get('fic_title',''))}</div></div>
<div class=card><div class=k>next source</div><div class=v>{esc(e.get('next_source','?'))}</div>
<div class=sub>{esc(e.get('next_source_title','') or '')}</div></div>
<div class=card><div class=k>canon consumed</div><div class=v>{esc(e.get('canon_consumed','?'))}</div></div>
<div class=card><div class=k>locks</div><div class=v>{len(d['locks'])}</div></div>
<div class=card><div class=k>characters</div><div class=v>{len(chars)}</div></div>
<div class=card><div class=k>firewalls</div><div class=v>{len(fw)}</div></div>
<div class=card><div class=k>banned literals</div><div class=v>{len(st.get('enforce') or [])}</div></div>
<div class=card><div class=k>learned decisions</div><div class=v>{len(live)}</div></div>
</div>
<h2>Character locks</h2><table><tr><th>character</th><th>state at live edge</th><th>rank / sp</th></tr>{rows_ch}</table>
<h2>Knowledge firewalls</h2><table><tr><th>topic</th><th>state</th><th>who</th></tr>{rows_fw}</table>
<h2>Binding learned rules</h2>
{''.join(f'<div class=rule><b>{esc(x["id"])}</b> [{esc(x.get("kind"))}] {esc(x.get("rule"))}'
         + (f'<div class=sub>never as achieved fact: {esc(", ".join(x.get("tokens") or []))}</div>' if x.get("tokens") else "")
         + '</div>' for x in live)}
<h2>Growth — decisions recorded</h2>
<table><tr><th>id</th><th>date</th><th>kind</th><th>rule</th></tr>{rows_dec}</table>
<h2>Lock cards ({len(d['locks'])})</h2><table class=mono>{rows_locks}</table>
<h2>Raw views for agents</h2>
<p><a href="state.txt">state.txt</a> (plain text, one fetch) · <a href="state.json">state.json</a> ·
<a href="rules.md">rules.md</a> · <a href="decisions.jsonl">decisions.jsonl</a></p>"""
    return page(f"StoryOS — {d['label']}", body)


def emit_gate_report(out: Path, name: str) -> dict | None:
    """Run the validator and store its verdict as files inside the stage.

    An agent must be able to check the gate WITHOUT trusting my prose and without a live tunnel,
    so the verdict is published as data: JSON for machines, text for humans, both mirrored.
    """
    repo = Path(__file__).resolve().parents[1]
    proj = REPO.parent / "projects" / name
    if not proj.is_dir():
        return None
    res = subprocess.run([sys.executable, str(repo / "tools" / "storyos_validate.py"),
                          "--project", str(proj), "--phase", "full"],
                         capture_output=True, text=True, cwd=str(REPO.parent), timeout=600)
    blob = res.stdout + res.stderr
    verdict = "PASS" if "STORYOS_VALIDATE: PASS" in blob else "FAIL"
    numbers = {}
    for k in ("errors", "warnings", "learned-rules-active"):
        m = re.search(rf"{k}[=:]\s*(\d+)", blob)
        if m:
            numbers[k] = int(m.group(1))
    # Read the EDGE from the structured state, not by regexing a human report: my first
    # version's fallback matched "NEXT CHAPTER: Chapter52" and published "live edge after
    # Chapter52" — one chapter ahead of truth, i.e. this tool would have created the very
    # class of stale claim it exists to detect. Parsing prose is not verification.
    def _edge_from_state():
        try:
            stf = out / name / "state.json"
            if stf.exists():
                return (json.loads(stf.read_text(encoding="utf-8")).get("edge") or {}).get(
                    "fic_chapter")
        except (OSError, ValueError):
            return None
        return None

    edge_ch = _edge_from_state()
    if edge_ch is None:
        # Re-derive from the native manifest instead of parsing prose. The regex fallback below was
        # removed on purpose: it matched the validator's "NEXT CHAPTER:" line, which reports
        # edge+1, and would have published a live edge one chapter ahead of truth.
        try:
            scan = REPO / "scripts" / "scan_project.py"
            inst = HOME / "projects" / name / "state"
            subprocess.run([sys.executable, str(scan),
                            str(REPO.parent / "projects" / name / "audits"),
                            str(REPO.parent / "projects" / name), str(inst)],
                           capture_output=True, text=True, timeout=900)
            (out / name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(inst / "STORYOS_STATE.json", out / name / "state.json")
        except (OSError, subprocess.SubprocessError) as e:
            print(f"  gate: state re-derivation failed for {name}: {e}")
        edge_ch = _edge_from_state()
    if edge_ch is None:
        raise SystemExit(f"emit_gate_report: cannot read the live edge for {name} from structured "
                         f"state — refusing to infer it from validator prose")
    edge = int(edge_ch)

    payload = {"project": name, "result": verdict, **numbers,
               "exit": res.returncode,
               # counted from the files actually on disk: emit_gate_report() is a different
               # scope, where the build-local "staged" would be a NameError that takes the
               # whole gate step down on the next publish.
               "staged_prose_files": (len(list((out / name / "chapters").glob("Chapter_*.md")))
                                      if (out / name / "chapters").is_dir() else 0),
               "live_edge_chapter": edge,
               "stdout_tail": blob.strip().splitlines()[-14:],
               "generated_by": "publish_stage.emit_gate_report"}
    (out / name).mkdir(parents=True, exist_ok=True)
    (out / name / "gate.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out / "api" / "gate").mkdir(parents=True, exist_ok=True)
    (out / "api" / "gate" / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n",
                                                        encoding="utf-8")
    (out / name / "gate.txt").write_text(
        f"StoryOS gate — {name}\nresult: {verdict}   "
        f"errors={numbers.get('errors')} warnings={numbers.get('warnings')} "
        f"learned_rules={numbers.get('learned-rules-active')}\n"
        f"live edge: after Chapter{payload['live_edge_chapter']}\n\n"
        "Machine copy: api/gate/%s.json (also mirrored). Recompute with:\n"
        "  python3 storyos/tools/storyos_validate.py --project projects/%s --phase full\n"
        % (name, name), encoding="utf-8")
    return payload


def build(out: Path, only: str | None) -> Path:
    names = [only] if only else list(reg())
    if out.exists():
        shutil.rmtree(out)          # ← this wipe is why hand-placed files vanished
    (out / "api").mkdir(parents=True)
    rows, manifest = [], {"generated": dt.datetime.now().isoformat(timespec="seconds"),
                          "system": "storyos", "schema": "storyos-site/1",
                          "agent_entrypoint": "agents.md", "projects": {}}
    for n in names:
        d = load(n)
        rows.append(d)
        pd = out / n
        (pd / "locks").mkdir(parents=True)
        (pd / "state.txt").write_text(state_txt(d), encoding="utf-8")
        stsrc = d["state_dir"] / "STORYOS_STATE.json"
        if stsrc.exists():
            shutil.copy2(stsrc, pd / "state.json")
        (pd / "rules.md").write_text(rules_md(d), encoding="utf-8")
        (pd / "decisions.md").write_text(decisions_md(d), encoding="utf-8")
        dj = HOME / "projects" / n / "decisions.jsonl"
        if dj.exists():
            shutil.copy2(dj, pd / "decisions.jsonl")
        # Prose on the stage. An agent that fetches this URL has nothing else, so a state
        # file without the story text makes it rewrite canon from a summary — the exact
        # failure this system exists to prevent. STORYOS_STAGE_CHAPTERS=0 disables the tail.
        tail_n = int(os.environ.get("STORYOS_STAGE_CHAPTERS", "8"))
        ch_src = Path(d["path"]) / "chapters"
        staged = []
        if tail_n > 0 and ch_src.is_dir():
            def _cnum(f):
                m = re.search(r"Chapter_(\d+)", f.name)
                return int(m.group(1)) if m else -1

            # Keep only true chapter files: unnumbered helpers (CHAPTER_TEMPLATE.md) must
            # never be staged as prose. Matching is on the NUMBER _cnum extracted, not a
            # second regex over the name — an earlier draft of this line used [1-9]\d* and
            # silently dropped Chapter_01..09, whose zero padding it could not match. Nine
            # chapters vanished from the published set and the count looked self-consistent.
            allch = sorted((f for f in ch_src.glob("*.md") if _cnum(f) > 0), key=_cnum)
            for f in allch[-tail_n:]:
                (pd / "chapters").mkdir(exist_ok=True)
                shutil.copy2(f, pd / "chapters" / f.name)
                staged.append(f.name)
            if staged:
                head = ("Story prose - last " + str(len(staged)) + " of " + str(len(allch)) +
                        " accepted chapters (earliest here: " + staged[0] + ").\n"
                        "Chapters before this tail are still in the source project; read them "
                        "before plotting anything that depends on their detail. Do NOT rebuild "
                        "the arc from state.txt alone.\n")
                (pd / "chapters" / "README.txt").write_text(head, encoding="utf-8")
        for f in d["locks"]:
            shutil.copy2(f, pd / "locks" / f.name)
        local_site = d["state_dir"] / "site" / "index.html"
        (pd / "index.html").write_text(proj_page(d), encoding="utf-8")
        manifest["projects"][n] = {
            "label": d["label"], "gate": d["gate"]["result"],
            "errors": d["gate"].get("errors"), "warnings": d["gate"].get("warnings"),
            "live_edge": {"fic_chapter": d["state"].get("edge", {}).get("fic_chapter"),
                          "fic_title": d["state"].get("edge", {}).get("fic_title"),
                          "next_source": d["state"].get("edge", {}).get("next_source")},
            "counts": {"locks": len(d["locks"]), "decisions": len(d["decisions"]),
                       "characters": len(d["state"].get("characters") or {}),
                       "firewalls": len(d["state"].get("knowledge_firewalls") or []),
                       "banned_literals": len(d["state"].get("enforce") or []),
                       "banned_patterns": len(d["state"].get("enforce_regexes") or [])},
            "files": {}}
        for f in sorted(pd.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(out))
                manifest["projects"][n]["files"][rel] = {
                    "bytes": f.stat().st_size,
                    "sha256": hashlib.sha256(f.read_bytes()).hexdigest()[:16]}
    (out / "index.html").write_text(portal(rows), encoding="utf-8")
    def _read(f):
        try:
            v = (HOME / f).read_text().strip()
            return v if v.startswith("http") else "not yet published — ask the human"
        except OSError:
            return "not yet published — ask the human"

    # Deliberate: the tunnel-relative mirror PATH is stable, the paste ID is not. Baking a fresh
    # ID in here on every build is what made this document chase itself in circles — the canonical
    # pointer (a fixed ID the human publishes once) is the only cached address in this file.
    md = AGENTS_MD_TMPL.replace("{MIRROR_PATH}", "/soul_land_4/state.txt")
    (out / "agents.md").write_text(md, encoding="utf-8")
    (out / "START-HERE.md").write_text(md, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    rep = [f"# StoryOS stage build report", "", f"Generated {dt.datetime.now():%Y-%m-%d} · {len(rows)} project(s)", "",
           "| project | gate | errors | locks | chars | firewalls | decisions | enforced |",
           "|---|---|---|---|---|---|---|---|"]
    for d in rows:
        enf = sum(len(x.get("tokens") or []) + len(x.get("enforce_regexes") or [])
                  for x in d["decisions"] if x.get("status", "active") == "active")
        rep.append(f"| {d['name']} | {d['gate']['result']} | {d['gate'].get('errors')} | "
                   f"{len(d['locks'])} | {len(d['state'].get('characters') or {})} | "
                   f"{len(d['state'].get('knowledge_firewalls') or [])} | {len(d['decisions'])} | {enf} |")
    (out / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    (out / "api" / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Mutable copies at FIXED paths. paste.rs mints a new id per publish and refuses PUT
    # (verified 404), so no paste can be "the address that always updates" — the tunnel can.
    # Redacted public twin. The raw record names the connector log path and reports the local
    # origin — neither belongs at a public address. Verified: the unredacted copy leaked
    # "/tmp/storyos_cf.log" and origin_local until this existed.
    try:
        hsrc = HOME / "health.json"
        if hsrc.exists():
            hd = json.loads(hsrc.read_text())
            pub = {k: hd.get(k) for k in ("checked_at", "served_200", "probes", "availability_pct",
                                          "edge_failures_530", "transport_failures",
                                          "longest_outage_s")}
            pub["connector"] = {"registered": hd.get("connector", {}).get("registered"),
                                "lost_edge_events": hd.get("connector", {}).get("lost")}
            pub["verdict"] = ("HEALTHY" if (pub.get("availability_pct") or 0) >= 99
                              else ("DOWN_FOR_PROBES" if not pub.get("served_200") else "DEGRADED"))
            pub["note"] = ("public redacted view; origin status, host paths and the connector log "
                           "are withheld. The human reads those from $STORYOS_HOME/health.json")
            (out / "api" / "health.json").write_text(json.dumps(pub, indent=2) + "\n",
                                                    encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass
    # Adopted universal laws: an agent arriving here with nothing else most needs the
    # authority ladder, because absent it, it invents precedence.
    for extra in (HOME / "LAWS.md", REPO / "LAWS.md"):
        if extra.exists():
            try:
                shutil.copy2(extra, out / "LAWS.md")
            except OSError:
                pass
            break
    for src, dst in ((Path("/tmp/storyos_watchdog/pointer.txt"), out / "pointer.md"),):
        try:
            if src.exists():
                shutil.copy2(src, dst)
        except OSError:
            pass
    (out / "api" / "README.json").write_text(json.dumps({
        "read_order": ["GET /api/health.json   measured — is the tunnel up right now?",
                       "GET /<project>/state.txt the state an agent must obey",
                       "GET /api/manifest.json  index + sha256 of every published file"],
        "no_such_routes": ["/health", "/api", "/api/state", "/state"],
        "if_this_url_fails": "a 530/1033 means the connector detached, not that state changed; "
                             "fall back to the mirror paste named in /pointer.md",
        "key_policy": "reads open; POST /api/learn and /api/scan require X-StoryOS-Key",
        "generated": dt.datetime.now().isoformat(timespec="seconds")}, indent=2) + "\n",
        encoding="utf-8")
    for _n in names:
        try:
            emit_gate_report(out, _n)
        except Exception as _e:                          # a failed probe must not block a build
            print(f"  gate report for {_n}: NOT written ({_e})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO.parent / "storyos-site"))
    ap.add_argument("--project")
    ap.add_argument("--publish", action="store_true",
                    help="after building: publish the mirror, then refresh the pointer (that order)")
    a = ap.parse_args()
    out = build(Path(a.out).expanduser(), a.project)
    # Correct sequence, because ordering is the whole lesson here:
    #   stage on disk  ->  mirror (embeds the FINAL agents.md)  ->  pointer (quotes the NEW mirror)
    # Anything else makes a document name a superseded one, which is what an outside agent caught.
    if getattr(a, "publish", False):
        for script in ("publish_mirror.py",):
            f = REPO / "scripts" / script
            if f.exists():
                r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True,
                                   timeout=240)
                line = (r.stdout or r.stderr).strip().splitlines()
                print("  " + (line[-1] if line else f"{script}: no output"))
        h = REPO / "tools" / "health.py"
        if h.exists():
            r = subprocess.run([sys.executable, str(h), "--publish", "--n", "6", "--sleep", "2"],
                               capture_output=True, text=True, timeout=240)
            for l in (r.stdout or "").splitlines():
                if "pointer" in l or "HEALTH" in l or "public path" in l:
                    print("  " + l.strip())
    files = [f for f in out.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    print(f"stage built: {out}")
    print(f"  {len(files)} files · {total/1024:.0f} KB · deployable to any static host")
    print(f"  entry: index.html · agents.md · api/manifest.json")
