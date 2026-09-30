# Website accessibility evidence

Date: 2026-09-30, Europe/Berlin

Branch: codex/web-accessibility-foundation
Base: fe7ed766fb999522603b836f4fa4f73d9196328c (Feldexa/Feldexa-Web main)

## Change
- Added keyboard-operable skip link to #main-content.
- Added labelled navigation landmark for public repo/wiki links.
- Added stable heading IDs and aria-labelledby relationships for three info panels.
- Added visible :focus/:focus-visible styles.

## Verification
- git diff --check — pass on the local branch.
- Browser preview http://127.0.0.1:8765/ loaded locally.
- Pressing Tab focused visible “Skip to main content” link in AX tree.
- AX tree exposed main-content, Public links navigation, and labelled section headings.
- Contrast spot-checks: muted 5.00:1 / 5.21:1; petrol links 6.20:1 / 6.47:1.

This evidence accompanies the unmerged review PR for this branch. It is not a publication or release-completion claim.
