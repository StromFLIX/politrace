# Data contracts and static API

The source of truth is `data/`, reviewed in Git. `pipeline/models.py` defines strict Pydantic contracts; `uv run politrace schemas` exports JSON Schema. Astro consumes the canonical files at build time and generates HTML, JSON and Markdown. No runtime database or writable API is required.

## Relationship graph

```text
Party ── Program ── Tree / Leaf ── Criterion
                                   │    │
                         Assessment│    │Impact (−2 … +2)
                                   └────┤
                                        Law ── Passage
                                         │
                                         Vote ── GroupVote[]
```

- **Party**: ID, long/short names, colour and website. Adding a party is a metadata PR; it does not require a new schema or UI implementation. Update the optional Actions dropdown as well.
- **Program**: party, election year, original source, publication date, explicit comparison window, Markdown path, immutable-identity leaves, a section tree, extraction audits, review and model provenance.
- **Criterion**: programme/party/leaf IDs, atomic title and description, falsifiable test, tags/keywords, exact reference, optional deadline, review and independent fulfilment assessment.
- **Law**: official publication ID/title/date/citation, source/PDF metadata, transcription status, bounded passages and a machine-owned matching audit. The importer supports promulgated laws from BGBl I and II, with dated archive coverage separate from RSS additions.
- **Impact**: criterion and law IDs, signed ordinal score, uncalibrated confidence, rationale, exact law passage/quote and programme quote, caveats, second-pass verification, review and model provenance.
- **Vote**: law ID, parliamentary motion/date, source, type and group counts, reviewed independently. There is no inference from impacts to votes.

Records other than shared party metadata include `schema_version: "1.0"` and `dataset`. File names equal record IDs. All models reject unknown fields. Schemas describe record shapes; cross-record constraints are enforced by `politrace validate`.

## Namespaces and identity

`data/live/` contains sourced records. `data/demo/` contains fictional test fixtures. Demo IDs always start with `demo-`; live IDs must not. References cannot cross datasets. Parties are shared metadata, not shared policy records.

Imported law IDs are deterministic, e.g. `bgbl-1-2026-285`. Programme IDs default to `<party>-<year>` and may have an explicit edition suffix. Paragraph, section and criterion IDs use content-derived hashes when first created. **After publication, IDs are stable identity, not fields to recompute whenever text is corrected.** Existing records are not overwritten by generators.

A pair of law and criterion has at most one canonical impact record. Revise its rationale/review/score through a PR. Git keeps the historical versions.

## Citation conventions

- Physical PDF pages are 1-based; they may differ from printed page labels.
- Markdown line ranges are 1-based, inclusive at both ends.
- Each page starts with `<!-- page:N -->`.
- `Leaf.text` and `Leaf.reference.quote` are identical and must occur within the cited Markdown range.
- A criterion quote is a substring of its programme leaf. Its page and line range equal that leaf's encompassing range.
- An impact's `law_quote` occurs in its declared law passage; `criterion_quote` occurs in its criterion's source reference.
- `source.sha256` is the downloaded **original PDF** hash, not the Markdown hash. Preserve it as original-ingestion provenance when documenting a later transcription correction.
- A `generation` entry records model, prompt version and a SHA-256 of the request inputs/schema/system policy. It does not include the API key.

## Review and temporal constraints

`proposed`, `reviewed` and `rejected` are editorial states. Reviewed/rejected records require a reviewer and date. Model verification `passed` is not `reviewed`.

The law publication date must be in the programme's `[period_start, period_end)` comparison window. The start must not precede programme publication. Windows are an explicit editorial choice, not inferred from government membership. A proposal about an older period needs an appropriately dated programme/window.

A non-open assessment requires a reviewed programme/criterion and reviewed impact evidence for that criterion. JSON validators cannot establish whether a reviewer is qualified, whether a legal argument is sound, or whether all possible promises were extracted. Those require substantive PR review.

## API v1

Base path: `/api/v1`. Everything is a public, read-only **static snapshot**.

| Endpoint | Response |
| --- | --- |
| `/index.json` | Default dataset, dataset URLs and OpenAPI link |
| `/{dataset}/index.json` | Dataset digest, lightweight collection `counts`, URLs and disclaimers |
| `/{dataset}/{collection}.json` | `{schema_version, dataset, total, items}` |
| `/{dataset}/{collection}/{id}.json` | One canonical record (party detail also includes programme IDs and statistics) |
| `/{dataset}/programs/{id}/tree.json` | Tree, leaves, source/review metadata and Markdown URL |
| `/{dataset}/programs/{id}/source.md` | Extracted programme Markdown |
| `/{dataset}/laws/{id}/source.md` | Law Markdown, only if text is available |
| `/{dataset}/stats.json` | Statistics for each programme/window, with denominator semantics |
| `/{dataset}/search.json` | Searchable criterion text, tags, keywords and detail URLs |
| `/{dataset}/coverage.json` | Dated law inventory, imported/pending IDs and source mode; RSS does not advance full-archive coverage |
| `/sources/bundestag-21.json` | Programme source/rights inventory for the seven elected parties |
| `/sources/laws-bundestag-21.json` | Checked, dated official archive inventory with source-page hashes |
| `/schemas/{collection}.schema.json` | Canonical record contract |
| `/openapi.json` | OpenAPI 3.1 path documentation |

Collections: `parties`, `programs`, `criteria`, `laws`, `impacts`, `votes`. Dataset: `live` or `demo`. `/api/health.json` is the container readiness probe.

Example from the fictional dataset:

```sh
curl http://localhost:8080/api/v1/demo/programs/demo-spd-2025/tree.json
curl http://localhost:8080/api/v1/demo/criteria/demo-spd-2025-ac-001.json
curl http://localhost:8080/api/v1/live/laws.json
```

JSON uses `application/json`; Markdown uses `text/markdown`. Public GETs permit CORS without credentials. Unknown paths are real HTTP 404s, not a successful SPA response. There are no server-side query filters or pagination in v1: download the list/search index and filter client-side. JSON Schemas describe individual records, not collection envelopes.

The law collection is a **bulk data export including every verbatim passage** and can be tens of megabytes after a backfill. Use the dataset index's `counts` for a lightweight inventory and individual record URLs when a full collection download is unnecessary. Normal website navigation serves prebuilt pages, not the bulk collection.

The dataset digest covers the serialized canonical JSON records. Their cited text lives in the records; a source Markdown-only change outside cited leaves is not necessarily reflected in that digest. Use the Git commit and original PDF hashes for full provenance. Snapshots change only after a merge and rebuild/redeployment. Do not treat the API as a live connection to Parliament.
