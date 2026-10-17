# Website verification evidence — 2026-10-17

Scope: the machine-readable contract, the deterministic checker, and a headed-browser measurement of
the published page. This note records what was run and what was observed on the revision that
contains it (commit SHA recorded in the pull-request comment for this change).

Nothing here is a release claim. The site still describes the app as in development, which is
correct while `Feldexa/Feldexa` has no published release.

## 1. Deterministic checker

Command (repository root): `python3 tools/verify_site.py`

Observed: **45 checks: 44 pass, 0 fail, 1 skip** on the change; **44 checks: 43 pass, 0 fail, 1 skip** before the inline favicon was added. The skip is `layout.viewport_matrix`, which needs a
browser and is measured separately in §3; it is reported as `SKIP`, never as a pass.

Command: `python3 tools/verify_site.py --base origin/main`

Observed: `mutation.changed_paths` reports every path changed against `origin/main` (committed and
uncommitted) and confirms each one is inside `allowed_write_paths` and outside
`forbidden_write_paths`.

The checker validates the `AGENTS.md` contract block (schema, types, version, canonical remote against
`origin`, default branch, root and shadowing policy names, release status, claims policy, tracker and
paid-infrastructure flags), the checkout root, the absence of a nested copy of this repository, and
the absence of a second contract authority. It then serves the repository and checks the served page:
doctype, `lang`, title, viewport, description, skip link target, `main` landmark, labelled `nav`s,
one `h1`, heading order and tag balance, internal links and anchors, no third-party resources, no
tracker signatures, focus styles, responsive rule, declared-pair contrast, relative font units, and
the public claims against `release_status`.

## 2. Negative tests

Command: `python3 tools/verify_site_selftest.py`

Observed: **13 cases: 13 pass, 0 fail**. Each case copies the repository, applies one violation and
asserts the reason code appears with a non-zero exit:

| Case | Reason code |
|---|---|
| premature release claim | `CLAIM_PREMATURE_RELEASE` |
| removed skip link | `SKIP_LINK_NOT_FIRST` |
| third-party script | `EXTERNAL_RESOURCE` |
| tracker script | `TRACKER_DETECTED` |
| low-contrast token | `CONTRAST_BELOW_MIN` |
| skipped heading level | `HEADING_ORDER_SKIP` |
| missing contract | `CONTRACT_FILE_MISSING` |
| broken internal link | `INTERNAL_LINK_BROKEN` |
| remote mismatch | `GIT_REMOTE_MISMATCH` |
| nested project root | `NESTED_PROJECT_ROOT` |
| duplicate contract authority | `CONFIGURATION_SHADOWED` |
| write outside the mutation boundary | `MUTATION_OUTSIDE_BOUNDARY` |

Enforcement classification: **`VALIDATOR_AVAILABLE`, not `HOOK_ENFORCED`.** `.github/workflows/**` is
forbidden by the contract, so nothing runs the checker automatically; a green run is evidence that the
checker ran on that revision.

## 3. Headed browser measurement

Browser: Chromium 1248 from the host Playwright cache, launched **headed** on the operator's display
session. Pages measured: the locally served repository and the live site.

| Measurement | Local | Live (`https://feldexa.github.io/Feldexa-Web/`) |
|---|---|---|
| Horizontal overflow at 320/390/768/1024/1280/1440 px | none | none |
| Text elements measured for contrast | 49 | 49 |
| Elements below 4.5:1 (or 3:1 when large) | 0 | 0 |
| Third-party network requests | 0 | 0 |
| Console errors | 0 after the favicon fix | 1× 404 favicon (pre-publication revision) |
| Skip link on first Tab | visible at 16/16 px, 3 px solid outline | same |
| Heading count | 7 | 7 |

The live page at the time of measurement was `767b68b`, which predates the inline favicon added by
this change; its 404 is the browser's automatic `/favicon.ico` request and is exactly what the
favicon fixes. The live site is re-measured after publication (§5).

Design limits recorded honestly: the page is light-only (`color-scheme: light`); a `prefers-color-scheme:
dark` browser still receives the light design by decision, not by accident. No dark theme is claimed.

## 4. What was not measured here

- TalkBack, rotor and screen-reader announcement behaviour: this is a static page without app
  semantics; only DOM-level landmarks, heading order and focus were measured.
- Automated axe/WCAG rule engines: none is installed and no dependency is added. The checks above are
  the project's own; they are not a substitute for a full audit.
- The app itself: this repository cannot produce evidence about app behaviour.

## 5. Re-measurement after publication

After the merge to `main` and the GitHub Pages deployment completes, the live page is checked again:

```
python3 tools/verify_site.py --url https://feldexa.github.io/Feldexa-Web/
```

The result is recorded in the pull-request comment and in the issue closing comment, with the
deployment's exact live revision.

## 6. Host and global-configuration audit (safe summary)

The repository contract is project-local. A bounded audit of the harness configuration used on this
workstation was performed and recorded here only as status, never as contents:

| Item | Status | How it was established |
|---|---|---|
| Project-local contract present and parsed | `PASS` | `tools/verify_site.py` |
| Contract carried by exactly one file | `PASS` | `contract.single_authority` |
| Checkout is the Git root, no nested copy | `PASS` | `contract.root_identity`, `contract.no_nested_root` |
| Project-specific global instructions/skills for this repository | none found | a bounded search of the installed harness configuration directories for this project's name returned no match; the only global skill present is a generic, unrelated one |
| Global configuration on other workstations | `NOT_VERIFIED` | no access from this host; never reported as `PASS` |
| Absolute checkout paths in tracked files | none | the checker reads the tracked tree; this note records no host path |

Cross-host configuration gaps stay explicit follow-up work: this repository cannot audit a host it
does not run on, and must not claim to.
