# Contract schema (v1)

`AGENTS.md` carries the project-local contract in two forms: prose a human reads and one
machine-readable block that `docs/verify/verify_site.py` parses and validates. This document is the
schema both forms share. `AGENTS.md` is the single authority for the values; this file never repeats
them.

## Where the block lives and how it is read

- The block is the last fenced `yaml` block in `AGENTS.md` that contains the version key.
- The verifier parses a deliberately small YAML subset: nested mappings, scalar lists, quoted and
  plain scalars, booleans, integers and `>-` folded block scalars. Tab indentation, flow collections
  (`{}`, `[]`), anchors, aliases, tags and duplicate keys are rejected with a reason code instead of
  being guessed at. A contract the checker cannot fully read never passes.
- Unknown keys fail the schema check. Adding a field is a deliberate change: extend `CONTRACT_SCHEMA`
  in the verifier, document it below, and change the value in `AGENTS.md` in the same reviewed change.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `contract_version` | integer (not boolean) | yes | Schema version. Only `1` is supported. |
| `repository` | string | yes | `owner/name`; must equal the normalized `canonical_remote` and the normalized `origin`. |
| `root_policy` | mapping | yes | `rule` must be `NO_NESTED_PROJECT_ROOT`. |
| `shadowing_policy` | mapping | yes | `rule` must be `NO_CONFIGURATION_SHADOWING`. |
| `canonical_remote` | mapping of two strings | yes | `https` and `ssh`; both must normalize to one `owner/name`. |
| `default_branch` | string | yes | Must be `main`. |
| `allowed_write_paths` | list of non-empty strings | yes | Globs. Enforced against the contract **at the base ref** (see below). |
| `forbidden_write_paths` | list of non-empty strings | yes | Globs. A match fails even if an allowed pattern also matches. |
| `release_status` | string | yes | `unreleased` or `released`. Drives the public-claim checks. |
| `required_checks` | list of non-empty strings | yes | The checks a change must run. |
| `claims_policy` | mapping | yes | `rule` must be `CLAIMS_MUST_MATCH_VERIFIED_APP_BEHAVIOR`. |
| `no_trackers` | boolean | yes | Must be `true`. |
| `no_paid_infrastructure` | boolean | yes | Must be `true`. |

## Checks and reason codes

`python3 docs/verify/verify_site.py` prints one line per check and exits non-zero if any fails.
`--list-checks` prints the complete list.

### Contract and identity

| Check | What it establishes | Reason code |
|---|---|---|
| `contract.parse` | The block is present and inside the supported subset. | `CONTRACT_FILE_MISSING`, `CONTRACT_BLOCK_MISSING`, `CONTRACT_PARSE_ERROR` |
| `contract.schema` / `contract.types` | Required fields present with the documented types. | `CONTRACT_FIELD_MISSING`, `CONTRACT_FIELD_UNKNOWN`, `CONTRACT_TYPE_INVALID`, `CONTRACT_MALFORMED` |
| `contract.version` | `contract_version` is the integer `1`. | `CONTRACT_VERSION_UNSUPPORTED` |
| `contract.repository` | `repository` equals the canonical remote and `origin`. | `CONTRACT_REPOSITORY_MISMATCH` |
| `contract.canonical_remote` | Both remote forms are strings and normalize to one repository. | `CONTRACT_REMOTE_INVALID` |
| `contract.git_remote` | `origin` normalizes to the canonical repository; a missing `origin` fails. | `GIT_REMOTE_MISSING`, `GIT_REMOTE_MISMATCH` |
| `contract.default_branch` | `main`. | `CONTRACT_DEFAULT_BRANCH` |
| `contract.root_policy` / `contract.shadowing_policy` | The declared rule names. | `CONTRACT_ROOT_POLICY`, `CONTRACT_SHADOWING_POLICY` |
| `contract.mutation_boundary` | Allowed and forbidden lists are non-empty (structure only). | `CONTRACT_MUTATION_BOUNDARY` |
| `contract.release_status` | A known release state. | `CONTRACT_RELEASE_STATUS` |
| `contract.claims_policy` | The claims rule name. | `CONTRACT_CLAIMS_POLICY` |
| `contract.no_trackers` / `contract.no_paid_infrastructure` | Both are `true`. | `CONTRACT_TRACKERS_FIELD`, `CONTRACT_PAID_INFRA_FIELD` |
| `contract.root_identity` | The checkout is the Git root. | `WRONG_PROJECT_ROOT` |
| `contract.no_nested_root` | No second copy of this project exists inside it (with or without `.git`, up to six levels deep, `docs/` included). | `NESTED_PROJECT_ROOT` |
| `contract.single_authority` | Exactly one file carries the contract block. | `CONFIGURATION_SHADOWED` |

### Mutation boundary

`mutation.changed_paths` runs with `--base <ref>` and checks every changed path — committed against
the base, staged, unstaged, untracked and ignored — against the contract **at that base ref**. For
ignored paths only `forbidden_write_paths` is enforced: a host-local artifact such as `.DS_Store` is
not a project write, while an ignored write under `app/` or `secrets/` is still refused., read with `git show <ref>:AGENTS.md`. A change therefore
cannot widen its own boundary. Changed symlinks are resolved and refused if they leave the checkout.
`AGENTS.md` itself is allowed because it is the policy authority; the delta it applies is reported by
`mutation.contract_delta` — allowlist additions and removals, forbidden-list changes, a
`release_status` flip, the branch and the two booleans, and the `required_checks` count — so a
reviewer sees every contract change explicitly. With no change it reports `SKIP`.

| Check | Reason code |
|---|---|
| `mutation.changed_paths` | `MUTATION_OUTSIDE_BOUNDARY`, `MUTATION_DIFF_FAILED`, `MUTATION_BASELINE_UNKNOWN` |
| `mutation.contract_delta` | `CONTRACT_DELTA_UNREPORTED` (reserved; the check is informational and a contract change is a review matter) |

### Page, accessibility, links, privacy, claims

| Check | What it establishes | Reason code |
|---|---|---|
| `page.fetch` / `page.check_error` | The page is served and the checker did not crash. | `PAGE_FETCH_FAILED`, `PAGE_HTTP_STATUS`, `VERIFIER_ERROR` |
| `html.doctype`, `html.lang`, `page.title`, `html.viewport`, `html.description` | Document basics. | `DOCTYPE_MISSING`, `LANG_MISSING`, `TITLE_MISSING`, `VIEWPORT_MISSING`, `DESCRIPTION_MISSING` |
| `a11y.main_landmark` / `a11y.main_targetable` | Exactly one rendered `<main>` with an id. Comments and inert content (`<template>`, `<noscript>`) cannot fake it. | `MAIN_LANDMARK_MISSING`, `MAIN_ID_MISSING` |
| `a11y.skip_link` | The first link addresses the main landmark. | `SKIP_LINK_NOT_FIRST` |
| `a11y.nav_labels` | One accessible label per `nav`. | `NAV_UNLABELLED` |
| `a11y.heading_h1`, `a11y.heading_order`, `a11y.heading_markup`, `a11y.heading_text` | One `h1` first, no skipped level, balanced tags, no empty heading. An image's `alt` text and a heading's `aria-label` count as content. | `H1_COUNT`, `HEADING_ORDER_SKIP`, `HEADING_TAG_MISMATCH`, `HEADING_EMPTY` |
| `a11y.link_href`, `a11y.link_name`, `a11y.duplicate_id` | Every anchor has a target and a name (text, `aria-label`, `title` or an image's `alt`); ids are unique. | `LINK_WITHOUT_HREF`, `LINK_WITHOUT_NAME`, `DUPLICATE_ID` |
| `links.internal` | Every internal link and `#fragment` resolves, in repo and `--url` mode alike. | `INTERNAL_LINK_BROKEN` |
| `links.local_resources` | Every local resource exists, is a file and stays inside the checkout. | `LOCAL_RESOURCE_BROKEN` |
| `privacy.no_external_resources` | No URL-bearing attribute (including `form action`, `button formaction`, `srcset`, `poster`, `object data`, `embed src`), stylesheet `url()`/`@import`, `<base>` or meta refresh loads a third-party origin (`//`, `///` and rel-token lists included). | `EXTERNAL_RESOURCE` |
| `privacy.no_meta_refresh_redirect` | No meta refresh at all. | `META_REFRESH_REDIRECT` |
| `privacy.no_trackers` | No tracker signature in the HTML, inline styles, stylesheets or inline scripts. | `TRACKER_DETECTED` |
| `css.stylesheet`, `css.fetch` | Every declared stylesheet is read. | `STYLESHEET_MISSING`, `CSS_FETCH_FAILED` |
| `css.focus_visible`, `css.focus_not_removed`, `css.skip_link_focus`, `css.skip_link_visible` | A visible focus style exists and is not made invisible by any shorthand or longhand (`none`, `0`, `hidden`, `transparent`), and the skip link is not hidden by default. | `FOCUS_STYLE_MISSING`, `FOCUS_STYLE_REMOVED`, `SKIP_LINK_FOCUS_MISSING`, `SKIP_LINK_HIDDEN` |
| `css.responsive` | A responsive breakpoint exists. | `NO_RESPONSIVE_RULE` |
| `css.contrast` | Every declared pair reaches 4.5:1. A rule that declares its own surface is judged against that surface; a rule that does not is judged against the surface of an ancestor selector it names, or the page surface. `var()` chains and fallbacks, 3/4/6/8-digit hex, `rgb()`/`hsl()` and named colours resolve; comments and uppercase properties are read; an unresolvable colour fails. | `CONTRAST_BELOW_MIN` |
| `css.relative_units` | No `font-size` or `font` shorthand in `px`. | `PX_FONT_SIZE` |
| `claims.unreleased_status` / `claims.no_premature_release` | With `release_status: unreleased`, the page says so and carries no store link or download call to action in text *or* attributes. | `CLAIM_STATUS_MISSING`, `CLAIM_PREMATURE_RELEASE` |
| `claims.released_status` | With `release_status: released`, a Play Store link exists. | `CLAIM_RELEASE_LINK_MISSING` |
| `layout.viewport_matrix` | Not asserted by this checker; always reported `SKIP` and measured in a headed browser. | `VISUAL_NOT_EXECUTED` |
| `links.external` (opt-in) | External anchors answer to `HEAD` (or `GET` when `HEAD` is not allowed). | `EXTERNAL_LINK_BROKEN` |

## What this does and does not enforce

- **Validator available, not hook-enforced.** `.github/workflows/**` is forbidden to this project, so
  nothing runs the verifier automatically on push or pull request. The classification is
  `VALIDATOR_AVAILABLE`; a green run is evidence that the checker ran on that revision, not that a
  hook would have run it.
- **The contract can still be changed.** `AGENTS.md` is the authority and is allowed to change; the
  verifier reports what changed rather than preventing it. Preventing it would need an authority
  outside the repository, which this project does not have.
- **Host-level policy stays host-local.** Absolute checkout paths, harness skill scopes and Android
  Studio availability are not repository facts and are not checked here.
- **Contrast is a static measurement.** It resolves the stylesheet and a simple ancestor relationship
  between selectors, not the full cascade; a colour applied by script or a user agent default is out
  of scope. The headed browser measurement in `docs/EVIDENCE_SITE_VERIFICATION_2026-10-17.md` is the
  rendered check.
- **Files under `.git/` are outside the boundary model.** Git hooks are not tracked paths and the
  checker does not read them.
- **Negative tests prove the checks can fail.** `python3 docs/verify/verify_site_selftest.py` copies
  the repository, applies one violation per case (60 cases), plus a clean baseline and eight accepted
  controls, and asserts the reason code appears with a non-zero exit.
