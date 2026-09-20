#!/usr/bin/env python3
"""
server.py — StoryOS online control centre for every registered project.

  python3 tools/server.py --port 4180

Routes
  GET /                      index of all projects + gate status
  GET /p/<name>              that project's control centre (self-contained HTML)
  GET /api/projects          JSON: every project, gate + growth
  GET /api/project/<name>    JSON: full derived state for one project
  GET /api/gate/<name>       JSON: live validator run (re-runs on demand)
  POST /api/scan/<name>      re-derive state from the project's files
  POST /api/learn/<name>     record a decision (body: {"what","rule","tokens","patterns"})

Design: read-mostly. The only writes are into $STORYOS_HOME — never into a project.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path(os.environ.get("STORYOS_HOME", str(Path.home() / "storyos-home")))
TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
VALIDATOR = TOOLS / "storyos_validate.py"
PY = sys.executable

# ---------------------------------------------------------------- public exposure policy
# Reached through a tunnel, this server is on the open internet. Default-deny, two tiers:
#   PUBLIC    - state an agent must read to work correctly (mirrored in the static stage)
#   PROTECTED - every other route, incl. all writes; needs header  X-StoryOS-Key: <STORYOS_KEY>
# With STORYOS_KEY unset, PROTECTED routes answer 503 instead of running unattended.
PUBLIC_EXACT = frozenset(("/", "/index.html", "/agents.md", "/START-HERE.md", "/report.md",
                          "/pointer.md", "/api/projects", "/api/README.json"))
PUBLIC_PREFIX = ("/api/gate/",)


def _stage_is_public(path: str) -> bool:
    """Anything present in the built static stage is public BY CONSTRUCTION — the stage is
    generated from publish_stage.py, which never copies chapter prose into it (verify_stage.py
    fails the build if it does). An allowlist of names went stale the moment I added /pointer.md
    and started refusing the very files meant to be read."""
    d = os.environ.get("STORYOS_SITE_DIR")
    if not d:
        return False
    f = Path(d) / path.lstrip("/")
    return f.is_file()


# Routes this server genuinely implements that are NOT public files. Existence and
# authorisation are derived from ONE list, so "unknown path" can be answered honestly.
PROTECTED_PREFIX = ("/api/project/", "/api/scan/", "/api/learn/", "/p/")


def root_of(path: str) -> str:
    return (path.split("?", 1)[0].split("#", 1)[0]) or "/"


def is_public(path: str) -> bool:
    """Default-deny. NOTE: "/" must be matched EXACTLY — as a prefix it matches every path
    and silently makes the whole server public (this happened; test_auth.py catches it)."""
    root = root_of(path)
    if root in PUBLIC_EXACT:
        return True
    if _stage_is_public(root):
        return True
    if any(root.startswith(x) for x in PUBLIC_PREFIX):
        return True
    # static stage mirrors are already public files; only these extensions may be read openly
    if re.match(r"^/[A-Za-z0-9_-]+/(state\.txt|rules\.md|decisions\.md|report\.md)$", root):
        return True
    if root == "/api/manifest.json":
        return True
    return False


def route_exists(path: str) -> bool:
    """True for public files and for the handful of dynamic routes do_GET/do_POST implement.

    Without this the server answered 401 for EVERY unmatched path, which (a) turned a typo into
    'protected endpoint', (b) handed strangers a free oracle for discovering real routes, and
    (c) made /agents.md document a 404 the server could not produce. 404 for junk, 401 only
    where a key would actually help."""
    root = path if isinstance(path, str) else root_of(path)
    if is_public(root):
        return True
    return any(root.startswith(x) for x in PROTECTED_PREFIX)


def key_ok(hdrs) -> bool:
    import hmac
    want = os.environ.get("STORYOS_KEY", "")
    if not want:
        return False
    got = hdrs.get("X-StoryOS-Key") or ""
    if not got:
        import base64
        ah = hdrs.get("Authorization", "")
        if ah.lower().startswith("basic "):
            try:
                got = base64.b64decode(ah[7:]).decode().split(":", 1)[0]
            except Exception:
                got = ""
    return bool(got) and hmac.compare_digest(got, want)




def registry() -> dict:
    f = HOME / "registry.json"
    return json.loads(f.read_text()) if f.exists() else {"projects": {}}


def store(name: str) -> Path:
    return HOME / "projects" / name


def decisions(name: str) -> list[dict]:
    f = store(name) / "decisions.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def run_gate(project: Path) -> dict:
    try:
        r = subprocess.run([PY, str(VALIDATOR), "--project", str(project), "--phase", "full",
                            "--json"], capture_output=True, text=True, timeout=240)
        line = [l for l in r.stdout.splitlines() if l.startswith("{")]
        return json.loads(line[-1]) if line else {"result": "UNKNOWN",
                                                   "findings": [r.stdout[-400:] or r.stderr[-400:]]}
    except Exception as e:                                     # noqa: BLE001 - never 500 the dashboard
        return {"result": "ERROR", "findings": [f"{type(e).__name__}: {e}"]}


def project_summary(name: str, entry: dict) -> dict:
    p = Path(entry["path"])
    st = store(name) / "state" / "STORYOS_STATE.json"
    state = json.loads(st.read_text()) if st.exists() else {}
    ds = decisions(name)
    live = [d for d in ds if d.get("status", "active") == "active"]
    return {"name": name, "label": entry.get("label", name), "path": (str(p) if os.environ.get("STORYOS_SHOW_PATHS") == "1"
                     else "(redacted at public edge; STORYOS_SHOW_PATHS=1 to show)"),
            "exists": p.exists(),
            "edge": state.get("edge", {}), "metrics": state.get("metrics", {}),
            "growth": {"decisions": len(ds), "active": len(live),
                       "enforceable": sum(len(d.get("enforce_regexes") or [])
                                          + len(d.get("tokens") or []) for d in live),
                       "locks": len(list((store(name) / "locks").glob("*.card.md"))),
                       "last": live[-1]["date"] if live else None},
            "gate": run_gate(p) if p.exists() else {"result": "MISSING"}}


PAGE = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#0b0d11;--p:#11151c;--l:#1e2530;--ink:#e6edf6;--dim:#8b98ab;--ok:#3ddc97;--no:#ff5c6c;--wn:#ffb454;--in:#5aa9ff;--m:ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:26px 20px 70px}
h1{font-size:21px;margin:0 0 3px}h2{font-size:15px;margin:26px 0 10px}
.sub{color:var(--dim);font-family:var(--m);font-size:12.5px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(215px,1fr))}
.card{background:var(--p);border:1px solid var(--l);border-radius:12px;padding:14px}
.k{font-family:var(--m);font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;color:#5d6b7e}
.v{font-size:25px;font-weight:650;font-family:var(--m);margin-top:4px}
a{color:var(--in);text-decoration:none}a:hover{text-decoration:underline}
.pill{display:inline-block;font-family:var(--m);font-size:10.5px;padding:3px 9px;border-radius:20px;border:1px solid}
.pass{color:var(--ok);border-color:#1d4a38;background:#0e1a15}.fail{color:var(--no);border-color:#4a2028;background:#180d10}
.warn{color:var(--wn);border-color:#4a3a18;background:#17120a}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px;border:1px solid var(--l);
border-radius:12px;background:var(--p);margin-bottom:10px;flex-wrap:wrap}
form{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
input,textarea{background:#0d1218;border:1px solid #28323f;border-radius:8px;color:var(--ink);padding:8px;
font:inherit;font-size:13.5px;flex:1;min-width:160px}textarea{min-height:56px;flex-basis:100%}
button{background:#1a2530;border:1px solid #2c3a4c;color:var(--ink);border-radius:8px;padding:8px 13px;
font:inherit;font-size:13px;cursor:pointer}button:hover{background:#22303e}
pre{font-family:var(--m);font-size:11.5px;color:var(--dim);white-space:pre-wrap;word-break:break-word;margin:0}
iframe{width:100%;height:78vh;border:1px solid var(--l);border-radius:12px;background:#fff}
.note{border-left:3px solid var(--in);padding:9px 13px;background:#0d1620;border-radius:0 10px 10px 0;
font-size:13.5px;color:#cfe3ff;margin:14px 0}
</style></head><body><div class=wrap>__BODY__</div>
<script>
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},
body:JSON.stringify(body||{})});return r.json()}
document.querySelectorAll('[data-scan]').forEach(b=>b.onclick=async()=>{
 b.textContent='scanning…';const j=await post('/api/scan/'+b.dataset.scan,{});
 b.textContent='done — reload';if(j.ok)setTimeout(()=>location.reload(),700)});
document.querySelectorAll('form[data-learn]').forEach(f=>f.onsubmit=async e=>{
 e.preventDefault();const fd=new FormData(f);
 const j=await post('/api/learn/'+f.dataset.learn,{what:fd.get('what'),rule:fd.get('rule'),
   kind:fd.get('kind'),tokens:(fd.get('tokens')||'').split(',').map(s=>s.trim()).filter(Boolean),
   patterns:(fd.get('patterns')||'').split(/\\n/).map(s=>s.trim()).filter(Boolean)});
 f.outerHTML = j.ok ? `<p class="pass" style="padding:10px">✓ ${j.id} recorded and enforced. The gate now fails on it.</p>`
                    : `<p class="fail" style="padding:10px">${j.error||'failed'}</p>`});
</script></body></html>"""


def esc(t) -> str:
    return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_index(rows: list[dict]) -> str:
    cards = []
    for r in rows:
        g, gate = r["growth"], r["gate"]
        cls = {"PASS": "pass", "FAIL": "fail"}.get(gate.get("result"), "warn")
        e = r["edge"] or {}
        cards.append(f"""<div class=row><div style="min-width:260px">
        <b><a href="/p/{esc(r['name'])}">{esc(r['label'])}</a></b>
        <div class=sub>after Chapter{esc(e.get('fic_chapter','?'))} “{esc(e.get('fic_title',''))}”</div></div>
        <div><span class="pill {cls}">gate {esc(gate.get('result'))}</span>
        <span class="pill warn">{gate.get('errors',0)} err / {gate.get('warnings',0)} warn</span></div>
        <div class=sub>{g['decisions']} decisions · {g['enforceable']} enforced · {g['locks']} locks</div>
        <div style="display:flex;gap:8px"><button data-scan="{esc(r['name'])}">rescan</button>
        <a class=card href="/api/gate/{esc(r['name'])}" style="padding:6px 10px;font-size:12px">gate json</a></div>
        </div>""")
    parts = []
    for r in rows:
        nm = esc(r["name"])
        parts.append(
            f'<h2>Learn so far — {nm}</h2>'
            f'<form data-learn="{nm}">'
            '<input name=what placeholder="what went wrong, or what you decided">'
            '<input name=rule placeholder="the rule now in force">'
            '<select name=kind style="flex:0"><option>rejection</option><option>correction</option>'
            '<option>preference</option><option>mechanics</option></select>'
            '<input name=tokens placeholder="tokens that must never appear, comma separated">'
            '<textarea name=patterns placeholder="one regex per line — the gate will fail any prose matching this">'
            '</textarea><button>record permanently</button></form>')
    learned = "".join(parts)
    body = f"""<h1>StoryOS — Control Centre</h1>
    <div class=sub>{len(rows)} project(s) · home <code>{esc(HOME)}</code> · {dt.datetime.now():%Y-%m-%d %H:%M}</div>
    <div class=note>Every rule you record here becomes <b>enforcement</b>: the gate fails any future
    draft that breaks it. Nothing is ever deleted — the decision log is append-only, so the system
    only accumulates. That is how it gets better the more you use it.</div>
    {''.join(cards) or '<p class=sub>no projects registered — <code>storyos use &lt;path&gt; --name &lt;name&gt;</code></p>'}
    {learned}"""
    return PAGE.replace("__TITLE__", "StoryOS — Projects").replace("__BODY__", body)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):                       # quiet
        pass

    def _send(self, code: int, body: str, ctype="text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200) -> None:
        self._send(code, json.dumps(obj, indent=2, ensure_ascii=False), "application/json")

    def _stage(self):
        """The static stage (publish_stage.py output) wins when built: it is the artifact that
        gets deployed, so serving it here makes preview and production the same bytes."""
        d = os.environ.get("STORYOS_SITE_DIR", str(REPO.parent / "storyos-site"))
        root = Path(d)
        if not root.is_dir():
            return None
        rel = (urlparse(self.path).path or "").lstrip("/") or "index.html"
        f = (root / rel).resolve()
        try:
            f.relative_to(root.resolve())
        except ValueError:
            return None                                   # refuse traversal, always
        return f if f.is_file() else None

    def do_GET(self):                                    # noqa: N802
        u0 = urlparse(self.path)
        if not route_exists(root_of(u0.path)):
            return self._json({"ok": False, "error": "404 no such route",
                               "hint": "GET /agents.md for the route table"}, 404)
        if not is_public(u0.path) and not key_ok(self.headers):
            return self._denied(u0.path)
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        reg = registry()["projects"]
        st = self._stage()
        if st is not None:
            ctype = ("text/html; charset=utf-8" if st.suffix == ".html" else
                     "application/json" if st.suffix == ".json" else
                     "text/plain; charset=utf-8")
            return self._send(200, st.read_text(encoding="utf-8"), ctype)
        if u.path in ("/", "/index.html"):
            rows = [project_summary(n, e) for n, e in reg.items()]
            return self._send(200, render_index(rows))
        if parts[:2] == ["api", "projects"]:
            return self._json({n: project_summary(n, e) for n, e in reg.items()})
        if parts[:2] == ["api", "project"] and len(parts) == 3 and parts[2] in reg:
            st = store(parts[2]) / "state" / "STORYOS_STATE.json"
            if st.exists():
                return self._send(200, st.read_text(encoding="utf-8"), "application/json")
            return self._json({"error": "no derived state — rescan"}, 404)
        if parts[:2] == ["api", "gate"] and len(parts) == 3 and parts[2] in reg:
            return self._json(run_gate(Path(reg[parts[2]]["path"])))
        if parts[:2] == ["p", ""] or (len(parts) == 2 and parts[0] == "p"):
            name = parts[1]
            if name in reg:
                site = store(name) / "state" / "site" / "index.html"
                if site.exists():
                    return self._send(200, site.read_text(encoding="utf-8"))
                return self._send(200, PAGE.replace("__TITLE__", name).replace(
                    "__BODY__", f"<h1>{esc(name)}</h1><p class=sub>No control centre yet.</p>"
                    f"<button data-scan={esc(name)}>build it now</button>"))
        return self._send(404, "not found", "text/plain")

    def _denied(self, path: str) -> None:
        # Denials are the interesting signal: who probed a protected route, and with what.
        try:
            with (HOME / "write_audit.log").open("a", encoding="utf-8") as ah:
                ah.write(f"{dt.datetime.now().isoformat(timespec='seconds')} DENY "
                         f"{self.command} {path} {self.client_address[0]}\n")
        except OSError:
            pass
        if not os.environ.get("STORYOS_KEY"):
            return self._json({"ok": False, "error": "protected route disabled — start the "
                              "server with STORYOS_KEY set to enable writes"}, 503)
        # Bare 401 for an unauthenticated caller. Naming the header turned every refusal into
        # an instruction to spray a stolen key at an arbitrary path.
        return self._json({"ok": False, "error": "401"}, 401)

    def do_POST(self):                               # noqa: N802
        u1 = urlparse(self.path)
        if not route_exists(root_of(u1.path)):
            return self._json({"ok": False, "error": "404 no such route"}, 404)
        if not key_ok(self.headers):
            return self._denied(u1.path)
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        reg = registry()["projects"]
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode() if n else "{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "invalid JSON"}, 400)
        name = parts[2] if len(parts) == 3 else None
        if name not in reg:
            return self._json({"ok": False, "error": "unknown project"}, 404)
        if parts[1] == "scan":
            st = store(name)
            st.joinpath("state").mkdir(parents=True, exist_ok=True)
            p = Path(reg[name]["path"])
            for cmd in ([PY, str(REPO / "scripts" / "scan_project.py"),
                         str(p / "audits" if (p / "audits").is_dir() else p), str(p),
                         str(st / "state")],
                        [PY, str(REPO / "scripts" / "gen_docs.py"), str(st / "state")],
                        [PY, str(REPO / "scripts" / "build_site.py"), str(p), str(st / "state" / "site")]):
                if not Path(cmd[1]).exists():
                    continue
                subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            try:
                with (HOME / "write_audit.log").open("a", encoding="utf-8") as ah:
                    ah.write(f"{dt.datetime.now().isoformat(timespec='seconds')} SCAN {name} "
                             f"{self.client_address[0]}\n")
            except OSError:
                pass
            return self._json({"ok": True})
        if parts[1] == "learn":
            ts = store(name)
            ts.joinpath("locks").mkdir(parents=True, exist_ok=True)
            did = f"D{len(decisions(name)) + 1:04d}"
            rec = {"id": did, "date": dt.date.today().isoformat(), "project": name,
                   "kind": body.get("kind", "correction"), "status": "active",
                   "what": body.get("what", ""), "rule": body.get("rule", ""),
                   "tokens": list(body.get("tokens") or []),
                   "enforce_regexes": list(body.get("patterns") or []),
                   "scope": "story-prose"}
            if not rec["rule"]:
                return self._json({"ok": False, "error": "rule is required"}, 400)
            for r in rec["enforce_regexes"]:
                try:
                    re.compile(r)
                except re.error as e:
                    return self._json({"ok": False, "error": f"bad regex: {e}"}, 400)
            try:
                audit = HOME / "write_audit.log"
                ts_ms = dt.datetime.now().isoformat(timespec="seconds")
                who = self.headers.get("X-Remote-Note") or "unlabelled"
                with audit.open("a", encoding="utf-8") as ah:
                    ah.write(f"{ts_ms} LEARN {name} {self.client_address[0]} note={who} "
                             f"rule={rec['rule'][:120]!r}\n")
            except OSError:
                pass                       # never fail a legitimate write because of logging
            with (ts / "decisions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            (ts / "locks" / f"{did}.card.md").write_text(
                "\n".join([f"# Lock {did} — {rec['rule'][:70]}", "", "```storyos-meta",
                           json.dumps({"card": "learned-lock", "id": did, "kind": rec["kind"],
                                       "status": "active", "tokens": rec["tokens"],
                                       "enforce_regexes": rec["enforce_regexes"]}, indent=2),
                           "```", "", "**What:** " + rec["what"], "", "**Rule:** " + rec["rule"], ""]),
                encoding="utf-8")
            return self._json({"ok": True, "id": did,
                               "enforceable_added": len(rec["tokens"]) + len(rec["enforce_regexes"])})
        return self._json({"ok": False, "error": "unknown route"}, 404)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4180)
    ap.add_argument("--bind", default="0.0.0.0")
    a = ap.parse_args()
    print(f"StoryOS home: {HOME}")
    print("  writes ENABLED (X-StoryOS-Key required)" if os.environ.get("STORYOS_KEY")
          else "  writes DISABLED — no STORYOS_KEY, public edge is read-only")
    ThreadingHTTPServer((a.bind, a.port), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
