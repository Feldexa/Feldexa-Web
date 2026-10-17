# Website verification evidence — 2026-10-17

Scope: the machine-readable contract, the deterministic checker, and a headed-browser measurement of
the published page. This note records what was run and what was observed on the revision that
contains it (the commit SHA is recorded in the pull-request comment for this change).

Nothing here is a release claim. The site still describes the app as in development, which is correct
while `Feldexa/Feldexa` has no published release.

## 1. Deterministic checker

Command (repository root): `python3 docs/verify/verify_site.py`

Observed: **52 checks: 51 pass, 0 fail, 1 skip**. The skip is `layout.viewport_matrix`, which needs a
browser and is measured separately in §3; it is reported as `SKIP`, never as a pass.

Command: `python3 docs/verify/verify_site.py --base origin/main`

Observed: **54 checks: 53 pass, 0 fail, 1 skip**. `mutation.changed_paths` reports 7 changed paths,
each checked against the contract at `origin/main`; `mutation.contract_delta` reports the single
allowlist entry this change adds (`AGENTS.md`, the policy authority).

The checker validates the `AGENTS.md` contract block (schema, types, version, repository identity,
canonical remote against `origin`, default branch, root and shadowing policy names, release status,
claims policy, tracker and paid-infrastructure flags), the checkout root, the absence of a nested copy
of this repository, and the absence of a second contract authority. It then serves the repository and
checks the served page: doctype, `lang`, title, viewport, description, skip link addressed at the
`main` landmark, one parsed `<main>`, labelled `nav`s, one `h1` first, heading order and tag balance,
anchors with a target and a name, unique ids, internal links and anchors, local resources inside the
checkout, no third-party resource of any kind, no meta refresh, no tracker signatures in HTML/CSS/JS,
a focus style that is neither missing nor removed, a skip link that is not hidden, a responsive rule,
declared-pair contrast, relative font units, and the public claims against `release_status`.

## 2. Negative tests

Command: `python3 docs/verify/verify_site_selftest.py`

Observed: **58 cases (53 violations, 1 clean baseline, 4 accepted controls): 58 pass, 0 fail**.

Each violation case copies the repository, applies exactly one change and asserts the reason code
appears with a non-zero exit. The cases cover the bypasses an independent review found in an earlier
revision of this checker, so they cannot silently return:

| Area | Cases and reason codes |
|---|---|
| Public claims | store anchor while unreleased, store URL in a meta attribute, German call to action → `CLAIM_PREMATURE_RELEASE` |
| Accessibility | removed skip link, skip link to the wrong target → `SKIP_LINK_NOT_FIRST`; commented-out `<main>` → `MAIN_LANDMARK_MISSING`; skip link hidden by CSS → `SKIP_LINK_HIDDEN`; focus outline removed → `FOCUS_STYLE_REMOVED`; anchor without `href` → `LINK_WITHOUT_HREF`; link without a name → `LINK_WITHOUT_NAME`; duplicate id → `DUPLICATE_ID`; unlabelled nav → `NAV_UNLABELLED`; skipped heading → `HEADING_ORDER_SKIP`; mismatched heading tags → `HEADING_TAG_MISMATCH` |
| Links | broken internal link → `INTERNAL_LINK_BROKEN` |
| Third-party loads | script, `///` script, rel-token-list stylesheet, CSS `url()`, CSS `@import`, meta refresh, `<base>`, `srcset`, video poster → `EXTERNAL_RESOURCE`; inline tracker → `TRACKER_DETECTED` |
| Contrast | direct token, `var()` chain, `var()` fallback, 8-digit hex → `CONTRAST_BELOW_MIN`; `font:` shorthand → `PX_FONT_SIZE` |
| Contract | missing contract → `CONTRACT_FILE_MISSING`; remote mismatch → `GIT_REMOTE_MISMATCH`; origin removed → `GIT_REMOTE_MISSING`; repository mismatch → `CONTRACT_REPOSITORY_MISMATCH`; `contract_version: true` → `CONTRACT_VERSION_UNSUPPORTED`; non-string remote → `CONTRACT_REMOTE_INVALID` |
| Project identity | nested checkout, nested copy without `.git` → `NESTED_PROJECT_ROOT`; contract copied to `docs/AGENTS.md` and to `AGENTS.md.bak` → `CONFIGURATION_SHADOWED` |
| Mutation boundary | a write outside the boundary, a change that adds `assets/**` to the allowlist and writes there, an ignored (`git/info/exclude`) write, and a symlink escaping the checkout → `MUTATION_OUTSIDE_BOUNDARY` (all checked against the base ref) |
| Inert markup | `<main>` inside `<template>` and inside `<noscript>` → `MAIN_LANDMARK_MISSING` |
| Focus visibility | `outline: 3px solid transparent`, `outline-style: none` → `FOCUS_STYLE_REMOVED` |
| CSS parsing | a colour behind a comment, and an uppercase `COLOR` property → `CONTRAST_BELOW_MIN` |
| Claim negation | a call to action with a distant unrelated "Nicht" → `CLAIM_PREMATURE_RELEASE` |
| Form submission | an external `<form action>` → `EXTERNAL_RESOURCE` |

Accepted controls (must not be rejected): a reworded but accurate status phrase, a declared
white-on-petrol colour pair, image `alt` text naming a heading and a link, and a documentation change
inside the mutation boundary.

Enforcement classification: **`VALIDATOR_AVAILABLE`, not `HOOK_ENFORCED`.** `.github/workflows/**` is
forbidden by the contract, so nothing runs the checker automatically; a green run is evidence that the
checker ran on that revision.

## 3. Headed browser measurement

Browser: Chromium 1248 from the host Playwright cache, launched **headed** on the operator's display
session. The measurement script is committed at `docs/verify/web_headed_evidence.js`; it needs a
Chromium binary (`CHROME_PATH`) and a local `playwright-core` (`PW`), neither of which the repository
installs, so the run is reproducible on a host that has them. Pages measured: the locally served
repository and the live site.

| Measurement | Local | Live (`https://feldexa.github.io/Feldexa-Web/`) |
|---|---|---|
| Horizontal overflow at 320/390/768/1024/1280/1440 px | none | none |
| Text elements measured for contrast | 49 | 49 |
| Elements below 4.5:1 (or 3:1 when large) | 0 | 0 |
| Third-party network requests | 0 | 0 |
| Console errors | 0 after the inline favicon was added | 1× 404 for `/favicon.ico` (pre-publication revision) |
| Skip link on the first Tab | visible at 16/16 px with a 3 px solid outline | same |
| Heading count | 7 | 7 |

The live page at the time of measurement was `767b68b`, which predates the inline favicon added by
this change; its 404 is the browser's automatic `/favicon.ico` request, which the favicon fixes. The
live site is re-measured after publication (§5).

Design limits recorded honestly: the page is light-only (`color-scheme: light`); a browser that
prefers a dark scheme still receives the light design by decision, not by accident. No dark theme is
claimed.

## 4. What was not measured here

- TalkBack, rotor and screen-reader announcement behaviour: this is a static page without app
  semantics; only DOM-level landmarks, heading order, focus and computed colours were measured.
- Automated axe/WCAG rule engines: none is installed and no dependency is added. The checks above are
  the project's own; they are not a substitute for a full audit.
- The app itself: this repository cannot produce evidence about app behaviour.

## 5. Re-measurement after publication

After the merge to `main` and the GitHub Pages deployment completes, the live page is checked again:

```
python3 docs/verify/verify_site.py --url https://feldexa.github.io/Feldexa-Web/
```

The result is recorded in the pull-request comment and in the issue closing comment, with the
deployment's exact live revision.

## 6. Host and global-configuration audit (safe summary)

The repository contract is project-local. A bounded audit of the harness configuration used on this
workstation was performed and recorded here only as status, never as contents:

| Item | Status | How it was established |
|---|---|---|
| Project-local contract present and parsed | `PASS` | `docs/verify/verify_site.py` |
| Contract carried by exactly one file | `PASS` | `contract.single_authority` |
| Checkout is the Git root, no nested copy | `PASS` | `contract.root_identity`, `contract.no_nested_root` |
| Project-specific global instructions/skills for this repository | none found | a bounded search of the installed harness configuration directories for this project's name returned no match; the only global skill present is a generic, unrelated one |
| Global configuration on other workstations | `NOT_VERIFIED` | no access from this host; never reported as `PASS` |
| Absolute checkout paths in tracked files | none | the checker reads the tracked tree; this note records no host path |

Cross-host configuration gaps stay explicit follow-up work: this repository cannot audit a host it
does not run on, and must not claim to.

## 7. Review history

Two independent reviews were required. The first (of `095286a`) rejected the change with eight
blocking findings:
claims were read from text only, the mutation boundary could be widened by the change under review,
several third-party loads and tracker placements were not seen, contrast resolution could be bypassed
by `var()` chains, a duplicate contract was ignored when its filename contained `AGENTS.md`, the
`repository` field was never checked, accessibility checks were presence-only, and this note's numbers
did not match the commands. Each was repaired and each repair has a negative case in §2; the tooling
moved to `docs/` so the change needs no widening of the boundary it is checked against. The second
review (of `2d89f73`) confirmed those eight repaired and found five more, all of the same class — a
PASS for something not measured: inert `<main>` inside `<template>`/`<noscript>`, a transparent or
`outline-style: none` focus ring, a declared colour hidden behind a CSS comment or written as
uppercase `COLOR`, a call to action with an unrelated distant negation, and a forbidden write hidden
by `git/info/exclude`. Each is repaired with a negative case in §2, and the checker now also reports
declared-pair contrast without rejecting a legitimate white-on-accent pair. The head was re-reviewed
again after these repairs; the exact SHA of every reviewed head is recorded in the pull-request
comment, which is the only place it can be stated without guessing it in advance.
