#!/usr/bin/env python3
"""StoryOS contribution intake — ported and adapted from the human's own
`the-universal-storyline-creation-` repo (github:gm5206663-bit @ 7da59a52, whose
tools/selftest.py passes 102/102 as delivered).

Why this exists in StoryOS: the standing requirement is that the system grows across a
lifetime and can be handed to other agents. Until now an agent could only edit state files
directly, which means any external contributor had to be trusted with the whole tree. An
intake queue with a schema and a rejection report means a contribution is DATA that must
pass rules before it touches canon — and every accepted record carries provenance.

Subcommands
    validate [file ...]   check intake/drop/ (or named files) without touching state
    ingest                validate then merge; accepted -> intake/accepted/, rejected ->
                          intake/rejected/ with a .report.txt saying exactly why
    status                what is pending, accepted, rejected

Design rules carried over from the source, deliberately:
  * RESERVED_FIELDS — a contribution may never redefine the shape of the system.
  * A non-ASCII filename is refused at the door, not silently mangled.
  * Unknown firewall state or confidence tag is an ERROR: inventing a state is a law
    change and belongs to the human, not to an agent.
  * Rejection is informative. The report names the field and the rule, and quotes the
    offending value, so a contributor can fix it without reading this source.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys

HOME = pathlib.Path(os.environ.get("STORYOS_HOME", str(pathlib.Path.home() / "storyos-home")))
INTAKE = HOME / "intake"
for _d in ("drop", "accepted", "rejected"):
    (INTAKE / _d).mkdir(parents=True, exist_ok=True)

KINDS = {
    "project":   {"required": ["id", "name", "path", "status", "live_edge"],
                  "optional": ["active", "verification", "notes", "authority"],
                  "collection": "projects"},
    "firewall":  {"required": ["who", "state", "topic", "rule"],
                  "one_of": [["earliest_change", "earliest_valid_change"]],
                  "optional": ["project", "belief", "notes"],
                  "collection": "firewalls",
                  "_note": "the project's own firewall table uses earliest_valid_change and the "
                           "adopted laws use earliest_change; either satisfies the rule, because "
                           "rejecting the human's existing data would make the tool wrong"},
    "anchor":    {"required": ["anchor", "year"],
                  "optional": ["project", "note", "chapter"],
                  "collection": "anchors"},
    "canon":     {"required": ["claim", "confidence"],
                  "optional": ["sources", "note", "project"],
                  "collection": "canon"},
    "lock":      {"required": ["lock", "value"],
                  "optional": ["project", "note"],
                  "collection": "locks"},
    "decision":  {"required": ["decision", "reason"],
                  "optional": ["project", "authorized_by", "date", "supersedes"],
                  "collection": "decisions"},
    "correction": {"required": ["was", "now", "reason"],
                   "optional": ["project", "file", "line", "found_by"],
                   "collection": "corrections"},
    "note":      {"required": ["text"], "optional": ["project", "tag"],
                  "collection": "notes"},
}
def _load_laws() -> dict:
    """Same law file the validator reads, so intake and the gate cannot disagree."""
    p = HOME / "laws" / "UNIVERSAL_LAWS.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("laws") or {}
    except (OSError, ValueError):
        return {}


_LAWS = _load_laws()
FIREWALL_STATES = [x["state"] for x in (_LAWS.get("firewall_states") or []) if x.get("state")] or [
    "KNOWN", "KNOWN PARTLY", "SUSPICION", "SUSPECTED", "DISBELIEF", "UNKNOWN", "FALSE BELIEF", "HIDDEN"]
RESERVED_EXTRA = [k for k in ("authority_order", "seven_gates", "twelve_locks", "failure_modes")
                  if k in _LAWS]
CONFIDENCE_LEVELS = ["canon", "fan", "design", "user ruling", "on page", "reported"]
PROJECT_STATUSES = ["live", "active", "gate-pass", "portable", "reference",
                    "template", "external", "paused", "superseded"]
RESERVED_FIELDS = sorted({"_comment", "authority_order", "seven_gates", "gate_scope_warning",
                            "twelve_locks", "failure_modes", "self_referential_trap",
                            "negative_test_rule", "pipeline", "predraft_gate", "leak_paths",
                            "adaptation_talent", "lock_4_rule", "firewall_states",
                            "authority_order"} | set(RESERVED_EXTRA))
NAME_OK = re.compile(r"^[\x20-\x7e]+$")
SNAKE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")


class Report:
    def __init__(self, label: str):
        self.label, self.errors, self.warnings = label, [], []

    def err(self, m): self.errors.append(m)
    def warn(self, m): self.warnings.append(m)
    def ok(self): return not self.errors

    def render(self):
        out = [f"intake report — {self.label}"]
        if self.errors:
            out.append(f"\nERRORS ({len(self.errors)}) — must fix before this can be ingested:")
            out += [f"  - {e}" for e in self.errors]
        if self.warnings:
            out.append(f"\nWARNINGS ({len(self.warnings)}) — ingested, but check these:")
            out += [f"  - {w}" for w in self.warnings]
        if self.ok() and not self.warnings:
            out.append("  clean")
        return "\n".join(out) + "\n"


def iter_strings(obj, path="$"):
    """Every string with its JSON path — needed so a rule can name WHERE it fired."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(k, f"{path}.<key>")
            yield from iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]")


def validate_records(records, source_name: str) -> Report:
    """Rules only — no writes. Split out so the selftest can feed it synthetic cases."""
    r = Report(source_name)
    if not isinstance(records, list):
        records = [records]
    if not records:
        r.err("file contains no records")
    for idx, rec in enumerate(records):
        tag = f"record {idx}"
        if not isinstance(rec, dict):
            r.err(f"{tag}: must be an object, got {type(rec).__name__}")
            continue
        kind = rec.get("kind")
        if kind not in KINDS:
            r.err(f"{tag}.kind = {kind!r} — allowed: {', '.join(sorted(KINDS))}")
            continue
        spec = KINDS[kind]
        for field in spec["required"]:
            v = rec.get(field)
            if v is None or (isinstance(v, str) and not v.strip()):
                r.err(f"{tag}.{field} is required for kind={kind!r}")
        for group in spec.get("one_of", []):
            if not any(str(rec.get(g, "")).strip() for g in group):
                r.err(f"{tag}: needs one of {', '.join(group)} — without it the rule cannot be "
                      f"enforced (there is no recorded moment at which a change becomes valid)")
        allowed = set(spec["required"]) | set(spec["optional"]) | {"kind", "provenance"}
        for k in rec:
            if k in RESERVED_FIELDS:
                r.err(f"{tag}.{k} is RESERVED — it changes the shape of the system, "
                      f"which belongs to the human, not to a contribution")
            elif k not in allowed:
                r.warn(f"{tag}.{k} is not a known field for kind={kind!r}")
        if kind == "firewall" and rec.get("state") not in (None, ""):
            if rec["state"] not in FIREWALL_STATES:
                r.err(f"{tag}.state = {rec['state']!r} is not a firewall state; inventing a "
                      f"state is a law change (see $STORYOS_HOME/laws/UNIVERSAL_LAWS.json) — "
                      f"allowed: {', '.join(FIREWALL_STATES)}")
            if rec["state"] in {"UNKNOWN", "HIDDEN", "FALSE BELIEF"} and not rec.get("earliest_change"):
                r.err(f"{tag}: state={rec['state']} needs earliest_change, otherwise the "
                      f"firewall cannot be enforced (no valid change is recorded)")
        if kind == "canon" and rec.get("confidence"):
            if rec["confidence"] not in CONFIDENCE_LEVELS:
                r.err(f"{tag}.confidence = {rec['confidence']!r} — allowed: "
                      f"{', '.join(CONFIDENCE_LEVELS)}")
            if rec["confidence"] in {"canon", "user ruling"} and not rec.get("sources"):
                r.warn(f"{tag}: confidence={rec['confidence']!r} with no sources — a canon-strength "
                       f"claim should say where it came from")
        if kind == "project" and rec.get("status"):
            if rec["status"] not in PROJECT_STATUSES:
                r.err(f"{tag}.status = {rec['status']!r} — allowed: {', '.join(PROJECT_STATUSES)}")
        # CJK/other scripts are refused with an explanation rather than silently shipped,
        # because a downstream renderer that cannot display them fails invisibly.
        for path, s in iter_strings(rec):
            if re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", s):
                r.err(f"{tag}{path}: contains non-Latin script — transliterate it, an agent "
                      f"downstream may not be able to render it")
                break
            if "\\n" in s:
                r.err(f"{tag}{path}: contains a literal backslash-n (a newline that never "
                      f"became a newline)")
                break
    return r


def validate_file(p: pathlib.Path) -> tuple[Report, list | None]:
    r = Report(p.name)
    if not NAME_OK.fullmatch(p.name):
        r.err(f"filename {p.name!r} must be ASCII-safe: letters, digits, _ . -")
        return r, None
    if not SNAKE.match(p.name):
        r.err(f"filename {p.name!r} must match ^[A-Za-z][A-Za-z0-9_.-]*$")
        return r, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        r.err(f"unreadable/invalid JSON: {e}")
        return r, None
    full = validate_records(data, p.name)
    r.errors += full.errors
    r.warnings += full.warnings
    recs = data if isinstance(data, list) else [data]
    return r, (recs if r.ok() else None)


def state_dir(project: str | None) -> pathlib.Path:
    return HOME / "projects" / (project or "_universal") / "state"


def merge(records: list, source_name: str) -> dict[str, int]:
    """Append validated records to per-collection ledgers, stamping provenance."""
    counts: dict[str, int] = {}
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    by_project: dict[str | None, list] = {}
    for rec in records:
        by_project.setdefault(rec.get("project"), []).append(rec)
    for project, recs in by_project.items():
        sd = state_dir(project)
        sd.mkdir(parents=True, exist_ok=True)
        for rec in recs:
            coll = KINDS[rec["kind"]]["collection"]
            out = rec.copy()
            out["provenance"] = {"accepted_from": source_name, "accepted_on": stamp,
                                 "accepted_by": "storyos/tools/intake.py",
                                 "note": "contributed record; verify consequential claims with "
                                         "the human"}
            path = sd / f"{coll}.jsonl"
            existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            # idempotence: re-ingesting the same contribution must not double-append
            probe = {k: v for k, v in rec.items() if k != "provenance"}
            dup = any(_same(e, probe) for e in existing if e.strip())
            if dup:
                counts[f"{coll}(dup, skipped)"] = counts.get(f"{coll}(dup, skipped)", 0) + 1
                continue
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            counts[coll] = counts.get(coll, 0) + 1
    return counts


def _same(line: str, rec: dict) -> bool:
    try:
        e = json.loads(line)
    except ValueError:
        return False
    return {k: v for k, v in e.items() if k != "provenance"} == rec


def cmd_validate(paths=None):
    files = [pathlib.Path(p) for p in paths] if paths else sorted((INTAKE / "drop").glob("*.json"))
    if not files:
        print(f"INTAKE_VALIDATE: nothing to do ({INTAKE / 'drop'} is empty)")
        return 0
    bad = 0
    for f in files:
        r, _ = validate_file(f)
        print(r.render())
        bad += not r.ok()
    print(f"INTAKE_VALIDATE: {'PASS' if not bad else f'{bad} file(s) rejected'} "
          f"({len(files)} checked)")
    return 1 if bad else 0


def cmd_ingest():
    files = sorted((INTAKE / "drop").glob("*.json"))
    if not files:
        print("INGEST: intake/drop/ is empty — nothing to merge")
        return 0
    acc = rej = 0
    for f in files:
        r, recs = validate_file(f)
        if recs is None:
            dest = INTAKE / "rejected" / f.name
            shutil_move(f, dest)
            (dest.with_suffix(".report.txt")).write_text(r.render(), encoding="utf-8")
            rej += 1
            print(f"  REJECTED  {f.name}")
            print("            " + (r.errors[0][:110] if r.errors else ""))
            continue
        counts = merge(recs, f.name)
        dest = INTAKE / "accepted" / f.name
        shutil_move(f, dest)
        (dest.with_suffix(".report.txt")).write_text(r.render(), encoding="utf-8")
        acc += 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no new records"
        print(f"  ACCEPTED  {f.name} → {summary}")
    print(f"INGEST: {acc} accepted · {rej} rejected   (state under $STORYOS_HOME/projects/*/state/)")
    return 1 if rej else 0


def shutil_move(src: pathlib.Path, dst: pathlib.Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def cmd_status():
    for d in ("drop", "accepted", "rejected"):
        n = len(list((INTAKE / d).glob("*.json")))
        print(f"  intake/{d:<9} {n} contribution file(s)")
    ledgers = sorted(HOME.glob("projects/*/state/*.jsonl"))
    print(f"  ledgers in runtime state: {len(ledgers)}")
    for p in ledgers[:12]:
        n = len([l for l in p.read_text().splitlines() if l.strip()])
        print(f"    {str(p.relative_to(HOME)):<58} {n} record(s)")
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "validate":
        return cmd_validate(argv[2:] or None)
    if cmd == "ingest":
        return cmd_ingest()
    if cmd == "status":
        return cmd_status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
