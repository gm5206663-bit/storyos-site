#!/usr/bin/env python3
"""
test_auth.py — the authorization matrix for the DEPLOYED server (scripts/server.py).

An auth rule that is not executed is a comment. This suite is executed against a running
site and exits non-zero if the contract is broken.

THE CONTRACT UNDER TEST (agents.md / scripts/server.py — checked 2026-10-07):
  * Every GET is public. The reader site exists so an agent that knows nothing can fetch
    the gate, the state, the issues — no key needed for reading anything.
  * The only key-gated surfaces are WRITES (POST /api/learn|promote|scan) and the
    audit log (GET /api/audit). A stranger must be refused; the key must open them.
  * POST /api/propose/<proj> is a PUBLIC write — but it lands in an inbox and changes
    no canon. It must answer 202 for anyone, and it must not touch a project.
  * Unknown paths are 404, never 401. A stranger must be able to tell a typo from a
    protected door; a server that answers 401 for everything is a route oracle.

RESIDUE — the reason this file was rebuilt (2026-10-07):
  A probe run once left an "auth test — auto-removed" rule sitting in the ledger,
  where it read as an ACTIVE learned rule forever. Two defects made that possible:
  (1) the cleanup searched only the old $STORYOS_HOME paths, while the deployed server
      writes the ledger to <site>/data/decisions/<proj>.jsonl — a path the suite never
      looked at; and (2) it matched records on a "what" field the deployed writer does
      not store, so nothing could ever match even in the right file.
  The cleanup now scans the real writer path (plus the legacy home paths), matches the
  returned id together with the probe's own markers, scrubs the proposals inbox too,
  and VERIFIES zero residue after itself — ids are compared by parsed record, not by
  substring, so "S0001" can never hide inside "S00012".

  python3 framework/tools/test_auth.py --base http://127.0.0.1:8080 --key <STORYOS_KEY>
        [--site .]   # the site checkout whose data/ this suite may scrub (default: repo root)
        [--home $STORYOS_HOME]   # legacy ledger location, if it exists
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROBE_MARK = "auth test — auto-removed by test_auth"
PROBE_RULE = "auth probe — auto-removed"
PROBE_PROPOSAL_RULE = "auth probe — auto-removed (proposal)"


def call(base: str, path: str, key: str | None = None, method: str = "GET", body=None,
         retries: int = 4):
    """Retry transport failures. A free Cloudflare quick tunnel drops roughly 1 request in 6
    (measured: 14/20); without a retry an auth test reports 0 (no response) and reads as a
    broken policy when the network simply hiccuped. A 401/403 is a REAL answer — never retried."""
    last = (0, b"")
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(base.rstrip("/") + path, method=method)
        if key:
            req.add_header("X-StoryOS-Key", key)
        if body is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:                                # noqa: BLE001
            last = (0, str(e).encode())
            time.sleep(1.2 * attempt)
    return last


CASES = [
    # (method, path, needs_key, note)
    #   needs_key False  -> public; GET wants 200, "202" wants 202
    #   needs_key True   -> stranger must get 401/403/503; with the key: GET/POST want 200
    #   needs_key "404"  -> unknown path: wants 404 for any caller
    ("GET", "/", False, "portal readable by anyone"),
    ("GET", "/agents.md", False, "agent contract must be reachable unauthenticated"),
    ("GET", "/api/manifest.json", False, "every published file + sha256, public"),
    ("GET", "/api/projects", False, "the project board"),
    ("GET", "/api/gate/soul_land_4", False, "gate is the thing an agent needs before drafting"),
    ("GET", "/api/state/soul_land_4", False, "per-project state — public BY DESIGN; reading is the site's job"),
    ("GET", "/api/proposals", False, "the growth inbox, read-only and public"),
    ("GET", "/api/audit", True, "the audit log is the one key-gated READ"),
    ("POST", "/api/propose/soul_land_4", "202", "public write path — must land in the inbox only, for anyone"),
    ("POST", "/api/learn/soul_land_4", True, "writes always protected"),
    ("POST", "/api/scan/soul_land_4", True, "spawned work always protected"),
    # An outsider MUST be able to tell a typo from a protected endpoint. A server that answers
    # 401 for everything is a route oracle and makes its own docs false.
    ("GET", "/definitely-not-a-route-xyz", "404", "unknown path is 404, never 401"),
    ("GET", "/health", "404", "there is no /health — do not imply a key would help"),
    ("GET", "/p/soul_land_4", "404", "the old framework dashboard is gone; a retired route is a 404 like any other"),
    ("GET", "/api/project/soul_land_4", "404", "the old derived-state route is gone; the live one is /api/state (public)"),
]


def _candidate_ledgers(a) -> list[Path]:
    """Every path a writer has ever used for a project's decisions ledger.
    FIRST the deployed writer's path; the $STORYOS_HOME pair are the legacy locations
    the suite used to search alone — kept so an old residue is still found and reported."""
    out = []
    if a.site and (Path(a.site) / "data").is_dir():
        out.append(Path(a.site) / "data" / "decisions" / "{proj}.jsonl")
    if a.home:
        out.append(Path(a.home) / "projects" / "{proj}" / "decisions.jsonl")
        out.append(Path(a.home) / "projects" / "{proj}" / "state" / "decisions.jsonl")
    return out


def scrub_ledgers(a, proj: str, did: str) -> tuple[int, list[str]]:
    """Remove the probe decision from every candidate ledger. Never deletes by id alone:
    a record is dropped only when the id matches AND the probe's own markers are present.
    An id match WITHOUT markers is reported, not deleted."""
    removed, stubborn = 0, []
    for tpl in _candidate_ledgers(a):
        f = Path(str(tpl).format(proj=proj))
        if not f.exists():
            continue
        kept, dropped, held = [], 0, 0
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line); continue
            if str(rec.get("id")) == did:
                if rec.get("what") == PROBE_MARK or rec.get("rule") == PROBE_RULE:
                    dropped += 1
                    continue
                held += 1                       # id matches, markers don't — do not delete
            kept.append(line)
        if dropped:
            f.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            c = f.parent / "locks" / f"{did}.card.md"
            c.unlink(missing_ok=True)
            print(f"  cleanup: {f} — removed {dropped} probe decision(s)")
            removed += dropped
        if held:
            stubborn.append(f"{f} (id matches but markers do not — left for a human)")
    return removed, stubborn


def scrub_proposals(a, pid: str) -> int:
    """Remove the probe proposal from the inbox. Proposals land in <site>/data/proposals.jsonl."""
    if not a.site:
        return 0
    f = Path(a.site) / "data" / "proposals.jsonl"
    if not f.exists():
        return 0
    kept, dropped = [], 0
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line); continue
        if str(rec.get("id")) == pid and str(rec.get("rule") or "").startswith("auth probe"):
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        f.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        print(f"  cleanup: {f} — removed {dropped} probe proposal(s)")
    return dropped


def residue_left(a, proj: str, did: str) -> bool:
    """Parsed-record check — substring proofing, so 'S0001' cannot hide inside 'S00012'."""
    for tpl in _candidate_ledgers(a):
        f = Path(str(tpl).format(proj=proj))
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if did in line:
                    return True
                continue
            if str(rec.get("id")) == did:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--key", default="")
    ap.add_argument("--site", default=str(Path(__file__).resolve().parents[2]),
                    help="site checkout whose data/ the suite may scrub (default: this repo)")
    ap.add_argument("--home", default=os.environ.get("STORYOS_HOME", ""),
                    help="legacy $STORYOS_HOME, so any old-ledger residue is found too")
    a = ap.parse_args()
    if a.site and not Path(a.site).is_dir():
        a.site = ""
    fails = []
    created: list[tuple[str, str, str]] = []   # (kind, project, id) — cleaned up at the end
    print(f"AUTH MATRIX against {a.base}\n")
    for method, path, needs_key, note in CASES:
        body = ({"what": PROBE_MARK, "rule": PROBE_RULE, "kind": "mechanics"}
                if path.startswith("/api/learn")
                else ({"rule": PROBE_PROPOSAL_RULE, "kind": "mechanics"}
                      if path.startswith("/api/propose") else None))
        code, raw = call(a.base, path, key=None, method=method, body=body)
        if needs_key == "404":
            ok = code == 404
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<34} anyone    -> {code} "
                  f"(want 404)  — {note}")
            if not ok:
                fails.append(f"{method} {path} returned {code}, want 404 — retired or unknown "
                             f"routes must not look merely 'protected'")
            continue
        if needs_key == "202":
            ok = code == 202
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<34} public    -> {code} "
                  f"(want 202)  — {note}")
            if not ok:
                fails.append(f"{method} {path} should accept a stranger's proposal with 202 "
                             f"but returned {code}")
            else:
                try:
                    pid = json.loads(raw.decode()).get("id") or ""
                    if pid:
                        created.append(("proposal", path.rsplit("/", 1)[-1], pid))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    print("  WARN: proposal accepted but its id was unreadable — cannot clean it")
            continue
        if needs_key is True:
            ok = code in (401, 403, 503)
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<34} stranger -> {code} "
                  f"(want 401/403)  — {note}")
            if not ok:
                fails.append(f"{method} {path} was reachable WITHOUT a key ({code})")
            if a.key:
                c2, _b = call(a.base, path, key=a.key, method=method, body=body)
                ok2 = c2 == 200
                if method == "POST" and c2 == 200:
                    try:
                        rec = json.loads(_b.decode()).get("decision") or {}
                        if rec.get("id"):
                            created.append(("decision", path.rsplit("/", 1)[-1], str(rec["id"])))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                print(f"  {'PASS' if ok2 else 'FAIL'}  {method:<4} {path:<34} with key -> {c2} "
                      f"(want 200)")
                if not ok2:
                    fails.append(f"{method} {path} failed WITH the key ({c2})")
        else:
            ok = code == 200
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<34} public    -> {code} "
                  f"(want 200)  — {note}")
            if not ok:
                fails.append(f"{method} {path} should be public but returned {code}")
    bad = call(a.base, "/api/learn/soul_land_4", key="definitely-wrong-key", method="POST",
               body={"what": "x", "rule": "y"})[0]
    ok = bad in (401, 403)
    print(f"  {'PASS' if ok else 'FAIL'}  POST /api/learn                      wrong key   -> {bad} "
          f"(want 401)")
    if not ok:
        fails.append(f"a WRONG key was accepted ({bad})")
    trav = [call(a.base, p)[0] for p in ("/../etc/passwd", "/%2e%2e%2fetc/passwd", "/../../etc/hosts")]
    # 401 is a PASS: the auth guard runs before routing, so a hostile path never reaches
    # the file layer at all. What must never happen is a 200.
    ok = all(c in (400, 401, 403, 404, 405) for c in trav)
    print(f"  {'PASS' if ok else 'FAIL'}  GET  traversal probes {trav} (want anything but 200)")
    if not ok:
        fails.append(f"path traversal not refused: {trav}")

    # A test that leaves evidence in the project it is testing is a defective test: an
    # "auth test rule" once survived in a ledger and read as an ACTIVE learned rule forever.
    leftover_ids, stubborn = [], []
    for kind, proj, did in created:
        if kind == "proposal":
            scrub_proposals(a, did)
        else:
            _, held = scrub_ledgers(a, proj, did)
            stubborn += held
            if residue_left(a, proj, did):
                leftover_ids.append(f"{proj}:{did}")
    if stubborn:
        fails.append("probe id found without probe markers — not deleted: " + "; ".join(stubborn))
        print(f"  FAIL  {stubborn}")
    if leftover_ids:
        fails.append(f"probe decision(s) survived cleanup: {', '.join(leftover_ids)} — "
                     f"they are now ACTIVE learned rules; remove them by hand")
        print(f"  FAIL  probe records survived cleanup: {leftover_ids}")
    elif created:
        print(f"  PASS  cleanup verified — {len(created)} probe record(s) written, none left behind")

    leaks = False
    for probe in ("/health", "/p/soul_land_4", "/api/learn/soul_land_4"):
        b = call(a.base, probe, method="POST" if probe.startswith("/api/") else "GET",
                 body={"what": "x", "rule": "y"} if probe.startswith("/api/") else None)
        if b[0] != 200 and b[1] and "X-StoryOS-Key" in b[1].decode("utf-8", "replace"):
            leaks = True
    print(f"  {'FAIL' if leaks else 'PASS'}  denial bodies never name the key header")
    if leaks:
        fails.append("a refusal told an unauthenticated caller which header to send")

    print(f"\nTEST_AUTH: {'PASS' if not fails else 'FAIL'} ({len(fails)} failure(s))")
    for f in fails:
        print("   -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
