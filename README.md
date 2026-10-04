# Politrace

**Vom Wahlversprechen zum nachvollziehbaren Gesetzesbeleg.**

An evidence-first proof of concept for German election manifestos: preserve each programme as a readable tree, derive individually testable acceptance criteria, and propose source-backed links to enacted legislation. Citizens can correct every data product through pull requests.

**A legal impact, fulfilment of a promise, and a party's vote are separate records. AI suggestions never automatically become verified fulfilment.**

## First iteration

- **Party view**: programme tree, searchable criteria, evidence coverage, separate fulfilment statistics, previous programme periods and direct source/API/edit links.
- **Programme reader**: chapter navigation, readable Markdown in source order, programme search, a criterion-bearing-paragraph filter and expandable exact-source/page citations. Works without JavaScript for reading; untrusted HTML and remote images are not rendered.
- **Activity view**: official law publications, signed criterion impacts on a −2…+2 scale, and independently sourced voting tables when data exists.
- **Open data**: versioned static JSON/Markdown API, schemas, programme trees, criteria search index and programme-level statistics.
- **Python pipeline**: PDF → page/line-anchored Markdown → agent-structured tree → atomic criteria. Paginated official BGBl I/II archive (plus RSS CLI) → German-stemmed BM25 candidate retrieval → two-pass legal assessment, with exact-quote validation, review states, caching and bounded budgets.
- **GitHub Actions**: one-click programme import, separate criteria extraction and law/evidence updates; data is proposed through PRs, never auto-merged. Existing open review branches are preserved.
- **Deployment**: one `docker-compose.yml`, serving prebuilt HTML/API files through unprivileged Nginx. No database, runtime model calls or runtime API keys.

Design previews (**fictional demo data**): [overview](docs/screenshots/overview.png) · [party detail](docs/screenshots/party.png) · [activity](docs/screenshots/activity.png).

Programme reader (**real, unreviewed Grünen transcription**): [desktop](docs/screenshots/programme-reader-desktop.png) · [desktop chapter](docs/screenshots/programme-chapter-desktop.png) · [mobile](docs/screenshots/programme-reader-mobile.png) · [mobile chapter](docs/screenshots/programme-chapter-mobile.png). Screenshots preserve known PDF extraction defects; this reader redesign is not a source correction.

### What is real, and what is not?

`data/live/` contains **171 official BGBl I/II laws**, the complete **Grünen 2025 programme transcription/tree**, **41 proposed criteria** and **6 proposed law links** from the first real end-to-end pilot. Only **8 of 337 source leaves** and **6 selected laws / 36 candidate pairs** were evaluated in that pilot; this is not full manifesto or cross-party coverage. Three links passed a second-model challenge and three retain explicit model disagreements. **No criterion has a human-reviewed fulfilment assessment, and no live votes have been imported.** See the [pilot result, actual cost and open quality findings](docs/pilots/2026-10-04-gruene.md).

An OpenRouter key is needed for further model stages. The real pilot demonstrates an operating extraction/matching path, not measured legal accuracy; automated tests and exact quotations do not prove that a model's interpretation is correct.

**Semantic deduplication is not implemented yet.** Stable per-leaf IDs and unique law/criterion pairs are not unique political commitments. See the [full-coverage plan, deduplication design and pilot-based cost estimates](docs/full-coverage.md) before increasing the paid backfill scope.

`data/demo/` contains **fictional** programmes, criteria, laws, votes and assessments for seven party views, including an older sample programme period. The UI and API label this namespace explicitly. These examples are not claims about actual party policy or parliamentary decisions.

The landing page chooses `live` after a live programme is imported; otherwise it shows the labelled demo. Both namespaces always remain accessible. Build with `POLITRACE_DATASET=live` or `demo` to choose explicitly.

## Run locally

Requirements: Node **22.12+** (Node 24 also supported), Python **3.12+**, [uv](https://docs.astral.sh/uv/). No key is needed to view or test the website.

```sh
npm ci
uv sync --frozen
uv run politrace validate
npm run dev
```

Open <http://localhost:4321>. Useful routes:

- `/demo/parteien/` — fully populated, clearly fictional product tour
- `/demo/parteien/spd/` — criteria, programme links and earlier sample period
- `/demo/aktivitaet/` — impact/vote UI demonstration
- `/live/aktivitaet/` — real sourced publications
- `/live/programme/gruene-2025/` — source-order programme reader, search and exact citations
- `/daten/` — API documentation
- `/quellen/` — 21st-Bundestag source inventory, archive coverage and explicit rights/import gaps
- `/methodik/` — evidence and scoring rules

## Run the complete production stack

```sh
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d --wait
```

Open <http://localhost:8080>. Health probe: `/api/health.json`.

The optional local override publishes a loopback port; production Compose publishes none. `PORT` changes the local host port. The application listens on container port **8080**; configure the Coolify proxy for that port. `POLITRACE_DATASET` is a **build-time** selection, so changing it requires a rebuild. No volumes or database migrations are needed. The image contains a snapshot: newly merged data appears only after rebuilding/redeploying.

**Do not put `OPENROUTER_API_KEY` in this stack.** See [Coolify deployment](docs/deployment.md) for the existing-domain cutover and smoke checks.

## Add your OpenRouter key and run

1. Add repository Actions secret **`OPENROUTER_API_KEY`**.
2. Enable Actions' permission to create PRs in the repository settings.
3. Run **Propose a manifesto tree**, providing the actual PDF/source, party, year, publication date, comparison window and public full-text reuse basis.
4. Review and merge the generated tree PR, then run **Propose criteria for an imported manifesto**.
5. Run **Propose new laws & evidence**. Review proposed links before counting any as human-reviewed evidence.

See [pipeline setup, budgets and retry behaviour](docs/pipelines.md), including the optional `DATA_PR_TOKEN` needed if bot-created PRs should automatically trigger further CI. The law feed itself needs no API key. No secret is stored in the repo, Docker image or frontend.

**The law pipeline runs daily at 06:00 Europe/Berlin**, including seasonal clock changes. Manual actions remain available. Data proposals wait for review; the scheduler never auto-merges political assessments.

## Historical backfill

**Backfill the 21st Bundestag** imports the official law archive from **2025-03-25** and proposes licence-cleared programme trees/criteria in separate draft PRs. It can be manually dispatched or started by a committed `.github/backfills/bundestag-21.json` request on `main`. A separate integration step verifies production and the OpenRouter secret without exposing it.

The archive search returns HTTP 403 from GitHub runners; official RSS and law PDFs remain accessible. A [dated, count-reconciled inventory](data/sources/laws-bundestag-21.json) allows the historical job to import those official records. Both RSS feeds support daily additions, but **do not extend the verified full-archive coverage date**. Fallback mode and this limitation are public; refresh the inventory from a network that can reach the search when needed.

The checked source inventory covers **CDU/CSU, SPD, Grüne, AfD, Linke and SSW**. That is six programmes for seven parties, not six completed imports. Five sources still need a documented public full-transcription reuse basis. The Grünen text has a noncommercial CC BY-NC 3.0 DE licence, excluding artwork. See [source inventory](data/sources/bundestag-21.json), [pipeline details](docs/pipelines.md) and the website's `/quellen/` page. Unknown data and unreviewed AI proposals never become fulfilment scores.

## API examples

```text
GET /api/v1/index.json
GET /api/v1/live/laws.json
GET /api/v1/live/criteria.json
GET /api/v1/live/impacts.json
GET /api/v1/live/programs/gruene-2025/tree.json
GET /api/v1/live/extraction.json
GET /api/v1/demo/programs/demo-spd-2025/tree.json
GET /api/v1/demo/programs/demo-spd-2025/source.md
GET /api/v1/demo/criteria/demo-spd-2025-ac-001.json
GET /api/v1/live/stats.json
GET /api/v1/live/coverage.json
GET /api/v1/sources/bundestag-21.json
GET /api/v1/sources/laws-bundestag-21.json
GET /api/v1/openapi.json
```

List responses have `{schema_version, dataset, total, items}`. There are no server-side query filters: use the list/search index client-side. Writes are PRs. See [data model and API](docs/data-model.md).

## Verification

```sh
uv run politrace validate
uv run politrace schemas
uv run ruff check .
uv run pytest
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

CI also checks schema drift and builds/smoke-tests Docker Compose, including API responses and genuine 404s. Tests cover graph integrity, temporal eligibility, exact citations, human-review gates, retry budgets, source URL protections, idempotence, search/filter/deep-link navigation and desktop/mobile rendering. Model correctness still needs a labelled real-world evaluation set and human legal review.

## Repository map

```text
data/                 Canonical live/demo records and JSON Schemas
pipeline/             PDF, OpenRouter, retrieval, law feed and validators
scripts/              Safe Actions entry point and fictional fixture seed
src/                  Astro pages, components, styles and static API export
tests/                Python, TypeScript and Playwright tests
.github/workflows/    CI and PR-producing data pipelines
deploy/nginx.conf     Static serving, headers and health endpoint
```

## Important limits before public launch

- Retrieval is lexical and can miss relevant commitments. Missing evidence is unknown, not failure. Scores are ordinal, not summed or presented as a party ranking.
- BGBl records describe promulgation, not every parliamentary vote. The historical archive covers I/II laws by publication date and records any remaining IDs. No automatic DIP/roll-call enrichment or consolidated-law resolver is implemented yet.
- History compares programme periods at the current data revision; earlier assessment states live in Git, not a point-in-time chart.
- Programme republication rights and PDF-tool licensing need attention. See [data/source rights](DATA_LICENSE.md).
- The operator must supply accurate legal/contact/hosting information before a public production launch; the privacy page explicitly marks these pilot limitations.

[Contribute or correct evidence](CONTRIBUTING.md) · [Methodology](docs/methodology.md) · [Pipeline guide](docs/pipelines.md) · [Deployment](docs/deployment.md)
