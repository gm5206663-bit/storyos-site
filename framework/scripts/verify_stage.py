#!/usr/bin/env python3
"""verify_stage.py — the site must not leak prose, must stay self-consistent, must be static."""
import json, re, sys
from pathlib import Path
out = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd() / "storyos-site")
fail, checked = [], 0
PROSE_MARKERS = re.compile(
    r"(He said to her|she whispered|His eyes narrowed|The crowd gasped|suddenly, |"
    r"Chapter \d+ continues|end of chapter)", re.I)
forbidden_state = re.compile(r"^(GATE: (PASS|FAIL|WARN|UNKNOWN))", re.M)
for f in sorted(out.rglob("*")):
    if not f.is_file():
        continue
    checked += 1
    txt = f.read_text(encoding="utf-8", errors="replace")
    rel = f.relative_to(out)
    if f.suffix in (".html", ".md", ".txt"):
        m = PROSE_MARKERS.search(txt)
        if m and "chapters" not in str(rel):
            fail.append(f"{rel}: narrative-looking prose leaked into a public file ({m.group(0)!r})")
    if f.name == "state.txt":
        if not forbidden_state.search(txt):
            fail.append(f"{rel}: no GATE line — an agent could not tell if drafting is allowed")
        for key in ("live edge", "next source chapter", "RULES OF ENGAGEMENT"):
            if key not in txt:
                fail.append(f"{rel}: missing '{key}'")
    if f.suffix in (".html",):
        for ext in re.findall(r'(?:src|href)="(https?://[^"]+)"', txt):
            fail.append(f"{rel}: external asset {ext} — breaks offline/file:// preview")
    if f.name == "manifest.json":
        man = json.loads(txt)
        for proj, entry in man["projects"].items():
            for relf, meta in entry["files"].items():
                p = out / relf
                if not p.exists():
                    fail.append(f"manifest lists missing file {relf}")
                elif p.stat().st_size != meta["bytes"]:
                    fail.append(f"{relf}: size drift ({p.stat().st_size} != {meta['bytes']}) — stale build")
        checked += 0
if not (out / "agents.md").exists():
    fail.append("agents.md missing — no contract for the receiving agent")
print(f"VERIFY_STAGE: {'FAIL' if fail else 'PASS'} ({checked} files checked, {len(fail)} issues)")
for x in fail[:25]:
    print("  [FAIL]", x)
sys.exit(1 if fail else 0)
