# Politrace

Source-cited German political promises and their proposed connections to published laws.

- **Site:** <https://politrace.stromflix.com>
- **Processing & gaps:** <https://politrace.stromflix.com/fortschritt/>
- **Versioned API:** <https://politrace.stromflix.com/api/v1/live/index.json>

## Data, not a party ranking

`data/live` contains publisher-attributed programmes, criteria with exact citations, official laws, proposed impacts, independently sourced voting records (where available), OCR reading editions and coverage reports. All six Bundestag programme extractions are published. That does **not** imply all law relationships, semantic extraction, deduplication or human review are complete.

Generated assessments remain **proposed**. Impact, fulfilment and voting behavior are separate. No relationship is inferred from missing evidence. Citizen edits use ordinary Git pull requests; the pipeline does not overwrite existing criterion/impact records.

## Local development and verification

```sh
uv sync --frozen
npm ci
uv run politrace validate
uv run pytest
uv run ruff check .
npm test
npm run build
npx playwright install chromium
npm run test:e2e
npm run dev
```

Fictional regression fixtures live only under `tests/fixtures`. They are not published as routes or API datasets. Production is a static Astro application served by Nginx in Docker Compose. No provider credential goes into frontend builds.

## Resumable production processing

`.github/workflows/production.yml` is the single scheduled production entry point. It runs at **06:00 Europe/Berlin**, including DST, and automatically dispatches another bounded slice when work remains. CLI dispatch: `gh workflow run production.yml --ref main`. Do not rerun a paid job from an older snapshot.

1. Restore the newest **results and cumulative charge ledger together**. A paid run with a missing ledger blocks spending rather than resetting costs.
2. Reconcile the official publication inventory. Where archive search is unavailable, use the disclosed dated inventory plus current RSS; do not pretend this proves new full historical coverage.
3. Produce page-complete OCR reading editions with Mistral. Cache individual PDF-page subsets, preserve source hashes, retain headers/footers, flag suspicious transcription, and isolate document failures.
4. Build shared law-passage indexes and retrieve candidates across every temporally applicable programme with independent programme quotas.
5. Process six-candidate work units with bounded concurrency. Persist validated pairs immediately, report a heartbeat every 45 seconds and resume only pending work.
6. Use bounded backoff for provider failures, isolate repeatedly invalid batches, and stop automatic spending on credit/budget failures. These are errors, not no-link decisions.
7. Upload the full recoverable checkpoint even after failure. Validate and publish the safe partial snapshot to `main`, respecting concurrent changes and branch protection, then explicitly dispatch CI.

Model, route, concurrency, slice duration and cumulative limit are in `.github/production.json`. The primary route is **GPT-6 Luna / OpenAI Flex** without automatic standard-price fallback. Proposed links receive a stronger-model challenge. The inherited cumulative cap includes previous calls, retries and conservative unresolved reservations; it is not reset per party or per slice.

Required Actions secrets: `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`. GitHub's workflow token needs `contents: write` and `actions: write`. Workflow publication does not rely on disabled automatic PR creation.

## OCR reading editions

```sh
# Environment supplies MISTRAL_API_KEY; never pass or commit it in source/config.
uv run python scripts/reading_editions.py --workers 4
```

Output: `data/live/readings/{id}.json` and `.md`. Paid page results and the cumulative page ledger remain under ignored `.cache/ocr`. A process lock prevents two workers from racing that ledger; worker requests share a page-rate gate. Mistral reports **processed pages, not verified USD charges**. Interrupted requests retain an explicit unknown-charge page count.

Existing evidence Markdown, citation IDs and criterion quotes remain untouched. Reading quality warnings are public; OCR is not marked human-reviewed. A publisher outage leaves its reading edition pending and the previous source text available.

## Source and review policy

Programme texts retain the actual publisher and recorded source terms. Politrace does not invent a licence or attribute a grant of rights to a user. Official German law text is distinguished from protected editorial material. See [data licensing](DATA_LICENSE.md), [contribution policy](CONTRIBUTING.md), [source coverage](docs/full-coverage.md), and [deployment](docs/deployment.md).

Older scripts/reports are retained to reproduce historic analysis and regressions; they are not the production scheduler. See [production operations](docs/production.md) for recovery and limitations.
