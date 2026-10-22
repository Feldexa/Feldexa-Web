# Public Roadmap

Feldexa is in private development. **It is not released:** there is no download, no store listing and no
pricing, and this page does not promise any.

What follows separates what exists and is verified in the app repository from what does not exist yet. A step is
called *implemented* only where that repository's own gates verify the behaviour; "not started" means exactly
that.

## Where the work stands

1. **Android foundation and secure local document model** — implemented. Private local storage with versioned
   migrations and migration backups, a document store that is encrypted at rest, and no network permission in
   the shipping build.
2. **PDF import, rendering, and field review** — implemented. Import and rendering of PDF forms, automatic field
   detection that includes table cells, confidence marking for proposals, and per-field review with confirm,
   change type and delete.
3. **Guided editing, export, and recovery** — implemented. Field-by-field guidance with automatic zoom onto the
   field being edited, export, sharing and printing, and recovery of an open document after the app process is
   killed.
4. **Accessibility, localization, privacy, and quality validation** — implemented as automated gates, and
   **not finished as a human review**. German and English, three themes, measured contrast and touch-target
   gates, screen-reader labels and custom actions for the editor's own controls, and a 132-frame render matrix
   captured per release candidate. No independent accessibility review has been carried out yet.
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

Dates and download availability will be announced only when they are confirmed.
