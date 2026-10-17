# Feldexa

Feldexa is an Android application in development that turns scanned, non-fillable PDF forms into reusable smart forms through local, privacy-first processing.

## Status

Feldexa is currently in development. It is not yet available for download.

The first release is planned for Android 12 (API 31) and later, with German and English support. The core workflow is designed to work on-device: import a PDF, analyze likely fields, review them, fill the form, and export a standard PDF.

## Privacy-first principles

- Core document processing is designed for local/offline use.
- The core workflow does not upload PDFs, OCR text, form answers, or signatures for cloud processing.
- Technical diagnostics are designed to exclude document content.

## Planned commercial model

Planned freemium model with optional one-time watermark-free export. No subscription is planned for V1.

## Public information

- [Privacy Principles](docs/privacy-principles.md)
- [Public Roadmap](docs/roadmap.md)
- [Contract schema](docs/contract-schema.md)
- [GitHub Wiki](https://github.com/Feldexa/Feldexa-Web/wiki)

## Verification

The site has no build step. Its checks are dependency-free and executable:

- `python3 tools/verify_site.py` — contract schema, served page, accessibility baseline, contrast,
  internal links, tracker and third-party-resource scan, and the public claims against the declared
  release status.
- `python3 tools/verify_site_selftest.py` — proves each check fails when the violation it guards
  against is introduced.
- `git diff --check` — whitespace hygiene.

Feldexa is developed privately. This repository contains public-safe product information only.
