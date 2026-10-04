# Complete-programme batch

The dedicated `programmes.yml` **GitHub Actions** job imports the five remaining SHA-pinned national programmes and extracts every source leaf. It runs independently of the existing Grünen all-law experiment. It does not schedule any Nautionette workflow and does not claim to have completed law matching for the other parties.

- Primary model: GPT-6 Luna, pinned to `openai/flex`, no standard-route fallback.
- A bounded Sonnet fallback is allowed after primary validation failures; exact quotations remain mandatory.
- Each programme has one durable **$5 cumulative** safety ceiling, including rejected outputs, retries and unknown-charge reservations. These five ledgers are separate from the existing $25 Grünen experiment. No independent paid probes are made.
- Each programme stores completed source text/tree, completed criterion leaves and cached replies independently. A failed sibling does not cancel other programmes.
- A push changing `.github/backfills/programmes.json` triggers the specified sources. For a continuation, set each selected source's `resume_runs` entry to its latest artifact-bearing run and increment `revision`. Never rerun a paid job with a fresh ledger. The preflight checks detect stale or lost spending checkpoints.
- Artifacts are source-specific: `programme-checkpoint-<id>`. They never overwrite another programme's data/ledger on restore. Inspect `result.json`, validate the recovered store and inspect the diff before publishing data.
- Source terms and attribution remain in the records. The explicit `attributed-transcription` mode does not invent an open licence or approval. Copyrighted source material is not relicensed by the repository's software/data licences; downstream users must consult actual publisher terms. No statement of personal authority or third-party permission is generated.
- Programme dates identify the documented resolution or PDF edition (as noted individually), not an invented first-upload date. PDF hashes, visually inspected textless-page declarations, and extraction caveats are retained.
- Artifacts are generated proposals, not human-approved assessments. Publication must not reset review status or imply that quotations matching Markdown prove perfect PDF transcription.

Monitor using `gh run watch <run> --exit-status`. On failure inspect `gh run view <run> --log-failed` and download the corresponding checkpoint before editing or resuming. Do not print credentials or place tokens in the repository.
