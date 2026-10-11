# AUDIT — the published site carries a stale stage, and its state file reports PASS anyway

**Date:** 2026-10-11 · **Class:** two-copies rot + checkers-that-lie · **Severity:** high
**Method:** clean clone · every number measured against the live site

---

## THE FINDING

`dragon_prince_yuan` — a stage published on the live StoryOS site — is a **stale build**.
Three of its seven manifest-tracked files have drifted from the manifest, and one is missing a
required section.

**The published `state.txt` reports `GATE: PASS` while being part of a build that fails
verification.**

---

## THE EVIDENCE

The gate, run correctly — `python3 framework/scripts/verify_stage.py published-site`:

```
VERIFY_STAGE: FAIL (121 files checked, 4 issues)
  [FAIL] dragon_prince_yuan/index.html: size drift (6210 != 5375) — stale build
  [FAIL] dragon_prince_yuan/state.json: size drift (5939 != 4795) — stale build
  [FAIL] dragon_prince_yuan/state.txt: size drift (1891 != 2392) — stale build
  [FAIL] dragon_prince_yuan/state.txt: missing 'RULES OF ENGAGEMENT'
```

**Exit code: 1.** The gate is working correctly.

### Manifest vs published

| File | Manifest expects | Published on disk | Verdict |
|---|---|---|---|
| `chapters/Chapter_01.md` | 23,640 | 23,640 | ok |
| `chapters/README.txt` | 245 | 245 | ok |
| `decisions.md` | 308 | 308 | ok |
| **`index.html`** | 5,375 | **6,210** | 🔴 drifted **+835** |
| `rules.md` | 309 | 309 | ok |
| **`state.json`** | 4,795 | **5,939** | 🔴 drifted **+1,144** |
| **`state.txt`** | 2,392 | **1,891** | 🔴 drifted **−501** |

**The four hand-written files are intact. The three generated files have drifted.**

That pattern identifies the cause: the stage was **regenerated after the manifest was
written**, and the manifest was never regenerated to match. A derived document out of sync
with its source — the house's Two-Copies Law, rule 4: *when two copies disagree, the receipt
wins* — except here nobody has re-established which is the receipt.

### The drifted build is what is LIVE

Measured by fetching the deployed site:

| URL | Live bytes | Matches |
|---|---|---|
| `.../dragon_prince_yuan/index.html` | **6,210** | the **drifted** file |
| `.../dragon_prince_yuan/state.json` | **5,939** | the **drifted** file |
| `.../dragon_prince_yuan/state.txt` | **1,891** | the **drifted** file |

**The stale build is publicly served.** Nothing was caught before publication.

### The state file contradicts itself

`published-site/dragon_prince_yuan/state.txt` contains:

```
GATE: PASS  (errors=0, warnings=0, learned-rules-active=0)
```

and contains the keys `live edge` and `next source chapter` —

**but it does not contain `RULES OF ENGAGEMENT`,** which `verify_stage.py` requires of every
`state.txt` because *"an agent could not tell if drafting is allowed"* without it.

So the file that exists to tell a receiving agent whether drafting is permitted **claims PASS
while omitting the section that carries that answer.**

---

## WHY THE GATE DID NOT STOP IT

The gate **did** stop it — `framework/tools/watchdog.sh` calls `verify_stage.py` and refuses to
publish on failure:

```
REFUSING to publish: stage failed verify_stage (see $STATE/build.log)
```

So the deployed drift did not come through the watchdog, or the watchdog's check was added
after this build shipped, or the publish path bypassed it. **The gate is not the defect here.
Something published around it.**

**This is worth knowing precisely, and it is not determinable from the repository alone.** The
deployed artifact and the gate disagree, and the gate is the one that is right.

---

## THE SECOND, QUIETER DEFECT — the invocation

`verify_stage.py` takes the site root as an argument and **defaults to `<cwd>/storyos-site`.**

Run three ways from the repository root:

| Invocation | Files checked | Issues |
|---|---|---|
| *(no argument)* | **0** | 1 |
| `.` | 381 | 106 |
| `published-site` ← correct | 121 | 4 |

- **No argument:** silently resolves to a directory that does not exist, checks **zero files**,
  and reports `FAIL ... 0 files checked`. It fails for the *wrong reason* — it did not verify
  anything, it merely could not find `agents.md` in a directory that was never there.
- **`.`:** over-broad. It sweeps 381 files including the framework source and reports 106
  issues, most of which are the manifest being resolved against the wrong root.
- **`published-site`:** correct — 121 files, 4 real issues.

The correct invocation **is** used — `watchdog.sh` and `go_live.sh` both pass `"$SITE"`. **But
it is not documented for a human.** A person running the gate by hand gets either a false FAIL
or a 106-issue flood, and will reasonably conclude the gate is broken.

**Two of three invocations produce a misleading result, and only the third is correct.**

---

## WHAT WAS NOT DONE

- **Nothing was published, unpublished, or regenerated.** The stale stage is live; taking a
  stage down is the author's call, and so is deciding which of the two disagreeing records is
  authoritative.
- **No manifest was rewritten.** Regenerating it would *bless* the drift by making the drifted
  files canonical. That decision requires knowing which copy is intended.
- **No script was edited.** Same rule as every other finding in this pass — a checker edit
  without a fixture to validate it is worse than a documented gap.

---

## THE RULINGS THIS NEEDS

**1. Which is authoritative for `dragon_prince_yuan` — the manifest or the published files?**
   - If the **published files** are current → regenerate `api/manifest.json`. The stage is fine
     and only the manifest was stale.
   - If the **manifest** is current → the stage was built from something else and **the live
     stage is wrong**. It should be rebuilt or pulled.

**2. `state.txt` is missing `RULES OF ENGAGEMENT`.** Was the section removed deliberately, or
   did the generator stop emitting it? If the generator dropped it, **every stage rebuilt since
   that change has the same hole** — worth checking the other stages.

**3. How did a build that fails the gate reach the live site?** The watchdog refuses to publish
   it. This is the most useful question of the three, because the answer tells you whether the
   gate is actually inline.

**4. Should `verify_stage.py` require its root argument explicitly?** Removing the default
   would turn two misleading invocations into one clear usage error. Recommended.

---

## RECEIPTS

- `framework/scripts/verify_stage.py` — lines 40 (`agents.md`), 48–70 (manifest/size checks),
  final line (`sys.exit(1 if fail else 0)`)
- `framework/tools/watchdog.sh` lines 84–85 (the refuse-to-publish guard)
- `framework/tools/go_live.sh` line 16
- `published-site/api/manifest.json` — the `dragon_prince_yuan` entry
- Live measurements — fetched 2026-10-11 from `https://gm5206663-bit.github.io/storyos-site/`

---

*Written 2026-10-11. Add-only: no file published, regenerated, or edited.*

---

## UPDATE — later the same day, after the whole-account sweep

Two more things were found, and both are repaired in this commit.

**1. The scope defect in `verify_stage.py` was worse than recorded above.**
The default stage path was `Path.cwd()/"storyos-site"`, which resolves only
when the script is run from the parent of the repository. Run from anywhere
else, `rglob()` over a missing directory yields nothing: **0 files checked**,
and the run reported `FAIL` only because `agents.md` happened to be absent. Had
`agents.md` existed, it would have printed **`PASS (0 files checked)`**.

Repaired: the stage resolves against the repository the script lives in, a
missing stage is refused by name, **0 files checked is a hard failure**, and
every run prints:
`COVERAGE: published-site — 121 files checked · 2 stage(s) with state.txt`.

**2. Why the drift could never be caught or fixed from here.**
`publish_stage.py` builds each stage from the project named in
`framework/storyos-home/registry.json`:

| project | registry path | exists? |
|---|---|---|
| `soul_land_4` | `/home/user/projects/soul_land_4` | **no** |
| `dragon_prince_yuan` | `/home/user/projects/dragon_prince_yuan` | **no** |

Neither source is in any repository of this account. Run against those
registry entries, `publish_stage.py` **built a stage with 0 of the 52 chapters
and reported `stage built: 57 files`** — success, covering nothing.

Repaired: a missing source now stops the build by name —
`SCOPE FAIL — the source for 'soul_land_4' is not here … Nothing was built. A
stage cannot be traced to a source that is absent.`

**Still open, and it is the author's call:** the published
`dragon_prince_yuan` stage remains 5,375 bytes out of date with its own
manifest and still claims `GATE: PASS` while missing `RULES OF ENGAGEMENT`.
It cannot be rebuilt from inside this account. `verify_stage.py` now reports
the four real failures instead of hiding them behind a zero.
