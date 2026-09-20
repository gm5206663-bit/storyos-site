#!/usr/bin/env python3
"""
publish_site.py — turn the live control centre into PUBLIC LINKS any agent can fetch.

  python3 scripts/publish_site.py --project <name> [--out F] [--upload] [--no-dashboard]

Each link is plain text, no auth, no JS, no key. paste.rs caps a document near 50 KB, so a
large payload is published as 2 verified parts (state, then dashboard).

Nothing is handed over unread: every link is fetched back and sha256-compared with the local
bytes before it is printed. A paste host was observed serving a DIFFERENT document under a
freshly returned id — an unverified link is how an agent ends up reading the wrong project.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("STORYOS_HOME", str(Path.home() / "storyos-home")))
REPO = Path(__file__).resolve().parent.parent
MAX_BYTES = 45_000


def reg() -> dict:
    return json.loads((HOME / "registry.json").read_text())["projects"]


# --------------------------------------------------------------------- content
def build(name: str) -> tuple[str, str]:
    entry = reg()[name]
    proj = Path(entry["path"])
    if not proj.is_absolute():                       # inside a bundle, paths are relative
        proj = (Path.cwd() / proj).resolve()
    st_f = HOME / "projects" / name / "state" / "STORYOS_STATE.json"
    if not st_f.exists():
        st_f = proj / "storyos" / "STORYOS_STATE.json"
    st = json.loads(st_f.read_text()) if st_f.exists() else {}
    gate = subprocess.run([sys.executable, str(REPO / "tools" / "storyos_validate.py"),
                           "--project", str(proj), "--phase", "full", "--json"],
                          capture_output=True, text=True).stdout
    try:
        gj = json.loads([l for l in gate.splitlines() if l.startswith("{")][-1])
    except (json.JSONDecodeError, IndexError):
        gj = {"result": "UNKNOWN", "findings": [gate[-400:]]}
    df = HOME / "projects" / name / "decisions.jsonl"
    ds = [json.loads(x) for x in (df.read_text().splitlines() if df.exists() else []) if x.strip()]
    live = [d for d in ds if d.get("status", "active") == "active"]
    m, e = st.get("metrics", {}), st.get("edge", {})
    chars = st.get("characters") or {}
    fw = st.get("knowledge_firewalls") or []
    locks_dir = st_f.parent / "canon" / "locks"
    n_locks = len(list(locks_dir.glob("*.md"))) if locks_dir.is_dir() else "?"
    acc = e.get("accepted_chapters") or []

    L = [f"STORYOS // {entry.get('label', name)}",
         f"generated {dt.datetime.now():%Y-%m-%d %H:%M}  ·  no auth, no JS — `curl -s <url>`",
         "=" * 60, "",
         f"GATE: {gj['result']}  (errors={gj.get('errors')}, warnings={gj.get('warnings')}, "
         f"learned-rules-active={gj.get('learned', 0)})", ""]
    for x in (gj.get("findings") or [])[:14]:
        L.append("  - " + x[:190])
    L += ["", "LIVE STATE — trust this over any older file", "-" * 40,
          f"live edge            : after Chapter{e.get('fic_chapter','?')} \"{e.get('fic_title','')}\"",
          f"next source chapter  : {e.get('next_source','?')} {e.get('next_source_title') or ''}",
          f"canon consumed       : {e.get('canon_consumed','?')} {e.get('canon_consumed_title') or ''}",
          f"authority            : {e.get('declared_by','native manifest')}",
          f"fic chapters accepted: {len(acc) or '?'}"
          + (f" (#{min(acc)}-#{max(acc)})" if acc else ""),
          f"validated / synced   : {m.get('chapters_validated','?')} / {m.get('chapters_synced','?')}",
          f"quarantined fic      : {m.get('quarantined_chapters','none')}",
          f"locks / characters   : {n_locks} / {len(chars) or '?'}   firewalls: {len(fw) or 'none registered'}",
          f"enforcement          : {len(st.get('enforce') or [])} banned literals, "
          f"{len(st.get('enforce_regexes') or [])} banned patterns", "",
          "CHARACTER LOCKS — state at the live edge", "-" * 40]
    for cn, cv in list(chars.items())[:16]:
        L.append(f"- {cn}: {str(cv.get('state') if isinstance(cv, dict) else cv)[:150]}")
    if not chars:
        L.append("(none derived — read the project's own character sheets)")
    L += ["", "KNOWLEDGE FIREWALLS — who may know what, not before when", "-" * 40]
    if not fw:
        L.append("(none registered). A GAP, not permission to assume characters know nothing:")
        L.append("derive knowledge from the project's own foundation/ and codex/.")
    for k in fw[:18]:
        if isinstance(k, dict):
            L.append(f"- {k.get('topic','?')}  [{k.get('state','?')}]  who: {k.get('character','?')}")
            if k.get("earliest_valid_change"):
                L.append(f"    earliest valid change: {str(k['earliest_valid_change'])[:150]}")
        else:
            L.append(f"- {str(k)[:160]}")
    L += ["", "BINDING LEARNED RULES — violating these means rewrite", "-" * 40]
    if not live:
        L.append("(none recorded yet — follow the project's own foundation/ and codex/)")
    for d in live:
        L.append(f"{d['id']} [{d.get('kind')}] {d.get('rule')}")
        if d.get("what"):
            L.append(f"     why: {d['what']}")
        if d.get("tokens"):
            L.append(f"     never as achieved fact: {', '.join(d['tokens'])}")
        if d.get("enforce_regexes"):
            L.append(f"     enforced patterns: {'; '.join(d['enforce_regexes'])}")
    L += ["", "RULES OF ENGAGEMENT", "-" * 40,
          "1. Do not draft prose while the gate is FAIL.",
          "2. Missing canon is reported missing. Never invented.",
          "3. Author knowledge is not character knowledge.",
          "4. A receipt older than the newest active-branch receipt is evidence, not live state.",
          "5. Do not overwrite the project's foundation/; generated state lives beside it.",
          "6. Learn a correction -> make it enforcement, not a note (storyos learn).", "",
          "No chapter prose here by design — state and rules only. The human hands over prose."]
    site = st_f.parent / "site" / "index.html"
    if not site.exists():
        site = proj / "storyos" / "site" / "index.html"
    return "\n".join(L), (site.read_text(encoding="utf-8") if site.exists() else "")


# --------------------------------------------------------------------- upload
def upload(text: str, tries: int = 5):
    want = hashlib.sha256(text.encode()).hexdigest()[:16]
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request("https://paste.rs/", data=text.encode(),
                                         headers={"content-type": "text/plain; charset=utf-8"})
            url = urllib.request.urlopen(req, timeout=90).read().decode().strip()
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            print(f"  upload try {attempt}/{tries}: {ex}"); time.sleep(2 + 2 * attempt); continue
        time.sleep(1.2)
        try:
            back = urllib.request.urlopen(url, timeout=90).read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            print(f"  readback try {attempt}/{tries}: {ex}"); continue
        if hashlib.sha256(back.encode()).hexdigest()[:16] == want:
            return url, want, len(back.encode())
        print(f"  try {attempt}/{tries}: readback MISMATCH — host served other content, retrying")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project"); ap.add_argument("--out")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--no-dashboard", action="store_true")
    a = ap.parse_args()
    if not (HOME / "registry.json").exists():
        sys.exit(f"storyos: no home at {HOME}. export STORYOS_HOME=... or run storyos init")
    name = a.project or next(iter(reg()), None)
    if name not in reg():
        sys.exit(f"storyos: unknown project {name!r}. Known: {', '.join(reg()) or 'none'}")
    state_txt, html = build(name)
    dash = ("\n" + "=" * 60 + "\nDASHBOARD — self-contained HTML, no external assets. "
            "Save as storyos.html and open.\n" + "=" * 60 + "\n" + html) if (html and not a.no_dashboard) else ""
    txt = state_txt + dash
    out = Path(a.out or f"storyos-site-{name}.txt").expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    print(f"wrote {out}  ({len(txt.encode())/1024:.0f} KB)")
    if not a.upload:
        return 0
    parts = ([("document", txt)] if len(txt.encode()) <= MAX_BYTES
             else [("part 1/2 — STATE AND RULES (agent reads this)", state_txt),
                   ("part 2/2 — DASHBOARD (human view)", dash)])
    if len(parts) > 1:
        print(f"{len(txt.encode())/1024:.0f} KB exceeds the ~50 KB host cap — publishing 2 parts")
    ok = []
    for label, body in parts:
        if not body.strip():
            continue
        r = upload(body)
        if not r:
            print(f"ABORTED at {label}: no verified link. Deliberate — an unverified link is "
                  f"how an agent reads the wrong project. Re-run --upload shortly.")
            return 1
        url, sha, size = r
        ok.append((label, url, size))
        print(f"PUBLIC LINK [{label}]  {url}")
        print(f"   verified: sha256[:16]={sha} · {size/1024:.0f} KB · first line “{body.splitlines()[0][:46]}”")
    if ok:
        print("\nSend every line above, in order. Part 1 alone is enough to work from.")
        print("Refresh any time: same command. Links die after ~30 days unused.")
        print("Always sanity-check the first line names the project you expect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
