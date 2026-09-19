#!/usr/bin/env python3
"""
StoryOS Site — build.py

Scans a StoryOS workspace (one or more project folders) and emits a self-contained
static payload into data/:

  data/index.json          portal, gates, growth, integrity  (small — load first)
  data/state/<proj>.json   full state: locks, firewalls, characters, decisions, rules
  data/chapters/<proj>/<n>.json   one chapter: prose (footer separated) + coverage
  data/vault/<proj>.json   every file in the project: path, bytes, sha256, kind
  data/issues.json         independent drift/stale-edge findings + scanner-gap proof

Design notes
------------
* No third-party dependencies. Python 3.9+ stdlib only.
* The published state is DERIVED FROM THE PROJECT'S OWN FILES, never hard-coded here.
  Authority order: foundation/CURRENT_STATE_MANIFEST.json -> foundation/STATUS_PANEL.md
  -> HANDOFF.md. If they disagree, the disagreement is reported, not silently resolved.
* Chapter prose is split from the `## Footer` production block so a reader page can show
  prose only while agents still get the footer.
* Every vault file carries sha256 so any consumer can detect alteration in transit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drift as driftmod

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
DATA = os.path.join(SITE, "data")

# --------------------------------------------------------------------------- #
# project discovery
# --------------------------------------------------------------------------- #

PROJECT_LABELS = {
    "soul_land_4_fire_phoenix": "Soul Land 4 — Fire Phoenix OC",
    "dragon_prince_yuan_native_oc_fanfiction": "Dragon Prince Yuan — Zhou Xu",
}

# directories whose contents are receipts, not live state
RECEIPT_DIRS = {"archive", "audits"}


def discover_projects(root: str) -> list[dict]:
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        if not os.path.isdir(os.path.join(p, "chapters")) and not os.path.isdir(
            os.path.join(p, "foundation")
        ):
            continue
        out.append(
            {
                "id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
                "dir": name,
                "path": p,
                "label": PROJECT_LABELS.get(name, name.replace("_", " ").title()),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha16(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def read(p: str) -> str:
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def walk_files(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for fn in filenames:
            out.append(os.path.join(dirpath, fn))
    return sorted(out)


def classify(rel: str) -> str:
    parts = rel.split("/")
    top = parts[0] if len(parts) > 1 else "(root)"
    if top in RECEIPT_DIRS:
        return "receipt"
    if top == "chapters":
        return "prose"
    if top == "canon_coverage":
        return "coverage"
    if top == "foundation":
        return "foundation"
    if top == "bible":
        return "bible"
    if top == "codex":
        return "codex"
    if top == "tools":
        return "tool"
    return "root"


# --------------------------------------------------------------------------- #
# state derivation
# --------------------------------------------------------------------------- #

MANIFEST_REL = "foundation/CURRENT_STATE_MANIFEST.json"


def load_manifest(proj_path: str) -> dict:
    p = os.path.join(proj_path, MANIFEST_REL)
    if not os.path.exists(p):
        return {}
    try:
        return json.loads(read(p))
    except Exception as exc:  # noqa: BLE001
        return {"_parse_error": str(exc)}


def edge_from_manifest(m: dict) -> dict:
    if not m or "_parse_error" in m:
        return {}
    cs = m.get("canon_consumed_through") or {}
    ns = m.get("next_source") or {}
    return {
        "fic_chapter": m.get("latest_fic_chapter"),
        "fic_title": m.get("latest_fic_title"),
        "fic_file": m.get("latest_fic_file"),
        "coverage_file": m.get("latest_coverage_file"),
        "canon_consumed": cs.get("chapter"),
        "canon_consumed_title": cs.get("title"),
        "next_fic_chapter": m.get("next_fic_chapter"),
        "next_source": ns.get("chapter"),
        "next_source_title": ns.get("title"),
        "authority": MANIFEST_REL,
        "schema_version": m.get("schema_version"),
        "updated": m.get("updated"),
    }


CHARACTER_KEYS = {
    "lan": "Lan Xuanyu", "qian": "Qian Lei", "liu": "Liu Feng", "yan": "Yan Shuo",
    "song": "Song Yichen", "luo": "Luo Haoran", "lu": "Lu Qianxun",
    "ye": "Ye Lingtong", "jin": "Jin Xiang", "dorm333": "Dorm333 (team)",
    "dorm336": "Dorm336 (team)",
}


def characters_from_manifest(m: dict) -> dict:
    """foundation/CURRENT_STATE_MANIFEST.json -> current_state is the character layer."""
    cs = (m or {}).get("current_state") or {}
    out = {}
    for k, v in cs.items():
        if not isinstance(v, str):
            continue
        out[CHARACTER_KEYS.get(k.lower(), k)] = {"key": k, "state": v}
    return out


def parse_status_panel(proj_path: str) -> dict:
    """Pull the character/lock table out of foundation/STATUS_PANEL.md if present."""
    p = os.path.join(proj_path, "foundation", "STATUS_PANEL.md")
    if not os.path.exists(p):
        return {}
    text = read(p)
    _m = re.search(r"^Live edge:.*$", text, re.M)
    panel = {
        "live_edge_line": _m.group(0).strip() if _m else None,
        "artifacts": {},
    }
    for label, rx in (
        ("prose", r"Latest prose:\s*`?([^`\n]+?)`?\s*[—-]"),
        ("coverage", r"Latest coverage:\s*`?([^`\n]+?)`?\s*$"),
        ("validation", r"Latest validation:\s*`?([^`\n]+?)`?\s*$"),
        ("support_sync", r"Latest support sync:\s*`?([^`\n]+?)`?\s*$"),
    ):
        m = re.search(rx, text, re.M)
        if m:
            panel["artifacts"][label] = m.group(1).strip()
    chars = {}
    # markdown table rows:  | Name | value | value |
    for row in re.finditer(r"^\|([^\n]+)\|\s*$", text, re.M):
        cells = [c.strip() for c in row.group(1).split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", " ", ":"}:
            continue
        name = cells[0].strip("*` ")
        if not name or name.lower() in {"item", "character", "name", "state"}:
            continue
        chars[name] = cells[1:]
    panel.update({"path": "foundation/STATUS_PANEL.md", "rows": chars})
    return panel


def parse_characters_from_state_txt(text: str) -> dict:
    """The published state.txt 'CHARACTER LOCKS' section: '- Name: value'."""
    out = {}
    sec = re.search(
        r"CHARACTER LOCKS[^\n]*\n-{5,}\n(.*?)(?:\n[A-Z][A-Z ]{4,}|\Z)", text, re.S
    )
    if not sec:
        return out
    for m in re.finditer(r"^-\s*([^:]+):\s*(.+)$", sec.group(1), re.M):
        out[m.group(1).strip()] = m.group(2).strip()
    return out


def parse_firewalls_from_state_txt(text: str) -> list[dict]:
    out = []
    sec = re.search(
        r"KNOWLEDGE FIREWALLS[^\n]*\n-{5,}\n(.*?)(?:\n[A-Z][A-Z ]{4,}|\Z)", text, re.S
    )
    if not sec:
        return out
    body = sec.group(1)
    for m in re.finditer(
        r"^-\s*(.+?)\s*\[(.*?)\]\s*who:\s*(.*?)\n\s*earliest valid change:\s*(.+)$",
        body,
        re.M,
    ):
        out.append(
            {
                "name": m.group(1).strip(),
                "status": m.group(2).strip(),
                "who": m.group(3).strip(),
                "earliest_valid_change": m.group(4).strip(),
            }
        )
    return out


FIREWALL_SOURCES = [
    ("Yan identity firewall", "foundation/YAN_SHUOER_BEAUTY_IDENTITY_PRESSURE_LOCK.md"),
    ("Lan/Yan relationship + secrecy", "foundation/LAN_YAN_ROMANCE_LOCK.md"),
    ("Lan Platform (Spirit Ascension) policy", "foundation/SPIRIT_ASCENSION_PLATFORM_YAN_POLICY.md"),
    ("Soul Spirit mechanics / Yan audit", "foundation/SOUL_SPIRIT_MECHANICS_AND_YAN_AUDIT_LOCK.md"),
    ("Fourth soul spirit (Emerald Demon Bird)", "foundation/FOURTH_SOUL_SPIRIT_EMERALD_DEMON_BIRD_LOCK.md"),
    ("Fifth/sixth soul spirit (future)", "foundation/FUTURE_PHOENIX_FIFTH_SIXTH_SOUL_SPIRIT_LOCK.md"),
    ("Seventh-ninth godhood (future)", "foundation/FUTURE_PHOENIX_SEVENTH_NINTH_GODHOOD_LOCK.md"),
    ("Rainbow Dragon external second martial soul", "foundation/RAINBOW_DRAGON_EXTERNAL_SECOND_MARTIAL_SOUL_LOCK.md"),
    ("Level30 cocoon metamorphosis", "foundation/LEVEL30_COCOON_METAMORPHOSIS_LOCK.md"),
    ("Mid time-skip third soul spirit", "foundation/MID_TIME_SKIP_THIRD_SOUL_SPIRIT_LOCK.md"),
    ("Phoenix/dragon lore guard", "foundation/PHOENIX_DRAGON_LORE_GUARD.md"),
]


FIREWALL_NAMED = dict(FIREWALL_SOURCES)

# A project may declare its firewalls in one of these instead of per-lock files.
FIREWALL_GENERIC_SOURCES = ("foundation/KNOWLEDGE_FIREWALLS.md",)

# foundation/ files whose name marks them as a boundary document
FIREWALL_NAME_TOKENS = ("LOCK", "FIREWALL", "GUARD", "POLICY")


def _firewall_summary(text: str) -> str:
    for line in text.splitlines():
        t = line.strip().lstrip("#> -*").strip()
        if len(t) > 40:
            return t[:300]
    return ""


def _firewall_status(text: str) -> str:
    """A firewall the project itself still marks unresolved is not LOCKED."""
    low = text.lower()
    for marker in ("boundaries tbd", "still tbd", ": tbd", "tbd after", "tbd."):
        if marker in low:
            return "PARTIAL / TBD (see source file)"
    return "LOCKED (see source file)"


def firewalls_from_foundation(proj_path: str) -> list[dict]:
    """Knowledge firewalls, derived from the project's own foundation/ lock files.

    Discovery is generic. FIREWALL_SOURCES is only a display-label map for the SL4
    lock files; a project that declares firewalls in foundation/KNOWLEDGE_FIREWALLS.md,
    or in any foundation/*LOCK*.md / *FIREWALL*.md / *GUARD*.md / *POLICY*.md, is picked
    up without this scanner hard-coding its filenames.
    """
    out = []
    seen = set()

    def add(rel: str, name: str) -> None:
        if rel in seen:
            return
        p = os.path.join(proj_path, rel)
        if not os.path.isfile(p):
            return
        seen.add(rel)
        text = read(p)
        out.append({
            "name": name,
            "source": rel,
            "bytes": os.path.getsize(p),
            "sha256": sha16(open(p, "rb").read()),
            "summary": _firewall_summary(text),
            "status": _firewall_status(text),
        })

    for name, rel in FIREWALL_SOURCES:
        add(rel, name)
    for rel in FIREWALL_GENERIC_SOURCES:
        add(rel, os.path.basename(rel)[: -len(".md")].replace("_", " ").title())

    fdir = os.path.join(proj_path, "foundation")
    if os.path.isdir(fdir):
        for fn in sorted(os.listdir(fdir)):
            if not fn.endswith(".md"):
                continue
            if not any(tok in fn.upper() for tok in FIREWALL_NAME_TOKENS):
                continue
            rel = "foundation/" + fn
            add(rel, FIREWALL_NAMED.get(rel, fn[: -len(".md")].replace("_", " ").title()))

    return out


def collect_lock_cards(proj_path: str) -> list[dict]:
    """Lock cards are the generated .card.md files; search common locations."""
    cards = []
    for dirpath, dirnames, filenames in os.walk(proj_path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for fn in sorted(filenames):
            if not fn.endswith(".card.md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, proj_path).replace(os.sep, "/")
            if rel.split("/")[0] in RECEIPT_DIRS:
                continue
            cards.append(
                {
                    "id": fn[: -len(".card.md")],
                    "path": rel,
                    "bytes": os.path.getsize(full),
                    "sha256": sha16(open(full, "rb").read()),
                    "body": read(full).strip(),
                }
            )
    return cards


# --------------------------------------------------------------------------- #
# external state merge
# --------------------------------------------------------------------------- #
# The learned rules (decisions) and the 38 generated lock cards live in the human's
# storyos-home/, NOT inside the project folder. A project ZIP alone therefore shows
# learned=0 and locks=0, which understates the real canon. If a published mirror or
# manifest is supplied, merge it in -- always tagged with its provenance so nobody
# mistakes a merged value for one derived from the project's own files.

def load_external(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        return json.loads(read(path))
    except Exception as exc:  # noqa: BLE001
        return {"_parse_error": str(exc)}


def parse_mirror_state_txt(text: str) -> dict:
    """Extract learned rules from a published state.txt mirror block."""
    rules = []
    sec = re.search(r"BINDING LEARNED RULES[^\n]*\n(.*?)(?:\n[A-Z][A-Z ]{4,}|\Z)", text, re.S)
    if not sec:
        return {"decisions": rules}
    body = sec.group(1)
    for m in re.finditer(
        r"^(D\d+)\s*\[(\w+)\]\s*(.+?)\n"
        r"(?:\s*why:\s*(.+?)\n)?"
        r"(?:\s*never as achieved fact:\s*(.+?)\n)?"
        r"(?:\s*enforced patterns:\s*(.+?)\n)?",
        body, re.M):
        rules.append({
            "id": m.group(1), "kind": m.group(2), "rule": m.group(3).strip(),
            "why": (m.group(4) or "").strip(),
            "never_as_achieved_fact": (m.group(5) or "").strip(),
            "enforced_pattern": (m.group(6) or "").strip(),
            "source": "published mirror (paste.rs)",
            "provenance": "external",
        })
    return {"decisions": rules}


def collect_decisions(proj_path: str) -> list[dict]:
    """Learned rules: decisions.jsonl / decisions.md beside the project or inside it."""
    out = []
    for cand in (
        os.path.join(proj_path, "decisions.jsonl"),
        os.path.join(proj_path, "foundation", "decisions.jsonl"),
    ):
        if os.path.exists(cand):
            for line in read(cand).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    out.append({"raw": line})
            return out
    return out


def run_project_checker(proj_path: str) -> dict:
    """Run the project's OWN validator if it ships one. Never fatal."""
    tool = os.path.join(proj_path, "tools", "perfect_continuation_skill_check.py")
    if not os.path.exists(tool):
        return {"present": False}
    try:
        proc = subprocess.run(
            [sys.executable, tool],
            cwd=proj_path,
            capture_output=True,
            text=True,
            timeout=180,
        )
        kv = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        return {
            "present": True,
            "tool": os.path.relpath(tool, proj_path).replace(os.sep, "/"),
            "exit_code": proc.returncode,
            "result": kv.get("PERFECT_CONTINUATION_SKILL_CHECK_V2")
            or ("PASS" if proc.returncode == 0 else "FAIL"),
            "fields": kv,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-800:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"present": True, "error": str(exc)}


# --------------------------------------------------------------------------- #
# chapters
# --------------------------------------------------------------------------- #

FOOTER_RX = re.compile(r"\n---\n+\s*##\s*Footer\s*\n", re.I)


TITLE_RX = re.compile(r"^\s*#{1,6}\s*Chapter[_ ]?\d+.*\n?", re.I)


def split_chapter(text: str) -> tuple[str, str]:
    """Return (prose, footer). The leading `# Chapter N — Title` line is removed from the
    prose because the title is carried as structured metadata; leaving it in makes every
    reader page render the heading twice."""
    m = FOOTER_RX.search(text)
    if m:
        body, footer = text[: m.start()].strip(), text[m.end():].strip()
    else:
        body, footer = text.strip(), ""
    body = TITLE_RX.sub("", body, count=1).strip()
    return body, footer


def chapter_meta(text: str) -> dict:
    first = text.split("\n", 1)[0].strip()
    m = re.match(r"^#+\s*Chapter[_ ]?(\d+)\s*[—\-:]\s*(.+)$", first, re.I)
    if m:
        return {"n": int(m.group(1)), "title": m.group(2).strip()}
    m = re.match(r"^#+\s*Chapter[_ ]?(\d+)", first, re.I)
    if m:
        return {"n": int(m.group(1)), "title": first.split("—")[-1].strip(" -—:")}
    return {"n": None, "title": first.lstrip("# ").strip()}


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’\-]+", text))


def build_chapters(proj: dict, data_dir: str) -> list[dict]:
    cdir = os.path.join(proj["path"], "chapters")
    covdir = os.path.join(proj["path"], "canon_coverage")
    out = []
    if not os.path.isdir(cdir):
        return out
    for fn in sorted(os.listdir(cdir)):
        if not fn.lower().startswith("chapter_") or not fn.endswith(".md"):
            continue
        full = os.path.join(cdir, fn)
        raw = read(full)
        prose, footer = split_chapter(raw)
        meta = chapter_meta(raw)
        n = meta["n"]
        if n is None:
            m = re.search(r"(\d+)", fn)
            n = int(m.group(1)) if m else None
        cov = None
        if n is not None:
            for cand in (
                f"Canon_Coverage_Chapter_{n}.md",
                f"Canon_Coverage_Chapter_{n:02d}.md",
            ):
                p = os.path.join(covdir, cand)
                if os.path.exists(p):
                    cov = f"canon_coverage/{cand}"
                    break
        rec = {
            "n": n,
            "title": meta["title"],
            "file": f"chapters/{fn}",
            "prose_words": word_count(prose),
            "has_footer": bool(footer),
            "coverage": cov,
        }
        out.append(rec)
        payload = {
            "project": proj["id"],
            "n": n,
            "title": meta["title"],
            "file": rec["file"],
            "prose": prose,
            "footer": footer,
            "prose_words": rec["prose_words"],
            "coverage_file": cov,
            "coverage": read(os.path.join(proj["path"], cov)) if cov else None,
            "sha256": sha16(open(full, "rb").read()),
            "bytes": os.path.getsize(full),
        }
        d = os.path.join(data_dir, "chapters", proj["id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{n}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    out.sort(key=lambda r: (r["n"] is None, r["n"]))
    return out


# --------------------------------------------------------------------------- #
# vault
# --------------------------------------------------------------------------- #

def build_vault(proj: dict) -> list[dict]:
    files = []
    for full in walk_files(proj["path"]):
        rel = os.path.relpath(full, proj["path"]).replace(os.sep, "/")
        b = open(full, "rb").read()
        files.append(
            {
                "path": rel,
                "bytes": len(b),
                "sha256": sha16(b),
                "kind": classify(rel),
                "text": rel.endswith((".md", ".txt", ".json", ".py", ".jsonl", ".csv", ".html")),
            }
        )
    files.sort(key=lambda r: r["path"])
    return files


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/project/workspace-HANDOFF.md",
                    help="directory containing the project folders")
    ap.add_argument("--out", default=DATA)
    ap.add_argument("--external", default=os.path.join(SITE, "seed", "external_state.json"),
                    help="JSON with published decisions/lock cards to merge in. Lives in "
                         "seed/ (a committed INPUT) not data/ (generated output), so a "
                         "fresh clone reproduces the same state.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    data_dir = args.out
    os.makedirs(data_dir, exist_ok=True)

    projects = discover_projects(args.root)
    if not projects:
        print(f"no projects found under {args.root}", file=sys.stderr)
        return 1

    # Workspace-root handoff files sit OUTSIDE every project dir, so a per-project
    # scan never sees them. They are scanned separately and attributed by filename.
    root_files = [
        (fn, os.path.join(args.root, fn))
        for fn in sorted(os.listdir(args.root))
        if os.path.isfile(os.path.join(args.root, fn))
    ]

    index = {
        "system": "storyos-site",
        "schema": "storyos-site/2",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_root": args.root,
        "projects": {},
        "totals": {},
    }
    all_issues = {}

    for proj in projects:
        pid = proj["id"]
        manifest = load_manifest(proj["path"])
        edge = edge_from_manifest(manifest)
        panel = parse_status_panel(proj["path"])

        # published state.txt if the project ships one (used for firewalls/characters)
        state_txt = ""
        for cand in ("state.txt", os.path.join("foundation", "state.txt")):
            p = os.path.join(proj["path"], cand)
            if os.path.exists(p):
                state_txt = read(p)
                break

        ext = load_external(args.external)
        ext_proj = (ext.get("projects") or {}).get(pid, {}) if ext else {}
        ext_decisions = ext_proj.get("decisions") or []
        ext_locks = ext_proj.get("locks") or []
        if not ext_decisions and ext.get("mirror_text"):
            ext_decisions = parse_mirror_state_txt(ext["mirror_text"]).get("decisions", [])
        for d in ext_decisions:
            d.setdefault("provenance", "external")
        for l in ext_locks:
            l.setdefault("provenance", "external")

        checker = run_project_checker(proj["path"])
        checker_edge = None
        m = re.search(r"latest=Chapter(\d+)", checker.get("stdout_tail", "") or "")
        if m:
            checker_edge = int(m.group(1))

        paths = driftmod.collect_active_paths(proj["path"])
        # attribute workspace-root files to this project by filename/label match
        tag = proj["dir"].upper()
        paths += [(driftmod.ROOT_PREFIX + fn, full) for fn, full in root_files
                  if tag.split("_")[0] in fn.upper()
                  or proj["dir"].split("_")[0] in fn.lower()]
        drift = driftmod.scan_paths(paths, edge.get("fic_chapter"),
                                    skip={MANIFEST_REL})
        gap = driftmod.scanner_gap_proof(drift["findings"], manifest)

        chapters = build_chapters(proj, data_dir)
        vault = build_vault(proj)
        locks = collect_lock_cards(proj["path"])
        decisions = collect_decisions(proj["path"])

        # integrity: does the project's own checker agree with the manifest?
        disagreements = []
        if checker_edge and edge.get("fic_chapter") and checker_edge != edge["fic_chapter"]:
            disagreements.append(
                f"checker says latest=Chapter{checker_edge}, manifest says "
                f"Chapter{edge['fic_chapter']}"
            )
        if manifest.get("_parse_error"):
            disagreements.append(f"manifest parse error: {manifest['_parse_error']}")
        if not manifest:
            disagreements.append(f"{MANIFEST_REL} absent — no authoritative edge")

        state = {
            "project": pid,
            "label": proj["label"],
            "dir": proj["dir"],
            "generated_utc": index["generated_utc"],
            "authority": MANIFEST_REL if manifest else None,
            "edge": edge,
            "manifest": manifest,
            "status_panel": panel,
            "characters": characters_from_manifest(manifest)
            or parse_characters_from_state_txt(state_txt),
            "firewalls": parse_firewalls_from_state_txt(state_txt)
            or firewalls_from_foundation(proj["path"]),
            "locks": locks + ext_locks,
            "decisions": decisions + ext_decisions,
            "external_state": {
                "merged": bool(ext_decisions or ext_locks),
                "source": args.external,
                "decisions_merged": len(ext_decisions),
                "locks_merged": len(ext_locks),
                "note": "Learned rules and generated lock cards live in the human's "
                        "storyos-home/, not inside the project folder. Values marked "
                        "provenance=external came from the published mirror/manifest, "
                        "not from these project files.",
            },
            "project_checker": checker,
            "chapters": chapters,
            "integrity": {
                "disagreements": disagreements,
                "drift_findings": len(drift["findings"]),
                "checker_result": checker.get("result"),
                "checker_stale_count": checker.get("fields", {}).get("active_stale_issues"),
            },
        }
        os.makedirs(os.path.join(data_dir, "state"), exist_ok=True)
        with open(os.path.join(data_dir, "state", f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)

        os.makedirs(os.path.join(data_dir, "vault"), exist_ok=True)
        with open(os.path.join(data_dir, "vault", f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump({"project": pid, "files": vault}, f, ensure_ascii=False, indent=1)

        all_issues[pid] = {
            "drift": drift,
            "scanner_gap": gap,
            "integrity": state["integrity"],
            "workspace_root_files_scanned": [
                fn for fn, _ in root_files
                if tag.split("_")[0] in fn.upper()
                or proj["dir"].split("_")[0] in fn.lower()
            ],
        }

        gate = "PASS"
        if disagreements or drift["findings"]:
            gate = "WARN"
        if not manifest:
            gate = "FAIL"

        index["projects"][pid] = {
            "label": proj["label"],
            "gate": gate,
            "edge": edge,
            "counts": {
                "chapters": len([c for c in chapters if c["n"] is not None]),
                "prose_words": sum(c["prose_words"] for c in chapters),
                "files": len(vault),
                "bytes": sum(v["bytes"] for v in vault),
                "locks": len(locks) + len(ext_locks),
                "decisions": len(decisions) + len(ext_decisions),
                "locks_from_project": len(locks),
                "decisions_from_project": len(decisions),
                "external_merged": len(ext_locks) + len(ext_decisions),
                "firewalls": len(state["firewalls"]),
                "characters": len(state["characters"]),
                "receipts": len([v for v in vault if v["kind"] == "receipt"]),
            },
            "kinds": {},
            "project_checker": {
                "present": checker.get("present"),
                "result": checker.get("result"),
                "fields": checker.get("fields", {}),
            },
            "drift_findings": len(drift["findings"]),
            "integrity": state["integrity"],
        }
        kinds: dict[str, int] = {}
        for v in vault:
            kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
        index["projects"][pid]["kinds"] = kinds

    index["totals"] = {
        "projects": len(projects),
        "chapters": sum(p["counts"]["chapters"] for p in index["projects"].values()),
        "prose_words": sum(p["counts"]["prose_words"] for p in index["projects"].values()),
        "files": sum(p["counts"]["files"] for p in index["projects"].values()),
        "bytes": sum(p["counts"]["bytes"] for p in index["projects"].values()),
        "drift_findings": sum(p["drift_findings"] for p in index["projects"].values()),
    }

    with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    with open(os.path.join(data_dir, "issues.json"), "w", encoding="utf-8") as f:
        json.dump(all_issues, f, ensure_ascii=False, indent=1)

    if not args.quiet:
        t = index["totals"]
        print(f"built {t['projects']} project(s), {t['chapters']} chapters, "
              f"{t['prose_words']:,} words, {t['files']} files, "
              f"{t['bytes']/1048576:.2f} MB")
        for pid, p in index["projects"].items():
            e = p["edge"]
            print(f"  {pid:38} gate={p['gate']:5} edge=Ch{e.get('fic_chapter')} "
                  f"next=Ch{e.get('next_fic_chapter')} src={e.get('next_source')} "
                  f"drift={p['drift_findings']} "
                  f"checker={p['project_checker'].get('result')}")
        print(f"  -> {data_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
