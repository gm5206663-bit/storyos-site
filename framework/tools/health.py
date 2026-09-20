#!/usr/bin/env python3
"""
health.py — measure the public path, publish the result, and stop claiming what we have not seen.

Writes $STORYOS_HOME/health.json and re-publishes the pointer paste with the measured numbers,
so an agent reading the pointer sees the TRUTH ABOUT THE LAST FEW MINUTES rather than a promise.

  python3 tools/health.py --url <tunnel> [--n 40] [--sleep 4] [--publish]
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
PROBE = "/agents.md"          # exists on the tunnel and in the mirror; no auth needed


def one(url: str, timeout: int = 20) -> tuple[int, str]:
    """Return (status, kind). kind: ok | edge | transport. Distinguishing 530 from a refused
    connection matters: 530 means the edge answered and no connector is attached (our outage),
    000 means nothing answered at all."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        return e.code, ("edge" if e.code in (530, 1033, 502, 503, 504) else "edge")
    except Exception:                                     # noqa: BLE001
        return 0, "transport"


def log_signal(path: str = "/tmp/storyos_cf.log") -> dict:
    """Read the connector's own log: this is the only way to tell 'connector died' apart from
    'the edge is refusing our client', which a black-box probe cannot do."""
    out = {"lost": 0, "registered": 0, "last_event": None, "log": path}
    p = Path(path)
    if not p.exists():
        out["last_event"] = "no connector log"
        return out
    lines = p.read_text(errors="replace").splitlines()
    for l in lines:
        if "Lost connection with the edge" in l:
            out["lost"] += 1
        if "Registered tunnel connection" in l:
            out["registered"] += 1
    for l in reversed(lines):
        if "Lost connection" in l or "Registered tunnel" in l:
            out["last_event"] = l[:160]
            break
    return out


def publish_pointer(payload: str, previous: str | None) -> str | None:
    """Re-upload the pointer, keeping the SAME id if the host allows it. It does not, so the
    id changes on every publish — which is exactly why health.json is the stable local record
    and the pointer is rewritten by the watchdog, not by hand."""
    try:
        req = urllib.request.Request("https://paste.rs/", data=payload.encode(),
                                     headers={"content-type": "text/plain; charset=utf-8"})
        url = urllib.request.urlopen(req, timeout=60).read().decode().strip()
        back = urllib.request.urlopen(url, timeout=60).read().decode()
        if hashlib.sha256(back.encode()).hexdigest()[:16] == hashlib.sha256(payload.encode()).hexdigest()[:16]:
            return url
    except Exception:                                     # noqa: BLE001
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()

    url = a.url or ""
    uf = HOME / ".tunnel_url"
    # The runtime pointer is what a tunnel-start step writes, so it is fresher than the cached
    # file. Preferring it (and adopting it) stops the probe from testing a dead previous tunnel
    # and publishing a false "DOWN" verdict.
    RUNTIME_URL_POINTER = Path("/home/user/storyos-runtime/state/url")
    cands = [c for c in (RUNTIME_URL_POINTER, uf) if c.exists()]
    if not url:
        for c in cands:
            t = c.read_text().strip()
            if t.startswith("https://"):
                url = t
                break
    if url and (not uf.exists() or uf.read_text().strip() != url):
        try:
            uf.write_text(url + "\n", encoding="utf-8")
            print(f"  adopted fresher tunnel url into {uf.name}: {url}")
        except OSError:
            pass
    site = Path(os.environ.get("STORYOS_SITE_DIR", str(HOME.parent / "storyos-site")))
    mirror = (HOME / ".mirror_url").read_text().strip() if (HOME / ".mirror_url").exists() else ""

    origin = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:4180" + PROBE, timeout=8) as r:
            origin = r.status
    except Exception:                                     # noqa: BLE001
        origin = 0

    res = []
    if url:
        for i in range(a.n):
            code, kind = one(url + PROBE)
            res.append({"t": dt.datetime.now().isoformat(timespec="seconds"), "code": code,
                        "kind": kind})
            if i < a.n - 1:
                time.sleep(a.sleep)
    oks = sum(1 for r in res if r["code"] == 200)
    edge_bad = sum(1 for r in res if r["kind"] == "edge")
    transport_bad = sum(1 for r in res if r["kind"] == "transport")
    avail = round(100 * oks / len(res), 1) if res else None

    # longest consecutive outage streak, in seconds — "95% availability" hides whether the
    # gaps are 1s blips or 5-minute holes, and agents care about the holes
    streak = worst = 0
    for r in res:
        if r["code"] != 200:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    worst_s = round(worst * (a.sleep + 0.4)) if worst else 0

    conn = log_signal()
    rep = {"checked_at": dt.datetime.now().isoformat(timespec="seconds"),
           "tunnel_url": url or None, "probes": len(res), "served_200": oks,
           "availability_pct": avail, "edge_failures_530": edge_bad,
           "transport_failures": transport_bad, "longest_outage_s": worst_s,
           "origin_local": origin, "connector": conn, "mirror_url": mirror or None}
    (HOME / "health.json").write_text(json.dumps(rep, indent=2) + "\n")

    verdict = ("TUNNEL DOWN FOR PROBES" if oks == 0 and res else
               "DEGRADED" if (avail or 0) < 99 else "HEALTHY")
    print(f"HEALTH: {verdict}")
    if res:
        print(f"  public path : {oks}/{len(res)} served 200 = {avail}%   "
              f"(530={edge_bad}, refused={transport_bad})")
        print(f"  worst gap   : {worst_s}s continuous without a 200")
    print(f"  origin       : local :4180 -> {origin}")
    print(f"  connector log: {conn['registered']} registrations, {conn['lost']} lost-connection events")
    if conn.get("last_event"):
        print(f"  last edge evt: {conn['last_event']}")

    if a.publish:
        body = (f"StoryOS pointer — measured, not promised\n"
                f"updated: {rep['checked_at']}\n\n"
                f"AUTHORITY (read this first, it is byte-verifiable and needs no key):\n"
                f"  {mirror or '(no mirror published yet — ask the human to run publish_stage)'}\n\n"
                f"LIVE TUNNEL (optional fresh read, currently: {verdict.lower()}):\n"
                f"  {url or '(none)'}\n\n"
                f"last measurement window: {oks}/{len(res)} requests served 200 = {avail}%"
                f"  ({edge_bad} x HTTP 530)\n"
                f"longest continuous outage in window: {worst_s}s\n"
                f"connector: {conn['registered']} registrations / {conn['lost']} lost-edge events\n\n"
                f"Read {url + '/agents.md' if url else 'the mirror'} for the route table. There is no\n"
                f"/health, /api, /api/state or /state — a 404 there is a wrong route, not an outage.\n"
                f"A 530/1033 means the connector is detached; the origin may still be healthy.\n")
        u = publish_pointer(body, None)
        if u:
            (HOME / ".pointer_url").write_text(u + "\n")
            print(f"  pointer     : {u} (readback verified)")
            # <tunnel>/pointer.md is what agents fetch, and it used to be written only by the
            # watchdog, so a manual publish left it naming a mirror that no longer existed while
            # THIS run had just minted a new one. One pointer, one format, written by every
            # publisher — otherwise "mutable fixed path" quietly becomes a stale cache.
            try:
                (site / "pointer.md").write_text(body, encoding="utf-8")
                print(f"  stage copy  : refreshed to name {mirror or '(no mirror)'}")
            except OSError as e:
                print(f"  stage copy  : NOT refreshed ({e}) — agents may read a stale id")
        else:
            print("  pointer     : publish FAILED (leaving previous pointer untouched)")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
