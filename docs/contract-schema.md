# Contract schema (v1)

`AGENTS.md` carries the project-local contract in two forms: prose that a human reads, and one
machine-readable block that `tools/verify_site.py` parses and validates. This document is the schema
those two forms share. `AGENTS.md` is the single authority for the values; this file never repeats
them.

## Where the block lives and how it is read

- The block is the last fenced `yaml` block in `AGENTS.md` that contains the version key.
- The verifier parses a deliberately small YAML subset: nested mappings, scalar lists, quoted and
  plain scalars, booleans, integers and `>-` folded block scalars. Tabs, flow collections (`{}`,
  `[]`), anchors, aliases, tags and duplicate keys are rejected with a reason code instead of being
  guessed at, so a contract the checker cannot fully read never passes.
- Unknown keys fail the schema check. Adding a field is therefore a deliberate change: extend
  `CONTRACT_SCHEMA` in `tools/verify_site.py`, add it below, and change the value in `AGENTS.md` in
  the same reviewed change.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `contract_version` | integer | yes | Schema version. Only `1` is supported. A different value fails `contract.version`. |
| `repository` | string | yes | `owner/name`. Checked against the normalized `origin` remote and `canonical_remote`. |
| `root_policy` | mapping | yes | `rule` must be `NO_NESTED_PROJECT_ROOT`. |
| `shadowing_policy` | mapping | yes | `rule` must be `NO_CONFIGURATION_SHADOWING`. |
| `canonical_remote` | mapping | yes | `https` and `ssh` forms; both must normalize to the same `owner/name`. |
| `default_branch` | string | yes | Must be `main`. |
| `allowed_write_paths` | list of strings | yes | Globs. Every path changed against the base ref must match one. |
| `forbidden_write_paths` | list of strings | yes | Globs. A match fails even if an allowed pattern also matches. |
| `release_status` | string | yes | `unreleased` or `released`. Drives the public-claim checks. |
| `required_checks` | list of strings | yes | The checks a change must run, in order. |
| `claims_policy` | mapping | yes | `rule` must be `CLAIMS_MUST_MATCH_VERIFIED_APP_BEHAVIOR`. |
| `no_trackers` | boolean | yes | Must be `true`; the page check also scans for tracker signatures. |
| `no_paid_infrastructure` | boolean | yes | Must be `true`. |

## Checks the contract drives

`python3 tools/verify_site.py` prints one line per check and exits non-zero if any fails.

| Check | What it establishes | Reason code on failure |
|---|---|---|
| `contract.parse` | The block is present and inside the supported subset. | `CONTRACT_BLOCK_MISSING`, `CONTRACT_PARSE_ERROR` |
| `contract.schema` / `contract.types` | Required fields present with the documented types. | `CONTRACT_FIELD_MISSING`, `CONTRACT_TYPE_INVALID` |
| `contract.version` | Supported schema version. | `CONTRACT_VERSION_UNSUPPORTED` |
| `contract.canonical_remote` / `contract.git_remote` | Both remote forms normalize to the same repository, and so does `origin`. | `CONTRACT_REMOTE_INVALID`, `GIT_REMOTE_MISMATCH` |
| `contract.default_branch` | `main`. | `CONTRACT_DEFAULT_BRANCH` |
| `contract.root_policy` / `contract.shadowing_policy` | The declared rule names. | `CONTRACT_ROOT_POLICY`, `CONTRACT_SHADOWING_POLICY` |
| `contract.root_identity` | The checkout is the Git root, not a directory inside another project. | `WRONG_PROJECT_ROOT` |
| `contract.no_nested_root` | No second copy of this repository exists inside itself. | `NESTED_PROJECT_ROOT` |
| `contract.single_authority` | No other file carries the contract block. | `CONFIGURATION_SHADOWED` |
| `contract.mutation_boundary` | Allowed and forbidden lists are non-empty (structure only). | `CONTRACT_MUTATION_BOUNDARY` |
| `mutation.changed_paths` (with `--base <ref>`) | Every path changed against the base is inside `allowed_write_paths` and outside `forbidden_write_paths`. | `MUTATION_OUTSIDE_BOUNDARY` |
| `claims.unreleased_status` / `claims.no_premature_release` | With `release_status: unreleased`, the page says so and offers no store link or download call to action. | `CLAIM_STATUS_MISSING`, `CLAIM_PREMATURE_RELEASE` |
| `claims.released_status` | With `release_status: released`, the page carries the store path. | `CLAIM_RELEASE_LINK_MISSING` |

The page, accessibility, link, privacy and contrast checks are independent of the contract fields and
are listed by `python3 tools/verify_site.py --list-checks`.

## What this does and does not enforce

- **Validator available, not hook-enforced.** `.github/workflows/**` is forbidden to this project, so
  nothing runs the verifier automatically on push or pull request. The classification is
  `VALIDATOR_AVAILABLE`; a green run is evidence that the checker was executed on that revision, not
  that a hook would have run it.
- **Host-level policy stays host-local.** Absolute checkout paths, harness skill scopes and Android
  Studio availability are not repository facts and are not checked here.
- **Negative tests prove the checks can fail.** `python3 tools/verify_site_selftest.py` copies the
  repository, applies one violation per case and asserts the reason code appears with a non-zero exit.
  A check that cannot be made to fail is not enforcement.
