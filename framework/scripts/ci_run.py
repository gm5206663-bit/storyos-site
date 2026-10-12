#!/usr/bin/env python3
"""ci_run.py — run verify_stage.py in CI, with the dragon_prince set PINNED.

Why a pin exists at all: published-site/dragon_prince_yuan is a stale build —
three generated files drifted from the manifest and its state.txt is missing
the RULES OF ENGAGEMENT section (audit: AUDIT_2026-10-11_STALE_STAGE_AND_SCOPE.md,
which is also the account of WHY it cannot be rebuilt from in here: the source
project named in framework/storyos-home/registry.json is not in any repository
of this account, and which of the two disagreeing records is authoritative is
the author's ruling). Until that ruling, CI pins exactly the four documented
failures and fails if ANY issue appears beyond them. When the stage is rebuilt
or the ruling lands, empty PENDING — CI then demands a clean stage.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # …/storyos-site
STAGE = ROOT / 'published-site'

PENDING = {
    'dragon_prince_yuan/index.html: size drift (6210 != 5375) — stale build',
    'dragon_prince_yuan/state.json: size drift (5939 != 4795) — stale build',
    'dragon_prince_yuan/state.txt: size drift (1891 != 2392) — stale build',
    "dragon_prince_yuan/state.txt: missing 'RULES OF ENGAGEMENT'",
}


def main():
    r = subprocess.run([sys.executable, 'framework/scripts/verify_stage.py', str(STAGE)],
                       cwd=ROOT, capture_output=True, text=True)
    print(r.stdout, end='')
    if r.stderr:
        print(r.stderr, end='')
    bad = []
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.startswith('[FAIL] '):
            issue = s[len('[FAIL] '):].strip()
            if issue not in PENDING:
                bad.append(issue)
    if bad:
        print('\nCI: NEW stage issue(s) beyond the pinned set:')
        for b in bad:
            print('   ', b)
        return 1
    print(f"\nCI: nothing failed outside the pinned set "
          f"({len(PENDING)} documented dragon_prince_yuan issue(s) awaiting the author's ruling).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
