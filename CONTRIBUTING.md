# Contributing to Politrace

Corrections to data are first-class contributions. You do not need to run an LLM to correct a record. Use the **“auf GitHub bearbeiten”** link on a programme, criterion or law page, edit its JSON/Markdown, and open a pull request. Explain the change and link the original sources.

## What belongs where

| Path | Product |
| --- | --- |
| `data/parties.json` | Party metadata, independent of a particular election |
| `data/live/programs/<id>.{json,md}` | Real programme tree, verbatim transcription and source metadata |
| `data/live/criteria/<id>.json` | One measurable commitment and its source citation |
| `data/live/laws/<id>.{json,md}` | Official publication and its transcribed legal text |
| `data/live/impacts/<id>.json` | One law's signed effect on one criterion |
| `data/live/votes/<id>.json` | Separately sourced parliamentary voting results |
| `data/demo/` | **Fictional** examples for UI development; never move them into `live` |
| `data/schemas/` | Generated JSON Schemas; edit `pipeline/models.py`, not these files |

See [data contracts](docs/data-model.md), [methodology](docs/methodology.md) and [source rights](DATA_LICENSE.md).

## Evidence review checklist

1. **Open the original PDF**, not only the extracted Markdown. Check that layout extraction, headings, page numbers and quotations are faithful. Image-only pages require reviewed OCR; do not fill gaps from memory.
2. A criterion must express **one observable commitment**. Its test, quantities, deadline and exceptions must be supported by its quoted programme leaf and section context. No promises inferred from a party's reputation.
3. Keep the source quote verbatim. Markdown line numbers are **1-based and inclusive**. The `page` is the physical PDF page, not a printed page label. A criterion uses its leaf's page and encompassing line range.
4. Check the programme's explicit comparison window. `period_start` cannot precede publication; `period_end` is exclusive. Do not match an old law to a future manifesto.
5. For an impact, read the whole relevant legal provision, scope, commencement clauses, exceptions and any referenced base legislation. Cite an exact substring of a stored law passage and the criterion's source quote. **A shared topic is not a legal effect.**
6. Consider counterevidence. Explain uncertainty and opposing interpretations in `caveats` and the PR. `confidence` is model self-report, not a probability of truth.
7. Review programme extraction, criteria, impacts and fulfilment **separately**. A PR merge publishes records; it does not automatically mark them reviewed. Model proposals cannot self-approve.
8. Never infer a party's vote from a government coalition or the direction of a law. A vote record needs its own official source, motion and date. Do not invent exact counts from a vague report of group positions.

## Review and assessment are different

New AI records have `review.status: "proposed"`. A human may change it to `reviewed` or `rejected`, with their public reviewer identifier, actual review date and an explanatory `note`. Do not claim to have performed a review you did not perform. CODEOWNERS and protected-branch review provide social enforcement; JSON validation alone cannot prove an identity or expertise.

A criterion's `assessment` remains `unassessed` until a human justifies `partial`, `fulfilled` or `contradicted`. Supply a rationale, reviewer, date and `evidence_ids` pointing to **reviewed impact records for this criterion**. The programme and criterion must also be reviewed. A `+2` impact never automatically makes a criterion fulfilled.

When withdrawing a reviewed impact that supports an assessment, revisit that assessment in the same PR; otherwise validation will reject the dangling reviewed evidence. When legal effects reverse, update the overall assessment and cite the relevant evidence, without deleting the older law's historical impact.

## Stable identity and corrections

- Keep record IDs, file names and existing references. Do not renumber criteria when sorting them or editing a title.
- There is one canonical impact per `(law_id, criterion_id)`. Revise it through a PR rather than creating competing duplicate records.
- Prefer `rejected` plus a reason over deleting disputed records. The UI keeps rejected links inspectable, but they do not improve statistics.
- A genuinely new programme edition gets a new ID, even in the same election year. Explicitly choose comparison windows; avoid counting two editions as independent sets of promises unless that is intended.
- Changing Markdown can invalidate page/line spans. Update affected leaves and criterion references together, preserving IDs. Do not edit generated `dist/` files.
- Machine extraction audits live in `program.criteria_extraction`; they document processed leaves and reasons for producing no criteria. Do not remove an audit merely to rerun a model over a reviewed leaf.

## Automated PRs

Pipelines stop before source/model calls if their own data PR is already open. This protects citizen edits on that PR. Review, merge or close it before running that pipeline again. Never auto-merge political assessments.

An automated PR may use `GITHUB_TOKEN`. GitHub generally does not start another `pull_request` workflow for events created with that token. Either configure the optional scoped `DATA_PR_TOKEN`, or have a maintainer run validation on the PR before merging. Do not switch to `pull_request_target` with untrusted PR code and repository secrets.

## Local checks

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
```

If changing models, also run `uv run politrace schemas` and include the generated schemas. CI checks schema drift and builds/smoke-tests the production Compose stack. Browser tests use one headless worker to fit small development containers.

For code contributions, include regression tests and describe any effects on past metrics, record identity or model costs. Never add credentials, personal contact details, downloaded PDFs, LLM caches or generated build output to a PR.
