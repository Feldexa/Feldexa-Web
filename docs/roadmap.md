# Public Roadmap

Feldexa is in private development. **It is not released:** there is no download, no store listing and no
pricing, and this page does not promise any.

What follows separates what is built and verified in the app repository from what does not exist yet. These are
*development* statuses, not release statuses: the product is unreleased, so every step below is described as in
development, with the part that the app repository's own gates verify named beside it.

## Where the work stands

1. **Android foundation and secure local document model** — in development. Private local storage with
   versioned migrations and migration backups; a document store encrypted at rest, with keys held in the Android
   keystore (automated tests; that path is not yet measured on a device); and a release build that declares no
   network permission.
2. **PDF import, rendering, and field review** — in development. Import and rendering of PDF forms, automatic field
   detection that includes table cells, confidence marking for proposals, and per-field review with confirm,
   change type and delete.
3. **Guided editing, export, and recovery** — in development. Field-by-field guidance with automatic zoom onto the
   field being edited, export, sharing and printing, and recovery of an open document after the app process is
   killed.
4. **Accessibility, localization, privacy, and quality validation** — in development, and **not finished as a
   human review**. German and English; light, dark and high-contrast themes plus a follow-system setting;
   measured contrast and touch-target gates; screen-reader labels and custom actions for the editor's own
   controls; and a 132-frame render matrix (22 states × 2 locales × 3 themes) that is captured and automatically
   audited on every matrix run. No independent accessibility review has been carried out yet.
5. **Internal and closed testing before any staged production rollout** — not started.

Optional privacy protections that exist and are user-controlled: blocking screenshots and screen recordings,
gating document content behind device authentication, and automatic deletion after a chosen retention period.

## What is explicitly not done

- No signed distributable artifact exists, so the app cannot be installed from a store.
- No store entry, staged rollout or production release has been performed.
- Detection quality against real German authority forms is not published; it needs a rights-cleared corpus and
  independent annotation, as described in the app repository's corpus policy.
- The full user journey has not been accepted on a real device by a person, and no rendered frame set has been
  approved by a human reviewer.

No dates are announced.
