# Model-selection evidence — 4 October 2026

## Decision, not a claim of Pareto optimality

The initial `gpt-4.1-mini` default was not task-benchmarked. The first retry uses **Claude Sonnet 5.5** as a **fast, quality-first baseline**, not as a demonstrated cost/accuracy optimum. GPT-5.6 Sol is configured for second-pass legal challenges; **that legal role has not yet been empirically evaluated**. A more expensive model or a second model is not a substitute for source checks or human review.

All current model IDs and catalog prices were checked against OpenRouter's live model/endpoint catalogs. The baseline costs $2/M input and $10/M output tokens at standard rates; GPT-5.6 Luna lists $0.20/M input and $1.20/M output. Catalog prices alone do not describe effective cost after output length, failed attempts, routing and retries.

## Small source-backed screen

Six deliberately selected paragraphs from the inspected, attributed noncommercial-use Grünen 2025 programme were evaluated through the **actual criterion-extraction pipeline**, with identical prompts and neighbouring source context. They include a table of contents, rhetoric, a status-quo description, minimum-wage commitments, traffic rules and the Deutschlandfonds. Expected checks are not sent to the model.

| Model | Provider-reported USD, including failed outputs/retries | Requests | Elapsed seconds | Proposed criteria | Mechanical checks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Claude Sonnet 5.5 | 0.043794 | 1 | 18.01 | 11 | 22/22 |
| GPT-5.6 Luna | 0.016451 | 7 | 125.39 | 17 | 21/22 |
| Gemini 3.8 Flash | **Unknown** | 1 in each attempt | No usable result | — | HTTP 400 / invalid parameters |

The two successful runs have complete cost accounting; their unused reservations were released. Flash's responses did not supply `usage.cost`, so the client retained unknown-cost reservations. **The `0` reported-cost field for an unaccounted request does not mean a free request.** Do not treat a transport/provider-parameter failure as an intelligence score.

Results:
- [Sonnet baseline and failed Flash request](2026-10-04-sample-v2.json), [Actions run](https://github.com/StromFLIX/politrace/actions/runs/37207939481).
- [Luna comparison and Flash diagnostics](2026-10-04-lower-cost-sample-v2.json), [Actions run](https://github.com/StromFLIX/politrace/actions/runs/37208119539).
- Both successful outputs passed exact PDF/Markdown citation and graph validation and abstained on the three negative-control paragraphs.
- Inspection of the earlier sample exposed combined independent commitments, an omitted examination promise, and an invented measurable interpretation of an undefined “European level.” Prompts/checks were tightened before these version-2 comparisons; the earlier Sonnet call cost another $0.042580.

## What the numbers do and do not mean

**Assistant inspection, not expert or human approval:** Luna retained more granular proposed uses of the infrastructure fund. Sonnet was faster and used fewer requests, but its two fund criteria do not capture all the finer-grained uses Luna extracted. Luna's minimum-wage eligibility test still couples eligibility to the amount, which the screen flags. Its “more than 90%” contract-coverage test also needs contextual review: a source description must not become an invented independent legal threshold.

The checklist uses regexes for selected concepts. A wording mismatch can fail a sound interpretation, and keyword presence can pass a weak one. **22/22 is not 100% accuracy, and 17 criteria is not automatically better than 11.** No full precision/recall ground truth, balanced all-party sample, repeated-run stability estimate or legal-impact evaluation exists yet. Neither successful model has been shown to dominate the other across cost, correctness, recall and latency.

For the requested fast first results, retain Sonnet for this bounded backfill. Keep Luna as a cheaper candidate for a broader, separately annotated evaluation and simple structural stages. Do not automatically promote either model based on this screen. The long-term selection criterion is cost per **correct, source-supported** extraction/link, including review burden and retries—not token price or a general intelligence ranking.

Run **Compare source-backed extraction models** manually to reproduce. Models are selected through the checked `.github/backfills/model-evaluation.json`; each model has a $0.50 exposure cap. Results are evaluation artifacts, not canonical political annotations, and no record here is marked reviewed or fulfilled. See [pipeline accounting](../pipelines.md#safety-cost-and-resumability) and [data reuse terms](../../DATA_LICENSE.md).
