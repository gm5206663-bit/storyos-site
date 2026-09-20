#!/usr/bin/env python3
"""Prove the LAWS.md provenance guard in verify_stage.py both ways.

Every prior attempt at this test silently no-op'd: the corruptor's regex did not match the
real footer text, so verify_stage legitimately reported PASS on an UNCORRUPTED file, and I
nearly read that as "the guard works". A checker whose failure case was never made to fail is
not a checker. So this script asserts the corruption landed BEFORE it runs the verifier.
"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]   # works from any clone
SITE = next((q for q in [REPO / "storyos-site", pathlib.Path("/home/user/storyos-site")] if q.exists()), None)
VERIFY = REPO / "storyos/scripts/verify_stage.py"
HOME_ENV = {"STORYOS_HOME": str(REPO / "storyos-home")}


def verify(target, env=None):
    """Run the stage verifier with an explicit env. Case C deliberately hides $STORYOS_HOME:
    the guard accepts ANY candidate source, so a good copy elsewhere would excuse a stale one
    and the test would prove nothing about the case actually under test."""
    e = dict(__import__("os").environ)
    e.pop("STORYOS_HOME", None)
    e.update(env or {})
    return subprocess.run([sys.executable, str(VERIFY), str(target)],
                          capture_output=True, text=True, env=e)
FOOTER = re.compile(r"source file sha256: `([0-9a-f]{8,64})")

failures = []
if SITE is None:
    print("LAWSGUARD: SKIP (no staged site to inspect; run after publish_stage)")
    sys.exit(0)

# case A: a clean copy must PASS (guard does not misfire)
a = pathlib.Path(tempfile.mkdtemp(prefix="lawsguard_A_")) / "site"
shutil.rmtree(a.parent, ignore_errors=True)
shutil.copytree(SITE, a)
ra = verify(a, HOME_ENV)
if ra.returncode != 0:
    failures.append(f"A: clean copy did not PASS:\n{ra.stdout[-600:]}")
print(f"A clean copy                  -> rc={ra.returncode}  {ra.stdout.splitlines()[0] if ra.stdout else ''}")

# case B: rewrite the recorded prefix with a wrong one, assert it landed, expect FAIL
b = pathlib.Path(tempfile.mkdtemp(prefix="lawsguard_B_")) / "site"
shutil.rmtree(b.parent, ignore_errors=True)
shutil.copytree(SITE, b)
doc = b / "LAWS.md"
text = doc.read_text(encoding="utf-8")
m = FOOTER.search(text)
assert m, f"VOID TEST: footer not matched by {FOOTER.pattern!r}; actual line: " \
          f"{[l for l in text.splitlines() if 'sha256' in l]}"
orig = m.group(1)
wrong = "f" * len(orig)
doc.write_text(text.replace(orig, wrong), encoding="utf-8")
after = FOOTER.search(doc.read_text(encoding="utf-8"))
assert after and after.group(1) == wrong, "VOID TEST: corruption did not land on disk"
assert orig != wrong, "VOID TEST: the recorded prefix is already all-fs"
print(f"B footer rewritten            -> {orig[:16]}… became {wrong[:16]}…")
rb = verify(b, HOME_ENV)
hit = "drifted from their source" in rb.stdout
print(f"B corrupted provenance        -> rc={rb.returncode}  guard fired={hit}")
if rb.returncode == 0 or not hit:
    failures.append(f"B: guard did not fire. stdout:\n{rb.stdout[-800:]}")
print(f"  message: {[l for l in rb.stdout.splitlines() if 'drifted' in l][:1]}")

# case C: a genuinely stale doc (source file changed, doc not regenerated) must also FAIL
c = pathlib.Path(tempfile.mkdtemp(prefix="lawsguard_C_")) / "site"
shutil.rmtree(c, ignore_errors=True)          # only the site copy: laws/ is a sibling
LAW_SRC = REPO / "storyos-home/laws/UNIVERSAL_LAWS.json"
assert LAW_SRC.exists(), "VOID TEST: no law source to seed the fixture"
(c.parent / "laws").mkdir(parents=True, exist_ok=True)
shutil.copy2(LAW_SRC, c.parent / "laws" / "UNIVERSAL_LAWS.json")   # the fixture file itself
shutil.copytree(SITE, c)
src = c.parent / "laws" / "UNIVERSAL_LAWS.json"
assert src.exists(), "VOID TEST: no sibling law source to make stale"
data = __import__("json").loads(src.read_text())
data["_injected"] = "a law was added without regenerating the doc"
src.write_text(__import__("json").dumps(data, indent=2), encoding="utf-8")
rc_ = verify(c)          # no STORYOS_HOME: only the stale sibling source is visible
hit_c = "drifted from their source" in rc_.stdout
print(f"C stale doc vs changed source -> rc={rc_.returncode}  guard fired={hit_c}")
if not hit_c:
    failures.append(f"C: sibling-source drift not detected.\n{rc_.stdout[-800:]}")

for d in (a, b, c):
    shutil.rmtree(d.parent, ignore_errors=True)

print()
if failures:
    print("LAWSGUARD: FAIL")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("LAWSGUARD: PASS (clean passes, forged prefix fails, stale sibling fails)")
