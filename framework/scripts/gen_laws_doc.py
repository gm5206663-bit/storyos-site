#!/usr/bin/env python3
"""Render $STORYOS_HOME/laws/UNIVERSAL_LAWS.json into a human/agent-readable LAWS.md.

Generated, never hand-typed: every line is derived from the law file, so the document cannot
drift from the data the validator reads. That is the whole point of the file existing.
"""
import json
import os
import pathlib
import sys

HOME = pathlib.Path(os.environ.get("STORYOS_HOME", str(pathlib.Path.home() / "storyos-home")))
SRC = HOME / "laws" / "UNIVERSAL_LAWS.json"


def main():
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    laws = raw["laws"]
    out = [
        "# Adopted universal laws — StoryOS",
        "",
        f"Generated from `{SRC}` by `scripts/gen_laws_doc.py`. Do not hand-edit this file; edit the",
        "JSON, or file a contribution under `intake/drop/`.",
        "",
        f"- **imported from:** {raw.get('imported_from')}",
        f"- **status:** {raw.get('status')}",
        "",
        "## Authority order (which source wins when they disagree)",
        "",
    ]
    for i, level in enumerate(laws.get("authority_order") or [], 1):
        out.append(f"{i}. {level}")
    out += ["", "## The twelve locks (a chapter is not writable until each is answerable)", ""]
    for k in laws.get("twelve_locks") or []:
        out.append(f"- **{k.get('n')}. {k.get('lock')}** — {k.get('question')}")
    out += ["", f"> Lock 4 rule: {laws.get('lock_4_rule')}", "",
            "## Pipeline (LOAD → … → RECORD)", ""]
    for st in laws.get("pipeline") or []:
        out.append(f"{st.get('n')}. **{st.get('stage')}** — {st.get('detail')}")
    out += ["", "## Pre-draft gate", ""]
    for st in laws.get("predraft_gate") or []:
        out.append(f"{st.get('n')}. **{st.get('step')}** — {st.get('detail')}")
    out += ["", "## Knowledge-firewall states (the only legal values)", ""]
    for st in laws.get("firewall_states") or []:
        out.append(f"- `{st.get('state')}` — {st.get('meaning')}")
    out += ["", "## Leak paths (never do these)", ""]
    lp = laws.get("leak_paths")
    for x in (lp if isinstance(lp, list) else [lp]):
        if x:
            out.append(f"- {x}")
    out += ["", "## Failure modes this system was built to prevent", ""]
    for f in laws.get("failure_modes") or []:
        out.append(f"- **{f.get('n')}. {f.get('mode')}** — {f.get('symptom')}")
    out += ["", "## Two rules about the checker itself", "",
            f"- **Self-referential trap.** {laws.get('self_referential_trap')}", "",
            f"- **Negative test rule.** {laws.get('negative_test_rule')}", "",
            f"- **Gate scope.** {laws.get('gate_scope_warning')}", "",
            "## How StoryOS applies these", "",
            "- `tools/storyos_validate.py` loads the firewall-state vocabulary from this file, so the",
            "  gate and the laws cannot disagree. `SUSPECTED` is accepted as a legacy alias for",
            "  `SUSPICION` and produces a warning, so existing project data is not newly failed.",
            "- `tools/intake.py` enforces the reserved-field list and the firewall/canon vocabularies",
            "  for contributions from other agents.",
            "- Gate 3 (`zero digits in prose`) is **not** adopted: this project's own locks require exact",
            "  figures (Rank20/SP505, Dawnflame 3,100) and its validator enforces them. Adopting that",
            "  gate would contradict the human's explicit requirements, and the authority order says the",
            "  project's locked documents outrank kit laws.",
            "",
            f"_source file sha256: `{__import__('hashlib').sha256(SRC.read_bytes()).hexdigest()[:16]}…_",
            ""]
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HOME / "LAWS.md"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"LAWS_DOC: wrote {dest} ({dest.stat().st_size} bytes, derived from {SRC.name})")


if __name__ == "__main__":
    main()
