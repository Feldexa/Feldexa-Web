# Feldexa-Web agent contract

This file is the project-local contract for agent work in **this** repository (the public website).
It extends, and never duplicates, the generic cross-project policy that lives in the harness's global
configuration. Where the two disagree about this repository, this file wins.

This repository is the public companion site of the private Android app `Feldexa/Feldexa`. It is not
the app and contains no app code.

## Mission and mutation boundaries

Allowed here:

- Static site content: `index.html`, `styles.css`, `docs/*.md`, `README.md`.
- Accessibility, wording and layout improvements that keep the site's claims true.
- Evidence notes under `docs/`.

Not allowed here:

- App code, build configuration for the app, or copies of the app repository.
- Any document content, OCR text, form answers, signatures, credentials, tokens or personal data.
- Product claims that are not implemented and verified in the app repository. "Planned" and
  "in development" are the correct words for everything that is not released.
- Analytics, trackers, third-party embeds or any request that would send visitor data anywhere.
- Paid infrastructure, private CI, or any new recurring cost.

Publishing the site is a release action. Do not deploy, publish or change DNS unless the work item
explicitly requires it.

## Repository identity

- Canonical remote: `https://github.com/Feldexa/Feldexa-Web` (norm equivalent: `git@github.com:Feldexa/Feldexa-Web.git`).
- Default branch: `main`. Work happens on issue-linked branches; `main` is only advanced by reviewed merges.
- No submodules, no worktrees, no forks are part of this contract. A fork is a different root and must
  declare its own contract.
- The local checkout location is host-local configuration and does not belong in this file.

## Path map

| Path | Meaning |
|---|---|
| `index.html` | The entire published landing page. Single page, no build step. |
| `styles.css` | The only stylesheet. Design tokens are the `:root` custom properties. |
| `docs/` | Public documents: roadmap, privacy principles, evidence notes. |
| `README.md` | Repository introduction and status. |

## Required checks before a change is considered done

1. `python3 -m http.server 8765 --bind 127.0.0.1` from the repository root, then load
   `http://127.0.0.1:8765/`. There is no build step and no test framework: the served page *is* the
   artifact, so it must be fetched and inspected, not assumed.
2. Accessibility baseline that every change must keep: a keyboard-operable skip link to the main
   content, a `main` landmark, one labelled `nav` per navigation group, a heading hierarchy without
   skipped levels, and a visible focus style for every focusable element.
3. Contrast: body text at least 4.5:1 and large text at least 3:1 against its own background.
4. `git diff --check` and a served-page read-back of the changed regions.
5. Record the result as evidence: what was run, the exact revision, and what was observed. A green
   markdown checklist is not evidence.

## Evidence

- Evidence for website changes belongs in `docs/` as a dated note, or in a pull-request comment.
- Never paste screenshots, HTML dumps or text that contains visitor or document data.
- A local check is not an independent review; say which one a result came from.

## Contract (machine-readable)

```yaml
contract_version: 1
repository: Feldexa/Feldexa-Web
root_policy:
  rule: NO_NESTED_PROJECT_ROOT
  detail: >-
    Before a write, resolve the real repository root and the normalized destination, including
    symlinks and not-yet-existing parents. Refuse to create a second copy of this project inside
    itself. Legitimate same-name directories that are not this project are not refused by name alone.
shadowing_policy:
  rule: NO_CONFIGURATION_SHADOWING
  detail: >-
    Only one authority per concern. This file owns project identity, the path map, mutation
    boundaries and local checks; global harness configuration owns generic working policy; host-local
    ignored configuration owns absolute checkout paths.
canonical_remote:
  https: https://github.com/Feldexa/Feldexa-Web
  ssh: git@github.com:Feldexa/Feldexa-Web.git
default_branch: main
allowed_write_paths:
  - index.html
  - styles.css
  - docs/**
  - README.md
forbidden_write_paths:
  - .github/workflows/**
  - "**/*.env"
  - "**/secrets/**"
  - app/**
required_checks:
  - serve the repository root over http and load the page
  - accessibility baseline (skip link, main landmark, labelled nav, heading order, visible focus)
  - contrast >= 4.5:1 body text, >= 3:1 large text
  - git diff --check
claims_policy:
  rule: CLAIMS_MUST_MATCH_VERIFIED_APP_BEHAVIOR
  detail: >-
    Every feature claim on the site must correspond to behaviour implemented and verified in
    Feldexa/Feldexa. Unreleased work is described as planned or in development.
no_trackers: true
no_paid_infrastructure: true
```

## Relationship to the app repository

- The app repository is the source of truth for what the product does; this repository is the source
  of truth for what is said publicly about it.
- When app behaviour changes, the website follows in its own change with its own evidence.
- A website statement is never evidence that an app feature works, and an app test result is never
  evidence that the published page is correct.
