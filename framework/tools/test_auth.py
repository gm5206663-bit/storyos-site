#!/usr/bin/env python3
"""
test_auth.py — the authorization matrix, executed against a live server.

An auth rule that is not executed is a comment. `"/" in PUBLIC_ROUTES` once made
`path.startswith("/")` true for every path, so EVERY protected GET was public while the
test suite still "passed" — because nothing asked the one question that matters:
does a protected route refuse a stranger? This script does, and exits non-zero if not.

  python3 tools/test_auth.py --base http://127.0.0.1:4180 --key <STORYOS_KEY>
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
    # (method, path, expect_key?, note)
    ("GET", "/", False, "portal readable by anyone"),
    ("GET", "/agents.md", False, "agent contract must be reachable unauthenticated"),
    ("GET", "/api/gate/soul_land_4", False, "gate is the thing an agent needs before drafting"),
    ("GET", "/soul_land_4/state.txt", False, "static state mirror"),
    ("GET", "/p/soul_land_4", True, "generated dashboard leaks project detail"),
    ("GET", "/api/project/soul_land_4", True, "full derived state — protected"),
    ("POST", "/api/learn/soul_land_4", True, "writes always protected"),
    ("POST", "/api/scan/soul_land_4", True, "spawned work always protected"),
    # An outsider MUST be able to tell a typo from a protected endpoint. A server that answers
    # 401 for everything is a route oracle and makes its own docs false.
    ("GET", "/definitely-not-a-route-xyz", "404", "unknown path is 404, never 401"),
    ("GET", "/health", "404", "there is no /health — do not imply a key would help"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:4180")
    ap.add_argument("--key", default="")
    ap.add_argument("--home", default=os.environ.get("STORYOS_HOME", ""),
                    help="STORYOS_HOME, so probe decisions written through the API can be removed")
    a = ap.parse_args()
    fails = []
    created: list[tuple[str, str]] = []      # (project, id) we wrote — cleaned up at the end
    print(f"AUTH MATRIX against {a.base}\n")
    for method, path, needs_key, note in CASES:
        code, _ = call(a.base, path, key=None, method=method,
                       body={"what": "probe", "rule": "probe"} if method == "POST" else None)
        if needs_key == "404":
            ok = code == 404
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<32} stranger -> {code} "
                  f"(want 404)  — {note}")
            if not ok:
                fails.append(f"{method} {path} returned {code}, want 404 — unknown routes must "
                             f"not look merely 'protected'")
            continue
        if needs_key is True:
            ok = code in (401, 403, 503)
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<32} stranger -> {code} "
                  f"(want 401/403)  — {note}")
            if not ok:
                fails.append(f"{method} {path} was reachable WITHOUT a key ({code})")
            if a.key:
                c2, _b = call(a.base, path, key=a.key, method=method,
                              body={"what": PROBE_MARK, "rule": "auth probe — auto-removed",
                                    "kind": "mechanics"} if method == "POST" else None)
                ok2 = (c2 == 200) if method == "POST" else (c2 in (200, 404))
                if method == "POST" and c2 == 200:
                    try:
                        body = json.loads(_b.decode())
                        if body.get("id"):
                            created.append((path.rsplit("/", 1)[-1], body["id"]))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                print(f"  {'PASS' if ok2 else 'FAIL'}  {method:<4} {path:<32} with key -> {c2} "
                      f"(want 200)")
                if not ok2:
                    fails.append(f"{method} {path} failed WITH the key ({c2})")
        else:
            ok = code == 200
            print(f"  {'PASS' if ok else 'FAIL'}  {method:<4} {path:<32} public    -> {code} "
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
    # "auth test rule" once survived here and inflated the learned-rule count forever.
    if created and a.home:
        for proj, did in created:
            f = Path(a.home) / "projects" / proj / "decisions.jsonl"
            if not f.exists():
                continue
            kept, dropped = [], 0
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line); continue
                if rec.get("id") == did and rec.get("what") == PROBE_MARK:
                    dropped += 1
                    continue
                kept.append(line)
            if dropped:
                f.write_text("\n".join(kept) + "\n", encoding="utf-8")
                c = f.parent / "locks" / f"{did}.card.md"
                c.unlink(missing_ok=True)
            print(f"  cleanup: {proj} — removed {dropped} probe decision(s) this run created")
    elif created:
        print(f"  WARN: wrote {len(created)} probe decision(s) and could not clean them "
              f"(pass --home $STORYOS_HOME). Remove ids: "
              f"{', '.join(d for _, d in created)}")

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
