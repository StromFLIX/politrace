# Data provenance and reuse

There is no blanket licence here for third-party source materials.

- **`tests/fixtures/demo/` (not published)**: original fictional fixture texts and assessments are dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Party names identify the UI fixtures; they are not endorsements, real quotations, actual votes or factual assessments of those parties.
- **Official law text**: German official statutes are generally covered by § 5(1) UrhG. Preserve the official source, publication citation and provenance. Do not imply that the generated transcription is an official consolidated legal version. Source-site assets, unofficial annotations and other surrounding materials may have separate rights.
- **Manifestos and other third-party sources**: rights remain with their publishers. A publicly downloadable PDF is not automatically licensed for republication of its entire transcription. Before importing a real programme into a public repository/API, check the applicable licence or obtain permission. A citation alone does not authorise unrestricted full-text republication. Use `source.license_note` to record the actual basis; do not make up a permission.
- **New live annotations and citizen contributions**: keep attribution and source metadata. A project-wide licence for these annotations and the source code should be chosen explicitly by the repository owner; none is inferred merely from a public endpoint or the ability to open a PR.

Do not commit original PDFs, personal data, credentials or private documents. The ingestion and analysis stages are designed for public political and legal sources only.

## Dependency notices

The PDF pipeline uses PyMuPDF and PyMuPDF4LLM, which have AGPL/commercial licensing terms. Running the pipeline in CI does not remove those obligations. Review the dependency licences and your deployment/distribution model, or obtain an appropriate commercial licence/use an alternative extractor where needed. Python and PDF libraries are not included in the static web runtime image.

Inter font files are bundled locally through `@fontsource-variable/inter` and are covered by the [SIL Open Font License](public/fonts/OFL.txt), which is also distributed in the static website at `/fonts/OFL.txt`. Other software dependencies retain their respective licences.
