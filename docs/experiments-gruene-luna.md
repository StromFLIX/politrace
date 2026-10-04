# Grünen × all imported laws: Luna Flex experiment

One user-authorized **$25 cumulative cap**, including tests, rejected replies, retries, review calls and unknown-charge exposure. Prior pilot/source-import spending and independent scheduled jobs are not part of this new experiment. This is automated proposal coverage, not a legal opinion, verified promise denominator or human approval.

## Model/routing contract

Checked against OpenRouter's public [model endpoints](https://openrouter.ai/api/v1/models/openai/gpt-6-luna/endpoints) on 2026-10-04:

- `openai/gpt-6-luna`, provider **`openai/flex`**, advertises $0.05/M input and $0.25/M output tokens, structured output and reasoning parameters.
- Requests use `provider.only: ["openai/flex"]`, `allow_fallbacks: false`, privacy restriction `data_collection: deny`, required parameters, and those price ceilings. No silent normal-price route when Flex is busy/unavailable.
- Medium reasoning; up to 15 minutes per Flex request. Bounded retries, at most four tasks in flight. Actual provider-reported `usage.cost` is counted even when JSON/citations fail validation. A timeout can still be charged: reserve it as unknown, not free.
- Supported law links alone receive a second-model **Claude Sonnet 5.5** challenge. It does not approve anything; disagreements remain visible. Most work stays on Luna; no expensive second call for obvious non-links/abstentions.
- Current catalogue prices are not promised bills, and low prices do not establish semantic quality. Inspect representative generated commitments and proposals before interpreting results.

## Coverage strategy

1. Reuse the existing 337-leaf source tree and eight processed pilot leaves. Process **every remaining leaf**, with explicit criteria or an explained abstention. Checkpoint each validated leaf rather than discard an entire programme on a late failure.
2. Propose strict equivalence only within this party/programme. Retrieve up to six lexical neighbours of each criterion and retain candidate pairs above token Jaccard 0.25, excluding differing written numbers/deadlines. Luna sees both full tests and exact source quotes. A merge requires equivalent action, target, beneficiaries, conditions, amount, deadline, legal level and commitment strength. Every pair in a multi-member group must have a positive equivalence decision: **no transitive similarity unions**. All original criterion IDs, quotes, reviews and impacts survive. This is a conservative proposed grouping, not guaranteed complete deduplication; compound criteria and less lexically similar duplicates still need inspection. It never changes reviewed metrics.
3. Freeze the criterion snapshot, then screen all 171 imported publications. Candidates are the union of whole-law top 12, top two per overlapping 8,000-character provision window (6,000-character stride), and reverse top three laws per criterion. This replaces the old top-six whole-law bottleneck, **not with a claim of exhaustive semantic recall**. Every candidate receives a disposition; omissions remain explicit unknowns. This first version uses lexical retrieval, not unimplemented semantic embeddings.
4. Judge bounded candidate batches against exact law passages and neighbouring layout blocks. Full texts too large for the bounded window are explicitly marked partial. Missing historical base law, applicability or exceptions requires `missing_context`, not fabricated evidence. The pipeline does not pretend to fetch consolidated historical law context.
5. Preserve existing impacts. Add only source-validated proposed impacts, with second-model disagreements. No party votes or overall fulfilment inferred. Existing rejected/reviewed records are not silently rewritten.
6. Publish the audit under `data/live/experiments/gruene-2025.json`, including each selected law, proposed groups, equivalence reasons, every candidate disposition, model fingerprints, omitted counts and cumulative cost. Website: `/live/auswertung/gruene-2025/`; API: `/api/v1/live/experiments/gruene-2025.json`.

“All leaves processed” does not measure missed promises. “All laws screened” does not measure retrieval recall. “Group” does not mean human-confirmed unique commitment. Existing PDF extraction defects remain disclosed. The law window is **BGBl I/II promulgation from 2025-03-25 in the checked 171-law inventory**, not every vote, ordinance or date of entry into force.

## Resume without resetting the budget

`.github/experiments/gruene-luna.json` is the committed request. The `Grünen Luna end-to-end experiment` workflow runs only for changes to that file on main. The initial phase is `criteria`; the `all` phase continues with grouping/matching.

Every attempt retains artifact `gruene-e2e-checkpoint`: canonical source/results, validated LLM cache, cumulative `.cache/e2e/budget.json`, per-law checkpoints and `.cache/e2e/result.json`. To continue, set `resume_run` to the preceding run ID. The workflow downloads that exact artifact. A missing ledger/artifact fails closed before paid calls. Re-running a GitHub job with a fresh $25 allowance is explicitly refused. The ledger is locked for one process and writes reservations **before** requests; interrupted in-flight charges become unknown exposure on restart. The cap cannot be raised by an ordinary retry.

Do not start a new initial experiment with a blank ledger to get around a budget stop. Do not overwrite citizen edits with an older checkpoint: this is a controlled frozen-corpus experiment. Review/reconcile any canonical edits since the artifact before continuing. Source/data corrections should become an explicit new version retaining this snapshot, not invalidate and silently rerun paid work.

The workflow retains artifacts rather than relying on repository PR creation permissions. The operator validates and publishes proposals to main through normal Git as authorized by the user. It never sets `reviewed` or an automatic fulfilment assessment.

## Costs and quality results

Actual results are populated by the run, not the planning estimates. The public report distinguishes `reported_cost_usd`, unknown/in-flight reservations, `budget_exposure_usd`, and `max_usd`. Previously completed work is reused; charges persist across resumes. Before scaling to other parties, inspect missed commitments, atomicity, false duplicate merges, unrelated/missing-context laws and signed-effect disagreements, and measure retrieval recall separately from link precision.
