#!/usr/bin/env python3
"""
storyos — the growth engine. A StoryOS home holds every project, and every project
accumulates permanently, so the system gets stronger the more you use it.

  storyos init                              create ~/storyos-home
  storyos use <path> --name <name>          register (or update) a project
  storyos list                              all registered projects + their growth
  storyos scan   [--project NAME]           re-derive state from the project's files
  storyos gate   [--project NAME]           run the validator (pre-draft gate)
  storyos learn  --what "..." --rule "..."  turn a rejection/correction into a PERMANENT lock
  storyos enforce --pattern "<regex>"       make a rule machine-checkable
  storyos status [--project NAME] [--json]  growth report
  storyos export [--project NAME] [--out F] build a handoff bundle for another agent
  storyos serve  [--port P]                 online control centre for every project

Storage layout ($STORYOS_HOME, default ~/storyos-home):
  registry.json                 projects + paths
  projects/<name>/decisions.jsonl   APPEND-ONLY. Nothing is ever deleted or overwritten.
  projects/<name>/locks/*.card.md   one card per accepted decision
  projects/<name>/state/          generated STORYOS_STATE.json, docs, site
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
import zipfile
from pathlib import Path

HOME = Path(os.environ.get("STORYOS_HOME", str(Path.home() / "storyos-home")))
SCRIPTS = Path(__file__).resolve().parent           # tools/
REPO = SCRIPTS.parent


def home(create: bool = False) -> Path:
    if not HOME.exists():
        if not create:
            sys.exit(f"storyos: no home at {HOME} — run `storyos init`")
        (HOME / "projects").mkdir(parents=True)
        (HOME / "registry.json").write_text(json.dumps({"projects": {}}, indent=2))
    return HOME


def registry() -> dict:
    f = home() / "registry.json"
    return json.loads(f.read_text()) if f.exists() else {"projects": {}}


def save_registry(r: dict) -> None:
    (home() / "registry.json").write_text(json.dumps(r, indent=2) + "\n")


def resolve(name: str | None) -> tuple[str, dict]:
    r = registry()
    projs = r["projects"]
    if not projs:
        sys.exit("storyos: no projects registered — run `storyos use <path> --name <name>`")
    if name:
        if name not in projs:
            sys.exit(f"storyos: unknown project '{name}'. Known: {', '.join(projs)}")
        return name, projs[name]
    if len(projs) == 1:
        return next(iter(projs.items()))
    default = r.get("default")
    if default and default in projs:
        return default, projs[default]
    sys.exit(f"storyos: multiple projects, pass --project. Known: {', '.join(projs)}")


def proj_dir(entry: dict) -> Path:
    p = Path(entry["path"])
    if not p.exists():
        sys.exit(f"storyos: project path missing: {p}")
    return p


def store(name: str) -> Path:
    d = home() / "projects" / name
    (d / "locks").mkdir(parents=True, exist_ok=True)
    (d / "state").mkdir(parents=True, exist_ok=True)
    return d


def decisions(name: str) -> list[dict]:
    f = store(name) / "decisions.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"_corrupt": line[:120]})
    return out


# ------------------------------------------------------------------ commands
def cmd_init(a) -> int:
    home(create=True)
    print(f"storyos home: {HOME}")
    print("  registry.json")
    print("  projects/")
    print("Next: storyos use <project_path> --name <name>")
    return 0


def cmd_use(a) -> int:
    home(create=True)
    p = Path(a.path).resolve()
    if not p.is_dir():
        sys.exit(f"storyos: not a directory: {p}")
    name = a.name or p.name
    r = registry()
    isNew = name not in r["projects"]
    r["projects"][name] = {"path": str(p), "added": dt.datetime.now().strftime("%Y-%m-%d"),
                           "label": a.label or name}
    r.setdefault("default", name)
    save_registry(r)
    store(name)
    print(f"{'registered' if isNew else 'updated    '}: {name}  →  {p}")
    print("  run: storyos scan --project " + name)
    return 0


def cmd_list(a) -> int:
    r = registry()
    if not r["projects"]:
        print("no projects yet — storyos use <path> --name <name>")
        return 0
    print(f"{'project':<22}{'decisions':>10}{'locks':>7}{'enforced':>10}  path")
    for name, e in r["projects"].items():
        ds = decisions(name)
        live = [d for d in ds if d.get("status", "active") == "active"]
        enf = sum(len(d.get("enforce_regexes") or []) + len(d.get("tokens") or []) for d in live)
        locks = len(list((store(name) / "locks").glob("*.card.md")))
        print(f"{name:<22}{len(ds):>10}{locks:>7}{enf:>10}  {e['path']}")
    return 0


def _run(cmd: list[str], cwd=None) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def cmd_scan(a) -> int:
    name, entry = resolve(a.project)
    p = proj_dir(entry)
    out = store(name) / "state"
    for cand in ("audits", "foundation"):
        corpus = p / cand
        if corpus.is_dir() and any(corpus.glob("*.md")):
            break
    rc, txt = _run([sys.executable, str(REPO / "scripts" / "scan_project.py"),
                    str(corpus), str(p), str(out)])
    print(txt)
    if rc == 0:
        _run([sys.executable, str(REPO / "scripts" / "gen_docs.py"), str(out)])
        _run([sys.executable, str(REPO / "scripts" / "build_site.py"), str(p), str(out / "site")])
        # merge learned decisions into the generated state
        ds = [d for d in decisions(name) if d.get("status", "active") == "active"]
        sf = out / "STORYOS_STATE.json"
        if sf.exists():
            st = json.loads(sf.read_text())
            st["learned"] = ds
            st["growth"] = growth_metrics(name)
            sf.write_text(json.dumps(st, indent=2, ensure_ascii=False))
        print("\ngate snapshot:")
        rc2, t2 = cmd_status(argparse.Namespace(project=name, as_json=False), quiet=True)
        print(t2 or "")
    return rc


def growth_metrics(name: str) -> dict:
    ds = decisions(name)
    live = [d for d in ds if d.get("status", "active") == "active"]
    by: dict[str, int] = {}
    for d in live:
        k = d.get("kind", "note")
        by[k] = by.get(k, 0) + 1
    return {"decisions_total": len(ds), "decisions_active": len(live),
            "by_kind": by,
            "enforceable": sum(len(d.get("enforce_regexes") or []) + len(d.get("tokens") or [])
                              for d in live),
            "locks_written": len(list((store(name) / "locks").glob("*.card.md"))),
            "last_decision_on": live[-1].get("date") if live else None}


def cmd_status(a) -> int:
    name, entry = resolve(a.project)
    p = proj_dir(entry)
    g = growth_metrics(name)
    gate_rc, gate_txt = _run([sys.executable, str(SCRIPTS / "storyos_validate.py"),
                              "--project", str(p), "--phase", "full", "--json"])
    try:
        gate = json.loads(gate_txt.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        gate = {"result": "UNKNOWN", "errors": None, "warnings": None, "findings": [gate_txt[:400]]}
    if a.as_json:
        print(json.dumps({"project": name, "path": str(p), "growth": g, "gate": gate}, indent=2))
        return 0
    if getattr(a, "quiet", False):
        return gate["errors"] or 0, gate_txt
    e = gate.get("edge") or {}
    print(f"── {name} ──  {p}")
    print(f"  live edge     : after Chapter{e.get('fic_chapter','?')} “{e.get('fic_title','')}”")
    print(f"  gate          : {gate['result']}  (errors={gate['errors']}, warnings={gate['warnings']})")
    for f in (gate.get("findings") or [])[:6]:
        print(f"    · {f[:160]}")
    print("  growth        :")
    print(f"    decisions   : {g['decisions_total']} recorded, {g['decisions_active']} active")
    print(f"    by kind     : {g['by_kind'] or '—'}")
    print(f"    locks       : {g['locks_written']} cards")
    print(f"    enforced    : {g['enforceable']} machine-checkable rules")
    print(f"    last on     : {g['last_decision_on'] or '—'}")
    if g["decisions_total"] == 0:
        print("    note        : nothing learned yet — run `storyos learn` after any rejection")
    return 0


def cmd_learn(a) -> int:
    name, entry = resolve(a.project)
    d = store(name)
    before = growth_metrics(name)["enforceable"]
    did = f"D{len(decisions(name)) + 1:04d}"
    rec = {"id": did, "date": dt.date.today().isoformat(), "project": name,
           "kind": a.kind, "status": "active", "what": a.what, "rule": a.rule,
           "why": a.why or "", "tokens": [t for t in (a.token or [])],
           "enforce_regexes": [r for r in (a.pattern or [])],
           "scope": a.scope}
    for r in rec["enforce_regexes"]:
        try:
            re.compile(r)
        except re.error as ex:
            sys.exit(f"storyos learn: rejecting {did} — invalid regex {r!r}: {ex}")
    with (d / "decisions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    card = [f"# Lock {did} — {a.rule[:70]}", "",
            f"Generated by `storyos learn` on {rec['date']}. Append-only history: this decision",
            "is never deleted, only superseded by a later one that cites it.", "",
            "```storyos-meta", json.dumps({"card": "learned-lock", "id": did, "kind": a.kind,
                                          "status": "active", "scope": a.scope,
                                          "tokens": rec["tokens"],
                                          "enforce_regexes": rec["enforce_regexes"]}, indent=2),
            "```", "", f"**What happened:** {a.what}", "", f"**Rule now in force:** {a.rule}", ""]
    if rec["why"]:
        card += [f"**Why:** {rec['why']}", ""]
    if rec["tokens"]:
        card += ["**Regression tokens (hard-grep):** " + ", ".join(f"`{t}`" for t in rec["tokens"]), ""]
    if rec["enforce_regexes"]:
        card += ["**Machine-enforced patterns:**",
                 *[f"- `{r}`" for r in rec["enforce_regexes"]], ""]
    (d / "locks" / f"{did}.card.md").write_text("\n".join(card), encoding="utf-8")

    after = growth_metrics(name)["enforceable"]
    print(f"{did} recorded ({a.kind}) — permanent.")
    print(f"  lock card : projects/{name}/locks/{did}.card.md")
    print(f"  enforceable rules: {before} → {after} (+{after - before})")
    print(f"  next gate run will fail any prose matching it.")
    return 0


def cmd_enforce(a) -> int:
    a.kind, a.what = "enforcement", a.what or "explicit enforcement addition"
    a.rule = a.rule or "pattern is forbidden in live prose"
    a.pattern = [a.pattern_]
    a.token = []
    a.scope = "story-prose"
    a.project, a.why = a.project, ""
    return cmd_learn(a)


def cmd_export(a) -> int:
    name, entry = resolve(a.project)
    p = proj_dir(entry)
    out = Path(a.out or f"storyos-handoff-{name}.zip").resolve()
    st = store(name)
    ds = decisions(name)
    brief = render_brief(name, p, ds, growth_metrics(name))
    (st / "AGENT_BRIEF.md").write_text(brief, encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(st / "AGENT_BRIEF.md", f"{name}/AGENT_BRIEF.md")
        z.write(st / "decisions.jsonl", f"{name}/decisions.jsonl") if (st / "decisions.jsonl").exists() else None
        for f in sorted((st / "locks").glob("*.card.md")):
            z.write(f, f"{name}/locks/{f.name}")
        for f in sorted((st / "state").rglob("*")):
            if f.is_file():
                z.write(f, f"{name}/state/{f.relative_to(st / 'state')}")
        z.write(REPO / "AGENT_ONBOARDING.md", f"{name}/SYSTEM/AGENT_ONBOARDING.md")
        z.write(REPO.parent / "storyos" / "tools" / "storyos_validate.py",
                f"{name}/SYSTEM/tools/storyos_validate.py")
        for f in sorted((REPO.parent / "storyos" / "scripts").glob("*.py")):
            z.write(f, f"{name}/SYSTEM/scripts/{f.name}")
        for f in sorted((REPO.parent / "storyos" / "templates").glob("*")):
            if f.is_file():
                z.write(f, f"{name}/SYSTEM/templates/{f.name}")
        if a.include_prose:
            for sub in ("chapters", "canon_coverage", "foundation", "codex", "bible"):
                d = p / sub
                if d.is_dir():
                    for f in sorted(d.rglob("*.md")):
                        z.write(f, f"{name}/project/{f.relative_to(p)}")
    n = len(zipfile.ZipFile(out).namelist())
    size = out.stat().st_size / 1024
    print(f"handoff bundle: {out}")
    print(f"  {n} entries, {size:.0f} KB · {len(ds)} decisions · "
          f"{'includes prose' if a.include_prose else 'state only (safe to hand over)'}")
    print("  A new agent reads AGENT_BRIEF.md, then SYSTEM/AGENT_ONBOARDING.md, then state/.")
    return 0


def render_brief(name: str, p: Path, ds: list[dict], g: dict) -> str:
    live = [d for d in ds if d.get("status", "active") == "active"]
    lines = [f"# Agent Brief — {name}", "",
             f"Project root (on the source machine): `{p}`",
             f"Decisions on record: **{g['decisions_total']}** ({g['decisions_active']} active) · "
             f"machine-enforced rules: **{g['enforceable']}**", "",
             "## What this project is",
             "Continue an existing StoryOS project. Do not restart it, and do not draft prose",
             "until the gate passes.", "", "## Hard rules learned so far (all binding)", ""]
    if not live:
        lines.append("_None recorded yet._ Follow the project's own foundation/ and codex/.")
    for d in live:
        lines.append(f"- **{d['id']}** ({d.get('kind')}): {d.get('rule')}")
        if d.get("tokens"):
            lines.append(f"  - never appear as achieved fact: {', '.join(d['tokens'])}")
        if d.get("enforce_regexes"):
            lines.append(f"  - enforced patterns: {'; '.join(d['enforce_regexes'])}")
    lines += ["", "## First three commands", "```bash",
              "python3 SYSTEM/tools/storyos_validate.py --project . --phase pre",
              "python3 SYSTEM/tools/storyos_validate.py --selftest      # trust the checker",
              "cat state/STATUS_PANEL.md                                 # live state", "```", "",
              "## Contract",
              "- Newest dated receipt **on the active branch** is live state; archived receipts are evidence.",
              "- Author knowledge is never character knowledge.",
              "- Missing canon is reported as missing, never invented.",
              "- If you find a conflict, report both sources with dates and wait.", ""]
    return "\n".join(lines)


def cmd_serve(a) -> int:
    env = dict(os.environ, STORYOS_HOME=str(HOME))
    print(f"serving StoryOS home {HOME} → http://0.0.0.0:{a.port}")
    os.execvpe(sys.executable, [sys.executable, str(SCRIPTS / "server.py"),
                                "--port", str(a.port)], env)


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(prog="storyos", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    s = sub.add_parser("use"); s.add_argument("path"); s.add_argument("--name")
    s.add_argument("--label"); s.set_defaults(fn=cmd_use)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    s = sub.add_parser("scan"); s.add_argument("--project"); s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("gate"); s.add_argument("--project"); s.add_argument("--phase", default="full")
    def _gate(a2):
        name, entry = resolve(a2.project)
        rc, txt = _run([sys.executable, str(SCRIPTS / "storyos_validate.py"),
                        "--project", proj_dir(entry), "--phase", a2.phase])
        print(txt)
        return rc
    s.set_defaults(fn=_gate)

    s = sub.add_parser("status"); s.add_argument("--project"); s.add_argument("--json", dest="as_json",
                                                                  action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("learn", help="turn a rejection/correction into a permanent lock")
    s.add_argument("--project"); s.add_argument("--what", required=True)
    s.add_argument("--rule", required=True); s.add_argument("--why")
    s.add_argument("--kind", default="correction",
                   choices=["rejection", "correction", "preference", "mechanics", "enforcement"])
    s.add_argument("--token", action="append", help="value that must never appear as achieved fact")
    s.add_argument("--pattern", action="append", help="regex the gate will fail on")
    s.add_argument("--scope", default="story-prose")
    s.set_defaults(fn=cmd_learn)

    s = sub.add_parser("enforce"); s.add_argument("--project"); s.add_argument("pattern_")
    s.add_argument("--what"); s.add_argument("--rule")
    s.set_defaults(fn=cmd_enforce)

    s = sub.add_parser("export"); s.add_argument("--project"); s.add_argument("--out")
    s.add_argument("--include-prose", action="store_true")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=4180)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
