#!/usr/bin/env python3
"""
make_bundle.py — build ONE uploadable artifact that gives a receiving agent everything.

    python3 scripts/make_bundle.py --out /home/user/StoryOS_Agent_Bundle.zip [--no-prose]

Inside the zip (relative, so it works wherever it is unzipped):

    START_HERE.md              12 lines: what to read, what to run, what is forbidden
    AGENT_BRIEF.md             binding learned rules + live state + the contract
    ENGINE.md                  what the system is, and its honest limits
    .storyos-home/             registry + append-only decisions + lock cards + derived state
    storyos/                   the engine itself (tools, scripts, templates, docs)
    projects/<name>/           the real project — chapters, canon, foundation, audits
                               (--no-prose omits chapters/, keeping it safe to share)

The bundle is self-checking: the agent runs one command and the validator either passes or
names the exact file and line that is wrong. Verified by building it and running it from a
clean directory on a path that does not exist on the author's machine.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HOME = Path(os.environ.get("STORYOS_HOME", str(Path.home() / "storyos-home")))
REPO = Path(__file__).resolve().parent.parent      # storyos/


def reg() -> dict:
    return json.loads((HOME / "registry.json").read_text())


def build(out: Path, prose: bool, only: str | None) -> Path:
    stage = Path(tempfile.mkdtemp(prefix="storyos_bundle_"))
    root = stage / "storyos-bundle"
    (root / "projects").mkdir(parents=True)
    (root / "storyos").mkdir(parents=True)
    (root / ".storyos-home" / "projects").mkdir(parents=True)

    # 1. the engine (small, and needed for --selftest / future `learn`)
    shutil.copytree(REPO / "tools", root / "storyos" / "tools")
    shutil.copytree(REPO / "scripts", root / "storyos" / "scripts")
    for f in ("templates", "AGENT_ONBOARDING.md", "README.md"):
        s = REPO / f
        if s.is_dir():
            shutil.copytree(s, root / "storyos" / f)
        elif s.exists():
            shutil.copy2(s, root / "storyos" / f)
    for junk in list((root / "storyos").rglob("__pycache__")):
        shutil.rmtree(junk, ignore_errors=True)
    for junk in list((root / "storyos").rglob("*.pyc")):
        junk.unlink(missing_ok=True)

    # 2. projects + their accumulated state
    entries = {k: v for k, v in reg()["projects"].items() if not only or k == only}
    for name, e in entries.items():
        src = Path(e["path"])
        dst = root / "projects" / name
        # Pre-repair backup snapshots (*_before/, *snapshot*/) hold superseded values — one of
        # them asserted "live edge after Chapter35" 16 chapters behind reality. My scanner
        # correctly excluded them from analysis while this copy function shipped all 325 of them
        # to another agent. Exclusion in one place is not exclusion: every consumer must filter.
        # copytree's ignore callable is fnmatch-style: ignore(dir_path, names) -> names to SKIP.
        # Passing it a *pattern* (the glob形式) silently ignores nothing — that bug shipped all
        # 325 pre-repair backup files straight to another agent, so filtering is verified after
        # the copy, not assumed from the API.
        # Only DIRECTORIES are excluded — a receipt whose NAME contains such a word (e.g.
        # TMP_DEEP_STALE_SCAN_2026-09-17_…md) is a normal audit file and stays. An earlier
        # version of the self-check matched the whole path and cried wolf on those.
        BAD_DIR = re.compile(r"(?:^|[_\-])(before|snapshot|backup|archive|tmp|cache)(?:$|[_\-])",
                            re.I)
        SKIP_EXT = (".pyc", ".pyo", ".zip")

        def _ignore(_dir, names):
            out = set()
            for nm in names:
                fp = Path(_dir) / nm
                if fp.is_dir() and BAD_DIR.search(nm):
                    out.add(nm)
                elif nm.endswith(SKIP_EXT) or nm == "__pycache__":
                    out.add(nm)
            return out

        shutil.copytree(src, dst, ignore=_ignore)
        leaked = [str(x.relative_to(dst)) for x in dst.rglob("*.md")
                  if any(BAD_DIR.search(part) for part in x.relative_to(dst).parts[:-1])]
        if leaked:
            raise SystemExit(f"make_bundle: FILTER FAILED, {len(leaked)} backup-dir files still "
                             f"shipped, e.g. {leaked[0]}")
        print(f"  filter verified: no *_before/ or archive/ files present in the copy")
        (dst / "EXCLUDED_FROM_THIS_BUNDLE.md").write_text(
            "# What this bundle deliberately omits\n\n"
            "`audits/*_before/` and `archive/` directories were excluded: they are dated pre-repair\n"
            "backups whose numbers were superseded (e.g. `Live edge: after Chapter35`, Yan Rank34/SP689,\n"
            "Dawnflame 2,800). Reading them as current state is the exact failure StoryOS exists to\n"
           " prevent. The live edge in this bundle is authoritative; nothing outside it overrides\n"
            " `foundation/CURRENT_STATE_MANIFEST.json`.\n", encoding="utf-8")
        if not prose:
            for sub in ("chapters",):
                shutil.rmtree(dst / sub, ignore_errors=True)
        # accumulated state: decisions, lock cards, derived mirrors
        sh = HOME / "projects" / name
        if sh.exists():
            shutil.copytree(sh, root / ".storyos-home" / "projects" / name)
        # the derived state also lives inside the project's storyos/ so the validator
        # finds it without any registry lookup
        st = sh / "state"
        if st.is_dir():
            (dst / "storyos").mkdir(exist_ok=True)
            shutil.copytree(st, dst / "storyos", dirs_exist_ok=True)

    # 3. a registry whose paths resolve *inside the bundle*
    (root / ".storyos-home" / "registry.json").write_text(json.dumps(
        {"projects": {n: {"path": f"projects/{n}", "label": v.get("label", n),
                          "added": v.get("added", ""), "relative": True}
                      for n, v in entries.items()},
         "default": next(iter(entries), None),
         "bundled": dt.datetime.now().isoformat(timespec="seconds")}, indent=2))

    # 4. the three read-first documents
    total_dec = 0
    for name in entries:
        f = root / ".storyos-home" / "projects" / name / "decisions.jsonl"
        if f.exists():
            total_dec += len([x for x in f.read_text().splitlines() if x.strip()])
    names = ", ".join(entries)
    # The bundle used to contain the ENGINE and the CANON but not what was actually PUBLISHED —
    # no state.txt, no agents.md, no gate verdict. An agent holding only the zip could run the
    # validator but could not see the answers, so it re-derived everything or, worse, guessed.
    # A "self-contained artifact" must carry its own published output plus its verifiability.
    site = Path(os.environ.get("STORYOS_SITE_DIR", str(REPO.parent / "storyos-site")))
    pub = root / "PUBLISHED"
    if site.is_dir():
        shutil.copytree(site, pub / "site", ignore=shutil.ignore_patterns("__pycache__"))
    mirror_txt = REPO.parent / "storyos-mirror.txt"
    if mirror_txt.exists():
        shutil.copy2(mirror_txt, pub / "mirror.txt")
    (pub / "README.md").write_text(
        "# What this is\n\n"
        "A snapshot of everything published at the live address, copied at bundle build time.\n\n"
        "- `site/agents.md`      — the contract, route table and rules of engagement\n"
        "- `site/<proj>/state.txt` — state to obey (gate, locks, firewalls, banned values, "
        "**stale edge claims**, **missing inputs**)\n"
        "- `site/<proj>/gate.txt`, `site/api/gate/<proj>.json` — the validator verdict as data\n"
        "- `site/api/health.json` — measured availability of the live tunnel **at snapshot time**; "
        "re-read it live, do not trust this copy for liveness\n"
        "- `mirror.txt`          — the same five-plus documents in the frozen byte-verifiable "
        "mirror format (`### FILE: <path>  (<N> bytes, sha256[:16]=<16 hex>)`)\n\n"
        "Verify rather than trust: for each mirror block, the bytes between its header and the "
        "next one are the file; `sha256` of them must match `sha256[:16]`. Or recompute "
        "everything yourself with `python3 storyos/tools/storyos_validate.py --project "
        "projects/<name> --phase full`.\n", encoding="utf-8")
    (root / "START_HERE.md").write_text(f"""# Start here. Do exactly this.

0. Read `PUBLISHED/site/agents.md` and `PUBLISHED/site/<project>/state.txt` — that is
   the published answer set; this bundle carries a snapshot of it so you are not
   dependent on a live tunnel.

**{dt.date.today().isoformat()} · StoryOS bundle · project(s): {names}**
**Decisions on record: {total_dec} · learned enforcement is live and will fail your draft.**

```bash
cd "$(dirname "$0")"                     # you are in storyos-bundle/
export STORYOS_HOME="$(pwd)/.storyos-home"

# 1. verify the checker itself works before trusting it (~2s)
python3 storyos/tools/storyos_validate.py --selftest

# 2. run the gate on the live project — this is your state, not a summary
python3 storyos/tools/storyos_validate.py --project projects/<name> --phase pre

# 3. read the live state
cat .storyos-home/projects/<name>/state/STATUS_PANEL.md
```

Then, in order: `AGENT_BRIEF.md` → `projects/<name>/HANDOFF.md` →
`projects/<name>/foundation/STATUS_PANEL.md` → `projects/<name>/foundation/NO_MISTAKE_LIVE_RULES.md`.

**The gate is the state of truth. A file that disagrees with the gate is stale, not an option.**

## Rules that are already binding (violating these means rewrite)
1. Do **not** draft prose until `--phase pre` prints `GATE: clear`.
2. Missing canon is reported as **missing**. Never invented, never smoothed over.
3. Author knowledge ≠ character knowledge. Respect the Knowledge Firewall.
4. Do not overwrite `projects/*/foundation/` — generated state belongs in `.storyos-home/`.
5. A receipt older than the newest active-branch receipt is **evidence, not live state**.
6. When you learn a correction, run `storyos learn` (see AGENT_BRIEF.md) so it becomes enforcement.

## Scope note (read before reporting a PASS as proof)
The drift guard scans the **story body** of `projects/<name>/chapters/*.md` — text before the
`---` + `## Footer` marker — because footers legitimately enumerate deleted values as warnings.
It does NOT scan whole-project text by default (that produced 293 false errors and taught people
to ignore the gate). To force a specific file: `--phase post --files chapters/Chapter_52.md`.

## If the gate disagrees with you
Do not edit the project to make it pass. Report both readings with their file and date, and wait.
""", encoding="utf-8")

    # agent brief per project, merged
    brief = [f"# Agent Brief — StoryOS bundle",
             f"Built {dt.datetime.now():%Y-%m-%d %H:%M} · {len(entries)} project(s) · "
             f"{total_dec} decisions recorded", ""]
    for name, e in entries.items():
        d = root / ".storyos-home" / "projects" / name / "decisions.jsonl"
        ds = [json.loads(x) for x in (d.read_text().splitlines() if d.exists() else []) if x.strip()]
        sf = root / ".storyos-home" / "projects" / name / "state" / "STORYOS_STATE.json"
        st = json.loads(sf.read_text()) if sf.exists() else {}
        ed = st.get("edge", {})
        m = st.get("metrics", {})
        brief += [f"## {name} — {e.get('label', name)}", "",
                  f"- live edge: **after Chapter{ed.get('fic_chapter','?')} “{ed.get('fic_title','')}”**",
                  f"- next source chapter: **{ed.get('next_source','?')}**",
                  f"- canon consumed: **{m.get('canon_consumed','?')}** · chapters: {m.get('chapters','?')}"
                  f" · locks: {m.get('lock_cards','?')} · characters: {m.get('characters','?')}"
                  f" · firewalls: {m.get('firewalls','?')}",
                  f"- decisions: {len(ds)} · enforceable rules: "
                  f"{sum(len(x.get('tokens') or []) + len(x.get('enforce_regexes') or []) for x in ds if x.get('status','active')=='active')}",
                  "", "### Learned rules (binding on every draft)"]
        live = [x for x in ds if x.get("status", "active") == "active"]
        if not live:
            brief.append("_None yet — follow the project's own foundation/ and codex/._")
        for x in live:
            brief.append(f"- **{x['id']}** ({x.get('kind')}): {x.get('rule')}")
            if x.get("what"):
                brief.append(f"  - why: {x['what']}")
            if x.get("tokens"):
                brief.append(f"  - must never appear as achieved fact: {', '.join('`%s`' % t for t in x['tokens'])}")
            if x.get("enforce_regexes"):
                brief.append(f"  - enforced patterns: {'; '.join('`%s`' % r for r in x['enforce_regexes'])}")
        brief.append("")
    brief += ["## Add a rule you learn (this is how the system grows)", "```bash",
              'python3 storyos/tools/storyos.py learn --project <name> \\',
              '  --kind correction --what "what went wrong" --rule "the rule now in force" \\',
              '  --token "SP526" --pattern "Rank\\s*23\\s*/\\s*SP\\s*156"', "```",
              "It appends to `.storyos-home/projects/<name>/decisions.jsonl` (append-only, never edited),",
              "writes a lock card, and the **next gate run fails** any prose matching it.",
              "If you cannot write into `.storyos-home/`, still record the decision in your handoff",
              "report — losing a learned rule is how the same mistake comes back.", "",
              "## Honest limits of this bundle",
              "- `pacing.mode` and `information_discipline` are declared strings, not derived.",
              "- Anything the project's own files do not state is reported as missing — that is by design.",
               "- The receiving agent should still re-read `projects/<name>/foundation/` directly; the",
               "  bundle is an index with enforcement, not a replacement for the source.", ""]
    (root / "AGENT_BRIEF.md").write_text("\n".join(brief), encoding="utf-8")

    (root / "ENGINE.md").write_text(f"""# What StoryOS is

A canon-discipline layer, not a writing tool. It exists so that established facts, locks and
knowledge firewalls survive **any** agent, **any** model, **any** number of sessions.

Four properties that make it different from a notes folder:

1. **Derived, never hand-typed.** `scan_project.py` reads the project's own files; every number
   on the dashboard can be traced to a source file. A hand-typed dashboard silently drifts.
2. **Precedence, not concatenation.** Native manifest → `foundation/STATUS_PANEL.md` → newest
   dated receipt. Receipts describe the past and must never outrank a live declaration. (This
   rule exists because a scan of 444 audit files, 325 of them pre-repair backups, inferred the
   live edge as Chapter49 when it was Chapter51.)
3. **Enforcement, not aspiration.** `storyos_validate.py` is executable. Rules live as a gate
   that fails drafts, with the exact file and line.
4. **It cannot eat the project.** StoryOS writes only beside it. This rule exists because an
   earlier version overwrote a real manifest and deleted five foundation files.

## The growth loop
`learn` → append-only decision log → lock card → **validator loads it as enforcement**.
A rule stated once is prose someone skims. A rule learned is code that blocks.

## Checks it runs
`provenance` · `lock-integrity` · `firewall-integrity` · `stale-claim` · `drift` ·
`banned-tokens` (literal + regex, negation-aware) · `required-pattern` · `ledger-coverage` ·
`branch-supersession`. Body/footer split keeps a chapter's own *"these values are deleted, not
currentized"* disclaimers from reading as violations — which is how a naive guard produced 293
false errors and taught everyone to ignore it.

## Verify, don't trust
```bash
python3 storyos/tools/storyos_validate.py --selftest     # 5/5 expected
python3 storyos/tools/storyos_validate.py --scan-coverage # opt-in; noisier by design
```
The selftest exists so an agent can confirm the checker actually bites before relying on a PASS.
A guard that fires on a correct project is worse than no guard.
""", encoding="utf-8")

    # 5. zip it, with bundle-relative paths
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage))
    shutil.rmtree(stage, ignore_errors=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="StoryOS_Agent_Bundle.zip")
    ap.add_argument("--project", help="bundle one project only")
    ap.add_argument("--no-prose", action="store_true", help="omit chapters (safe to share widely)")
    a = ap.parse_args()
    out = build(Path(a.out).resolve(), not a.no_prose, a.project)
    n = len(zipfile.ZipFile(out).namelist())
    print(f"bundle: {out}")
    print(f"  {n} files · {out.stat().st_size/1024/1024:.1f} MB · prose={'yes' if not a.no_prose else 'no'}")
