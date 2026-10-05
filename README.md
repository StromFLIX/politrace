# Politrace

Source-cited German political promises and automated assessments of their connections to published laws.

- **Site:** <https://politrace.stromflix.com>
- **Operations & progress:** [GitHub Actions](https://github.com/StromFLIX/politrace/actions/workflows/production.yml)
- **Versioned API:** <https://politrace.stromflix.com/api/v1/live/index.json>

## Data, not a party ranking

`data/live` contains publisher-attributed programmes, criteria with exact citations, official laws, proposed impacts, independently sourced voting records (where available), OCR reading editions and coverage reports. All six Bundestag programme extractions are published. That does **not** imply all law relationships, semantic extraction, deduplication or human review are complete.

**Sol-final assessments publish and count automatically**, without a human review gate. Luna drafts and rejected/missing-context decisions do not count. Impact, statutory implementation and voting behavior remain separate. Citizen corrections use ordinary Git PRs and explicit editorial overrides take precedence. See [methodology](docs/methodology.md).

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

## Browsing criteria by topic

Party pages and `/live/kriterien/` include a clickable topic overview and numbered pagination (20 criteria per page, with 50/100 options). Search, topic, party, status, page (`seite`) and page size (`pro_seite`) are shareable URL state; browser Back/Forward restores them. Filter and programme-year changes reset the page. Without JavaScript, all eligible criteria remain readable.

Topic progress uses the same accepted assessments and evidence rules as the party totals. It covers the whole selected programme/party, independently of search, status filters and the current page. A criterion with multiple tags appears in every applicable topic, so topic totals are **not additive**. Open criteria are not failed promises. This is a static, client-side browser, not a new paginated API; source records, IDs and citations are unchanged.

## Resumable production processing

`.github/workflows/production.yml` is the single scheduled production entry point. It runs at **06:00 Europe/Berlin**, including DST, and automatically dispatches another bounded slice when work remains. CLI dispatch: `gh workflow run production.yml --ref main`. Do not rerun a paid job from an older snapshot.

1. Restore the newest **results and cumulative charge ledger together**. A paid run with a missing ledger blocks spending rather than resetting costs.
2. Reconcile the official publication inventory. Where archive search is unavailable, use the disclosed dated inventory plus current RSS; do not pretend this proves new full historical coverage.
3. Produce page-complete OCR reading editions with Mistral. Cache individual PDF-page subsets, preserve source hashes, retain headers/footers, flag suspicious transcription, and isolate document failures.
4. Build shared law-passage indexes and retrieve candidates across every temporally applicable programme with independent programme quotas.
5. Luna screens up to 16 candidates per batch. Sol Flex decides up to 12 links per law across parties and separately synthesizes overall criterion assessments. Persist validated results and report heartbeats; resume only pending work.
6. Use bounded backoff for provider failures, isolate repeatedly invalid batches, and stop automatic spending on credit/budget failures. These are errors, not no-link decisions.
7. Upload the full recoverable checkpoint even after failure. Validate and publish the safe partial snapshot to `main`, respecting concurrent changes and branch protection, then explicitly dispatch CI.

Model, route, concurrency, slice duration and cumulative limit are in `.github/production.json`. The routes are **GPT-6 Luna Flex** for screening and **GPT-6 Sol Flex** for final evaluation, both with no standard-price fallback. The inherited ledger includes earlier charges and uncertain reservations. A one-time, explicit $20 additional allocation funds the Sol migration; it is never added again on a retry. The subsequent $10 top-up raises the cumulative ceiling to about $47.84; named `budget_topups` are applied once and preserve every prior charge and reservation ([funding operations](docs/production.md#additional-funding-without-resetting-the-ledger)). Legacy positive links are re-evaluated, not relabelled as approved. New costs are reported by model/stage.

Required Actions secrets: `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`. GitHub's workflow token needs `contents: write` and `actions: write`. Workflow publication does not rely on disabled automatic PR creation.

## OCR reading editions

```sh
# Environment supplies MISTRAL_API_KEY; never pass or commit it in source/config.
uv run python scripts/reading_editions.py --workers 4
```

Output: `data/live/readings/{id}.json` and `.md`. Paid page results and the cumulative page ledger remain under ignored `.cache/ocr`. A process lock prevents two workers from racing that ledger; worker requests share a page-rate gate. Mistral reports **processed pages, not verified USD charges**. Interrupted requests retain an explicit unknown-charge page count.

The OCR edition is the only full-document view for programmes and laws. Search, page navigation and page-level criterion links all use it. Existing paragraph/chapter bookmarks open the same PDF page in the reader; the old tree is no longer rendered. Missing editions show a pending notice and an original-source link rather than falling back to the old layout.

Existing evidence Markdown, citation IDs and criterion/impact quotes remain untouched in their API records and detail pages. Page mapping does not claim word-level alignment between old extraction and new OCR. Reading quality warnings are public; OCR is not marked human-reviewed. A publisher outage leaves its reading edition pending and the evidence available through the API.

## Source and review policy

Programme texts retain the actual publisher and recorded source terms. Politrace does not invent a licence or attribute a grant of rights to a user. Official German law text is distinguished from protected editorial material. See [data licensing](DATA_LICENSE.md), [contribution policy](CONTRIBUTING.md), [source coverage](docs/full-coverage.md), and [deployment](docs/deployment.md).

Older scripts/reports are retained to reproduce historic analysis and regressions; they are not the production scheduler. See [production operations](docs/production.md) for recovery and limitations.
