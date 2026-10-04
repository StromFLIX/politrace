# From the pilot to a complete, deduplicated overview

**Planning baseline: 4 October 2026, data at `02d5ce9`. This is an implementation plan, not a completed backfill or a grant to spend the estimates below.** The programme-reader change accompanying this document does not change source records, model output, assessments or the scheduled paid workload.

## What exists and what does not

| Stage | Verified baseline | Remaining work |
| --- | --- | --- |
| Programme inventory | Six national programmes, 638 PDF pages, seven elected parties; CDU/CSU share a programme | Confirm edition/publication metadata and an appropriate reuse basis for five sources |
| Programme text/tree | Grünen: all 337 source leaves imported | Five further programmes; PDF layout/source QA on all six |
| Criteria extraction | 8/337 Grünen leaves evaluated, 41 proposed criteria | 329 Grünen leaves, then every leaf of the other programmes; semantic completeness QA |
| Semantic deduplication | **Not implemented** | Canonical commitments, multiple source occurrences, explicit equivalence decisions and a non-destructive migration |
| Official laws | 171 BGBl I/II publications in the dated inventory from 2025-03-25; text available for all 171 | Fresh archive reconciliation, effective-date/base-law context and ongoing gap detection |
| Legal matching | 36 candidate pairs across six selected laws; six proposals, three disputed by the challenger | Remaining 165 laws against even the pilot, then re-screen the completed corpus with measured candidate recall |
| Human approval | No approved programme/criterion/impact or fulfilment assessment in the live pilot | Source, atomicity, deduplication and legal review; neither model agreement nor publication substitutes for these |
| Votes | No live records; no automatic adapter | Independent Bundestag/DIP/roll-call enrichment, not inference from law effects |

Sources: `data/sources/bundestag-21.json`, the live programme/extraction records, each law's `matching` audit, and [the pilot's run/cost report](pilots/2026-10-04-gruene.md). Counts are a revision-specific baseline, not a promise that the RSS feed establishes completeness forever.

**“All processed” is not “all promises correctly extracted,” and neither means “all law effects correctly identified.”** Each needs its own coverage and quality measure.

## 1. Finish source coverage without losing provenance

- Preserve the existing Grünen tree, Markdown, IDs, citations and reviewed/editorial fields; do not regenerate a completed source just to run criteria extraction.
- Resolve the remaining five source entries. The current catalogue has a full-text reuse basis only for attributed, noncommercial Grünen text. Public PDF availability alone is not an unrestricted republication licence. Options are documented permission/licensing, or a separately reviewed **quotation-only analysis product** rather than publishing entire texts. The latter needs a new source contract; the present full-text importer cannot simply pretend it has permission.
- Inspect layout defects before trusting downstream results: displaced drop capitals, broken words, columns, headers/footers, tables and cross-page continuations. The current source checks prove quotations match stored Markdown, not that Markdown faithfully reproduces the PDF. Preserve an immutable raw extraction and separately version source-backed corrections.
- Keep a disposition for **every** source leaf: extracted criteria, explained abstention, or pending/error. A heading/footer display collapsed by the reader is not an extraction abstention.
- Publish chapter-sized completed batches with a durable extraction ledger and a declared source/model/prompt fingerprint. The present criteria stage writes its canonical output only when the selected stage completes; cached responses help a retry but are not a visible incremental overview.

**Done for this stage:** all six source entries have an explicit publication mode; every page is accounted for; every leaf has a disposition, including actual errors rather than silently missing work. Source QA and semantic QA remain separately reported.

## 2. Add genuine deduplication, not just stable hashes

Today `extract_criteria` derives the ID from `leaf.id + test`. That prevents an identical local result from being inserted twice, but the same promise in the preamble and a policy chapter gets two IDs. A wording change can also change the generated hash. There is already one impact per `(law_id, criterion_id)`, but that does not deduplicate the underlying commitments.

Add a versioned **commitment-group** product, for example `data/live/commitments/<id>.json`, with its own stable public page/API:

- scope: **party + programme edition + comparison window**;
- canonical, atomic test: action, object, beneficiary/scope, amount/target, deadline, conditions, legal level, and commitment strength (`examine` is not `implement`);
- member criterion IDs and all exact source occurrences, including page/line citations;
- provenance, proposed/reviewed grouping status and reason for every merge/split;
- aliases/supersession links rather than deleted IDs or broken criterion/impact URLs.

Generate candidate duplicates cheaply using normalised exact tests, topic/lexical retrieval and semantic embeddings. Adjudicate equivalence against **both source passages**. Similar wording is only a candidate, not permission to merge.

Keep relation types distinct: `equivalent`, `broader`, `narrower`, `related`, `contradicts`. Do not union a whole connected similarity graph: A≈B and B≈C do not establish that A and C are identical commitments. Every group must have a mutually consistent test and source-backed conditions.

Examples:

- The same rent-cap extension repeated twice in one programme: one commitment, two occurrences.
- Extending the rent cap **and** removing exceptions: two independently testable commitments. The existing pilot notes this unresolved atomicity problem.
- €15 versus €16 minimum wage, different eligible groups, different dates, examination versus implementation: **not duplicates**.
- Similar demands by SPD and Grünen: related cross-party topic/semantic cluster, but separate party-owned commitments and assessments. Never erase political ownership to reduce the denominator.

Expose raw criterion counts, proposed unique-commitment counts and reviewed unique counts separately. Only an explicitly adopted grouping version may change a statistic's denominator; keep the old snapshot reproducible. Legal work may be shared for genuinely equivalent tests, but source applicability and party-specific conditions must still be checked separately.

**Done for this stage:** repeated within-programme promises are represented once in the selected overview, every occurrence/old ID still resolves, differing targets cannot be merged by tests, and uncertain groupings remain visible proposals rather than hidden decisions.

## 3. Screen all laws with a measurable recall strategy

The current matcher uses one full-law BM25 query and keeps at most **six criteria per programme/law**. That bounds expense but can miss the seventh relevant commitment, especially in omnibus laws. Increasing the loop count does not fix this.

1. Split each law into cited provisions/changed sections. Extract references, commencement and applicability separately; retain the original publication and passage IDs.
2. Retrieve with a **union of lexical and semantic candidates**, using both provision → commitment and commitment → provision searches. Deduplicate candidate pairs before model calls. Cache embeddings by exact text/version and legal judgments by the applicable provision/context + canonical test + model/prompt version.
3. Do not use an arbitrary top-six cap as proof of coverage. Tune candidate thresholds/expansion using a cross-topic, cross-party reference sample, inspect random omitted pairs, and report recall uncertainty. Unchecked pairs remain unknown.
4. Resolve relevant **base legislation at the applicable date**, plus conditions/exceptions, before asserting the effect of an amendment. Today's consolidated law is not automatically the right historical version. Unavailable context gets an explicit `missing_context` disposition, not a fabricated negative/positive link.
5. Use the stronger judge for plausible pairs and a separate challenger for supported proposals. Batch bounded tasks and use smaller-model screening only after testing its false-negative rate. Exact quotations, signed effects, conditions and disagreement must all survive validation.
6. Persist pair-level dispositions (`proposed_link`, `no_supported_link`, `missing_context`, `error`) and fingerprints. Today unsupported judgments are mainly a law-level candidate audit plus model cache; we need inspectable, durable negative/abstention records and selective invalidation. A different unrelated criterion or an editorial label should not force every past pair through another paid call.
7. Publish completed bounded batches, plus explicit deferred/error IDs. Freeze an extraction/grouping snapshot before matching its full corpus, so growing the criteria set does not continually invalidate all matching audits.

**Done for this stage:** all 171 laws (and any newly reconciled publications) have been screened against the chosen complete commitment snapshot; every selected pair has a disposition; remaining omissions, missing context and disputes are visible. This is automated coverage, not a claim that no unselected true link exists.

The existing law window is **promulgation from 25 March 2025**, not passage or entry into force. “All laws enacted in the period” needs this date basis kept explicit; distinguishing parliamentary passage and effective dates requires additional source fields. BGBl II includes treaty laws. Ordinances and corrections are not silently included as laws.

## 4. Quality gates before calling it a full overview

- A cross-party/topic reference set checks missed commitments, invented conditions, atomisation and duplicate merges, not just valid JSON/quotes.
- Candidate-retrieval recall is measured **separately** from final-link precision. Include unrelated, contradictory, indirect, temporal and missing-context examples, and inspect omitted pairs.
- A second model may disagree with the first; neither may self-approve a source, grouping or fulfilment assessment. Publish disputed interpretations with their reasons.
- A coverage API/dashboard distinguishes source pages, processed leaves, source occurrences, unique commitments, screened laws, candidate pairs, context gaps, model disagreements and human reviews. Avoid a single green “100%” badge conflating them.
- All record IDs, old citations and citizen corrections survive reruns. The new group API must not silently change the meaning of the existing criterion API or party totals.
- The paid runner has shared per-run/cumulative limits, known/unknown usage accounting, durable checkpoints, and a working publication path. GitHub Actions PR creation was blocked in the verified pilot; the operator's one-off direct publication did not fix the scheduled PR setting. Do not claim automatic daily publication until that path works.

## Cost: measured baseline, not a spending claim

The completed pilot reports:

| Measurement | Actual provider-reported charge |
| --- | ---: |
| Eight source leaves → 41 criteria | $0.140230 |
| 36 law/criterion checks, including the observed challenger calls | $1.187971 |
| Combined import (excluding the separate tiny integration probe) | $1.328201 |

Simple extrapolations:

- Remaining Grünen leaves: `329 × ($0.140230 / 8) = $5.77` **for criteria only**.
- Six programmes: scaling the same leaf density and cost over 638 versus 160 PDF pages gives approximately **$23.55 for criteria extraction**. This is a weak planning estimate, not measured cross-party cost: source structure, promise density and repair rates differ, and outline/OCR/deduplication are excluded.
- Current top-six matcher across all six programmes: `171 × 6 × 6 = 6,156` candidate checks. At the pilot average of `$1.187971 / 36 ≈ $0.033`, that is about **$203 for matching alone**. It assumes enough candidates and the same mix of law sizes, supported links, challenger calls and retries. It **still does not provide exhaustive semantic coverage**.
- An all-pairs run would be much worse. For illustration, 2,000 unique commitments × 171 laws is 342,000 pairs, approximately **$11,286 at that same unoptimised pilot rate**. This is why retrieval and reusable legal context matter; it is not a recommended workload or budget.

These projections are not invoices, current account balances, guaranteed maxima or claims that a particular model is Pareto-optimal. They exclude source acquisition/QA, model evaluation, deduplication, missing-context acquisition and human review. Repeated failed/resumed runs count towards the total. No honest fixed cost for the improved full pipeline is available before measuring it.

**Recommended next paid milestone:** finish the one existing programme, establish/inspect its deduplicated commitments, then screen all 171 laws against that fixed version in capped, checkpointed batches. Measure cost, recall and review burden there before scaling to five more programmes. Do not launch an unrestricted ~$200+ job merely because a small API request succeeds.

## Delivery sequence

1. **Reader improvement:** chapter navigation, source-order prose, search, linked criteria, compact layout furniture and expandable exact-source citations. No model calls or evidence rewrites.
2. **Complete Grünen extraction + grouping:** all remaining leaves, explicit abstentions, atomicity fixes and non-destructive deduplication. This is the smallest meaningful complete-programme milestone.
3. **All-law screening for that programme:** provision-aware retrieval, historical legal context, durable pair results, quality sample and measured cost.
4. **Cross-party expansion:** resolve the five source publication modes, repeat the measured process, expose cross-party clusters without merging party ownership.
5. **Ongoing maintenance:** daily 06:00 Europe/Berlin ingestion, corpus-delta matching, source freshness alarms, working review PRs and independent voting evidence.

Expect several engineering/data-review iterations rather than a single larger retry. Runtime can be scheduled and bounded; publication permissions and human review cannot honestly be promised a fixed completion date. A complete *automated proposal overview* and a complete *human-verified political assessment* are different deliverables.
