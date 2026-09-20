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

# A published artifact that records its own provenance must not drift from it. LAWS.md is
# generated from the law JSON and footers the source's sha256 prefix; nothing checked that.
# The prefix is derived FROM the footer and verified against the real source files, so this
# fails only when the two disagree — not when a rebuild legitimately changes both together.
SRC_RE = re.compile(r"source file sha256:\s*`([0-9a-f]{8,64})")
law_docs = [p for p in (out.rglob("LAWS.md")) if p.is_file()]
for doc in law_docs:
    m = SRC_RE.search(doc.read_text(encoding="utf-8", errors="replace"))
    if not m:
        fail.append(f"{doc.relative_to(out)}: generated law doc lost its provenance footer")
        continue
    rec = m.group(1)
    root = out.parent
    cands = [p for p in (root / "laws" / "UNIVERSAL_LAWS.json",
                         root / "storyos-home" / "laws" / "UNIVERSAL_LAWS.json",
                         Path.home() / "storyos-home" / "laws" / "UNIVERSAL_LAWS.json",
                         Path(__file__).resolve().parents[2] / "storyos-home" / "laws" / "UNIVERSAL_LAWS.json",
                         Path(__file__).resolve().parents[1] / "laws" / "UNIVERSAL_LAWS.json")
             if p.exists()]
    for env in ("STORYOS_HOME",):
        h = __import__("os").environ.get(env)
        if h:
            p = Path(h) / "laws" / "UNIVERSAL_LAWS.json"
            if p.exists() and p not in cands:
                cands.append(p)
    if not cands:
        fail.append(f"{doc.relative_to(out)}: provenance unverifiable — no laws/UNIVERSAL_LAWS.json "
                    f"found near {root} (set $STORYOS_HOME to check it)")
    else:
        H = __import__("hashlib").sha256
        digests = {str(c): H(c.read_bytes()).hexdigest() for c in cands}
        # Not "any copy agrees" — that passed a real drift test, because a stale published copy
        # was excused by an untouched runtime copy. Every copy must agree, and with the footer.
        if len(set(digests.values())) > 1:
            first = next(iter(digests.values()))
            disagree = [k for k, v in digests.items() if v != first]
            fail.append(f"{doc.relative_to(out)}: law source is ambiguous — "
                        f"{len(digests)} copies exist and they do not agree; the published laws "
                        f"cannot be traced to one source. Disagreeing: "
                        f"{', '.join(disagree[:3])}")
        if not all(d.startswith(rec) for d in digests.values()):
            fail.append(f"{doc.relative_to(out)}: footer says source sha256 {rec}… but the law file on "
                    f"disk hashes differently — the published laws drifted from their source "
                    f"(regenerate; never hand-edit)")
print(f"VERIFY_STAGE: {'FAIL' if fail else 'PASS'} ({checked} files checked, {len(fail)} issues)")
for x in fail[:25]:
    print("  [FAIL]", x)
sys.exit(1 if fail else 0)
