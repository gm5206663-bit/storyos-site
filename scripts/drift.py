"""
StoryOS Site — drift scanning.

Independent of the project's own validator. Scans the ACTIVE tree (plus workspace-root
handoff files) for statements that assert a *current* live edge disagreeing with the
authoritative manifest.

Four rules, each of which exists because a naive scan gets it wrong in a specific way:

1. CLAIM CLASS: DIRECTIVE vs SOFT.
   DIRECTIVE = "Live edge: after ChapterNN" / "Live edge is after ChapterNN" /
   "CURRENT OVERRIDE after ChapterNN". These instruct the reader about what is true NOW.
   SOFT = "Current after ChapterNN:", "Latest prose: chapters/Chapter_NN.md". These can
   legitimately appear inside a dated historical entry.

2. SECTION CONTEXT EXEMPTION (the one a naive scan always misses).
   A claim sitting under a dated or chapter-scoped heading is a receipt for that moment:
       ## 2026-09-13 — Chapter32 written and synced
       - Current after Chapter32: Yan Rank29/SP392; …
   That is CORRECT history, not drift. So the nearest preceding heading is tracked, and a
   SOFT claim whose chapter matches its own section heading is exempt. DIRECTIVE claims
   are NOT exempt — a "CURRENT OVERRIDE" is wrong even under a heading.

3. SENTENCE-LEVEL HISTORICAL EXEMPTION.
   A single line can describe history and then assert the current edge:
       "At that historical point, X had not fused. Current live edge is after Chapter34."
   Exempting the whole line hides the stale claim, so the line is split into sentences and
   only the sentence carrying the claim is judged — against historical hints in itself.
   Applies to SOFT claims only.

4. SELF-FILE EXEMPTION.
   `canon_coverage/Canon_Coverage_Chapter_36.md` saying "Current after Chapter36:" is a
   receipt for the chapter it documents; a chapter's own `## Footer` likewise. A file whose
   own number matches the claim is exempt (SOFT only).

Findings are deduplicated per (file, line, claimed chapter): the two live-edge regexes both
match "Current live edge is after Chapter34" and must not be reported twice.
"""
from __future__ import annotations

import os
import re

RECEIPT_DIRS = {"archive", "audits"}

# Directives about NOW. Never exempted by headings, history wording, or file name.
DIRECTIVE = [
    ("live-edge-colon",   re.compile(r"Live edge:\s*\**\s*(?:after\s*)?Chapter[_ ]?(\d+)", re.I)),
    ("live-edge-is",      re.compile(r"[Ll]ive edge is after Chapter(\d+)", re.I)),
    ("current-live-edge", re.compile(r"Current live edge is after Chapter(\d+)", re.I)),
    ("current-override",  re.compile(r"CURRENT OVERRIDE after Chapter(\d+)", re.I)),
]

# Receipt-shaped claims. Exemption rules apply.
SOFT = [
    ("current-after",     re.compile(r"Current(?:-| )?after Chapter(\d+)\b", re.I)),
    ("latest-prose",      re.compile(r"Latest prose:\s*`?chapters/Chapter_(\d+)\.md", re.I)),
    ("latest-coverage",   re.compile(r"Latest coverage:\s*`?canon_coverage/Canon_Coverage_Chapter_(\d+)\.md", re.I)),
    ("latest-validation", re.compile(r"Latest validation:\s*`?audits/CHAPTER_(\d+)_VALIDATION", re.I)),
    ("latest-support",    re.compile(r"Latest support sync:\s*`?audits/CHAPTER_(\d+)_SUPPORT_SYNC", re.I)),
]

# more specific pattern wins when several match the same sentence
PATTERN_RANK = {"current-live-edge": 0, "current-override": 1, "live-edge-is": 2,
                "live-edge-colon": 3}

HISTORICAL = re.compile(
    r"\bhistorical\b|\bsuperseded\b|\brejected\b|\barchiv(?:e|ed)\b|not current|"
    r"\bold\b|at that point|once was|previously|before the rebuild|this is now|"
    r"remains historical|historical context",
    re.I,
)

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
HEADING_CHAPTER = re.compile(r"Chapter[_ ]?(\d+)", re.I)
HEADING_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

# `:` is deliberately NOT a splitter: it introduces a claim ("Live edge: after Chapter35"),
# so splitting on it severs the directive from its chapter number.
SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+|\s*\|\s*")

# files that are by construction a dated log of past states
LEDGER_FILES = re.compile(r"CANON_LEDGER\.md$|SERIAL_LOG\.md$|CHANGELOG\.md$", re.I)


def _self_number(rel: str):
    base = os.path.basename(rel)
    m = re.search(r"Chapter(?:_)?(\d+)", base, re.I)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\.", base)
    return int(m.group(1)) if m else None


def scan_text(rel: str, text: str, expected_edge):
    """Return deduplicated findings for one file."""
    if not expected_edge:
        return []
    self_n = _self_number(rel)
    is_ledger = bool(LEDGER_FILES.search(rel))

    section_chapter = None
    section_dated = False
    in_footer = False
    raw = []

    for lineno, line in enumerate(text.splitlines(), 1):
        h = HEADING.match(line)
        if h:
            body = h.group(2)
            in_footer = bool(re.match(r"Footer\s*$", body, re.I))
            mc = HEADING_CHAPTER.search(body)
            section_chapter = int(mc.group(1)) if mc else None
            section_dated = bool(HEADING_DATE.search(body))
            continue

        for sent in SENTENCE_SPLIT.split(line):
            sent = sent.strip()
            if not sent:
                continue

            hits = {}
            for pid, rx in DIRECTIVE:
                m = rx.search(sent)
                if m:
                    hits[pid] = ("directive", int(m.group(1)))
            for pid, rx in SOFT:
                m = rx.search(sent)
                if m:
                    hits.setdefault(pid, ("soft", int(m.group(1))))
            if not hits:
                continue

            # dedupe: one finding per (claim class, claimed chapter)
            best = {}
            for pid, (cls, n) in hits.items():
                key = (cls, n)
                rank = PATTERN_RANK.get(pid, 9)
                if key not in best or rank < PATTERN_RANK.get(best[key][0], 9):
                    best[key] = (pid, n)

            for (cls, n), (pid, _) in best.items():
                if n == expected_edge:
                    continue
                exempt = None
                if cls == "soft":
                    if HISTORICAL.search(sent):
                        exempt = "sentence frames it as historical"
                    elif self_n is not None and n == self_n:
                        exempt = "file is the receipt for its own chapter"
                    elif in_footer and self_n is not None and n == self_n:
                        exempt = "chapter footer receipt"
                    elif section_chapter is not None and n == section_chapter:
                        exempt = f"claim matches its own section heading (Chapter{section_chapter})"
                    elif is_ledger and section_dated:
                        exempt = "dated entry in a ledger/serial-log file"
                if exempt:
                    continue
                raw.append(_finding(rel, lineno, pid, cls, n, expected_edge, sent,
                                    in_footer, self_n, section_chapter, section_dated))

    return raw


def _finding(rel, lineno, pid, cls, n, expected, sent, in_footer, self_n,
             sec_ch, sec_dated) -> dict:
    gap = expected - n
    if cls == "directive":
        sev = "SEV-1"
    elif gap > 2:
        sev = "SEV-1"
    elif gap > 0:
        sev = "SEV-2"
    else:
        sev = "SEV-3"          # claims a chapter AHEAD of the edge: future-route leak
    return {
        "file": rel,
        "line": lineno,
        "pattern": pid,
        "claim_class": cls,
        "claims_chapter": n,
        "expected_chapter": expected,
        "gap": gap,
        "severity": sev,
        "in_footer": in_footer,
        "file_self_chapter": self_n,
        "section_chapter": sec_ch,
        "section_dated": sec_dated,
        "text": sent.strip()[:400],
    }


def scan_paths(paths, expected_edge, skip=None) -> dict:
    """paths: list of (display_rel, absolute_path)."""
    skip = skip or set()
    findings = []
    scanned = 0
    for rel, full in paths:
        if rel in skip:
            continue
        if not rel.endswith((".md", ".txt", ".json")):
            continue
        scanned += 1
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            continue
        findings.extend(scan_text(rel, text, expected_edge))

    by_file = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)
    file_view = []
    for path, fs in sorted(by_file.items()):
        worst = min(fs, key=lambda x: x["severity"])
        file_view.append({
            "file": path,
            "severity": worst["severity"],
            "claims": sorted({x["claims_chapter"] for x in fs}),
            "claim_classes": sorted({x["claim_class"] for x in fs}),
            "lines": sorted({x["line"] for x in fs}),
            "n_findings": len(fs),
            "worst_text": worst["text"],
        })
    file_view.sort(key=lambda r: (r["severity"], min(r["claims"]), r["file"]))
    findings.sort(key=lambda f: (f["severity"], f["claims_chapter"], f["file"], f["line"]))

    return {
        "expected_edge": expected_edge,
        "scanned": scanned,
        "findings": findings,
        "by_file": file_view,
        "counts": {
            "findings": len(findings),
            "files_affected": len(by_file),
            "sev1": len([f for f in findings if f["severity"] == "SEV-1"]),
            "sev2": len([f for f in findings if f["severity"] == "SEV-2"]),
            "sev3": len([f for f in findings if f["severity"] == "SEV-3"]),
        },
    }


def collect_active_paths(proj_path: str):
    """Active tree only: receipts (archive/, audits/) excluded."""
    out = []
    for dirpath, dirnames, filenames in os.walk(proj_path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        rel_dir = os.path.relpath(dirpath, proj_path).replace(os.sep, "/")
        if rel_dir != "." and rel_dir.split("/")[0] in RECEIPT_DIRS:
            continue
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, proj_path).replace(os.sep, "/")
            out.append((rel, full))
    return out


ROOT_PREFIX = "(workspace root)/"


def scanner_gap_proof(findings, manifest) -> dict:
    """
    Derive WHY the project's own validator misses each finding, from the validator's own
    declared scope (manifest.active_markdown_dirs / top_level_active_files) and its own
    two live-edge regexes. Nothing here is asserted — it is replayed.
    """
    dirs = set(manifest.get("active_markdown_dirs") or [])
    tops = set(manifest.get("top_level_active_files") or [])

    their_live = re.compile(r"Live edge:[^\n]*Chapter(\d+)", re.I)
    their_curr = re.compile(
        r"Current(?:-| )?(?:controlling state |status |scene |values |valid measurements "
        r"|state rule )?after Chapter(\d+)\b",
        re.I,
    )

    causes = {
        "outside_project_dir": [],   # workspace-root files: no per-project scan can see them
        "dir_not_scanned": [],       # e.g. canon_coverage/
        "file_not_listed": [],       # top-level file absent from top_level_active_files
        "regex_no_match": [],        # in scope, but neither of their regexes fires
        "matched_but_exempted": [],  # in scope AND matched -> their historical allowlist
    }
    for f in findings:
        rel = f["file"]
        if rel.startswith(ROOT_PREFIX):
            causes["outside_project_dir"].append(rel)
            continue
        top = rel.split("/")[0]
        is_top_level = "/" not in rel
        in_scope = (top in dirs and not is_top_level) or (rel in tops and is_top_level)
        if not in_scope and not is_top_level:
            causes["dir_not_scanned"].append(rel)
        elif not in_scope:
            causes["file_not_listed"].append(rel)
        elif their_live.search(f["text"]) or their_curr.search(f["text"]):
            causes["matched_but_exempted"].append(rel)
        else:
            causes["regex_no_match"].append(rel)
    for k in causes:
        causes[k] = sorted(set(causes[k]))

    return {
        "their_scope_dirs": sorted(dirs),
        "their_scope_top_level_files": sorted(tops),
        "their_live_edge_regex": their_live.pattern,
        "their_current_after_regex": their_curr.pattern,
        "by_cause": causes,
        "fix_add_dirs": sorted(({"canon_coverage"} | {
            f["file"].split("/")[0] for f in findings
            if "/" in f["file"] and not f["file"].startswith(ROOT_PREFIX)
        }) - dirs),
        "fix_add_top_level_files": sorted(
            {f["file"] for f in findings if "/" not in f["file"]} - tops
        ),
        "fix_add_root_scope": sorted(
            {f["file"][len(ROOT_PREFIX):] for f in findings
             if f["file"].startswith(ROOT_PREFIX)}
        ),
        "fix_add_regexes": [
            {
                "id": "live_edge_directive_stale",
                "regex": r"[Ll]ive edge is after Chapter(\d+)|"
                         r"Current live edge is after Chapter(\d+)|"
                         r"CURRENT OVERRIDE after Chapter(\d+)",
                "why": "Their `Live edge:` regex requires a literal colon, so "
                       "`Live edge is after ChapterNN` never matches. Their "
                       "`Current…after Chapter` regex allows only the prefixes "
                       "controlling state/status/scene/values/valid measurements/"
                       "state rule, so `Current live edge is after` never matches.",
            },
        ],
    }
