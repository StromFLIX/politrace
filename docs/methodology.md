# Methodology

Politrace automatically connects programme commitments to enacted legal text. Human approval is **not a publication or scoring gate**. Citizens can correct sources, links and assessments through Git; signed editorial corrections take precedence.

## Sources

Programme and law PDFs have publisher URLs, retrieval dates and SHA-256 fingerprints. The website renders the page-complete OCR reading edition. Original evidence quotes, page/line spans, IDs and Markdown are preserved. A cleaner reading edition does not rewrite previously cited evidence. Statutory publications are not consolidated law or evidence of how a party voted.

Every programme leaf has an extraction audit. Criteria have exact source quotes and a specific test; numbers, deadlines and scope must come from the source. Lexical duplicate candidates are adjudicated for strict equivalence and grouped using complete-link membership. Related or broader/narrower promises are not duplicates; ownership remains separate across parties.

## Production models and decisions

1. A law-first search combines whole-law, overlapping provision windows and reverse BM25 retrieval. Each applicable programme has independent quotas; large programmes do not crowd out smaller ones. Temporal comparison windows are enforced. Unselected pairs remain unknown.
2. **GPT-6 Luna Flex** screens batches of up to 16 candidates, sharing legal context. Unsupported/missing-context outcomes are retained, without a signed effect or claimed absence of all political impact.
3. **GPT-6 Sol Flex** receives up to 12 proposed effects **from the same law, across programmes**, plus exact programme quotes, legal context and date. It makes a final decision: accepted, rejected or missing context. It may correct the direction, magnitude, citation and explanation. There is one public result, not a model-disagreement badge or a vote between models.
4. Accepted decisions require exact quotations in both supplied sources. Structural or quotation errors split into smaller validated batches. **A final decision can only come from Sol**, including retries; it never falls back to Luna. Both models share the same scoring rubric.
5. Sol synthesizes accepted effects for each criterion in chronological order, in batches of up to eight criteria. This creates an automated overall **statutory** assessment. It considers scope, reversals, conditions and dates; it does not add law scores.

Luna and Sol are explicitly pinned to `openai/flex`, with no standard-tier fallback. Endpoint prices checked 2026-10-05: Luna $0.05/$0.25 per million input/output tokens; Sol $1/$5. Actual response usage is accounted before validation, including retries. Missing usage retains conservative reservations. Totals from older runs remain intact; new charges are broken down by model and stage. Mistral OCR charges are separate.

## Score definitions

| Score | Per-law meaning | Overall statutory assessment |
| --- | --- | --- |
| −2 | Directly contradicts the precise criterion | Contradicted |
| −1 | Impedes the criterion | Contradicted/impeded |
| 0 | Demonstrably mixed effect | Mixed |
| +1 | Supports in part | Partially implemented |
| +2 | Directly implements the narrow criterion | Statutorily implemented |
| null | Rejected / insufficient evidence | Open |

Partial support is **not** rejected merely because it does not fulfil a broad promise. Unknown is not zero. Statutory implementation is not necessarily an achieved real-world outcome, and policy direction is not party responsibility or a vote.

## Public metrics

- Denominator: non-rejected criteria in the selected programme(s), including open ones. Labels say criteria, not a verified number of unique promises.
- Accepted Sol evidence requires `evaluation.status=accepted`, the final-model provenance, source validation and no editorial rejection. Raw legacy links and rejected/missing-context decisions are excluded from the citizen UI and scores, not deleted from the audit/API.
- `assessment.method=agent` has final-model provenance, date, source evidence IDs and an input fingerprint, **not an invented human reviewer**. It can automatically count despite `review.status=proposed`, which remains an optional editorial field for API compatibility.
- Implemented / partial / contradicted / mixed counts use the final criterion assessment. Unknown criteria are not treated as failed.
- Coverage counts each criterion with accepted evidence once, regardless of the number of linking laws.
- `fulfilment` is the percentage of the denominator statutorily implemented. `alignment` is the mean signed **criterion** score among scored criteria, not a sum of impacts or a percent fulfilled. The `scored` denominator is explicit.
- Empty denominators produce `null`, not fabricated percentages. Editorial assessments retain their signed review requirements and override generated changes.

## Party dashboard and time series

The programme-scoped party dashboard uses the same final criterion assessments as the public metrics. It separately displays fulfilled, partial, contradicted, mixed and open counts, with links into the criterion filters. Percentages use the complete selected-programme denominator; a positive share smaller than 0.1% is labelled `<0,1 %`, not rounded to zero.

Law counts deduplicate law IDs, not impacts. Supporting and opposing groups mean at least one positive or negative accepted impact respectively. Mixed laws have a zero-score impact or both positive and negative impacts on different criteria. These groups intentionally overlap. Topic groups also overlap because a criterion may carry several tags. Neither law counts nor signed effects imply responsibility or votes.

The timeline is **evidence coverage reconstructed from today's accepted evidence by law publication month**, not historical fulfilment or the date the model discovered a link. Each criterion enters the covered set once; the opposing set is the subset with at least one negative accepted impact up to that publication date, even if later legislation counteracts it. Months without new evidence retain the previous value. The chart ends at the latest non-rejected law in the selected comparison windows, not an invented current date. Empty evidence has an explicit empty state. No current criterion assessment is backdated to its first law, and no fulfilment time series is fabricated from the current snapshot.

Law highlights default to reach (distinct affected criteria), not claimed political importance. Their coverage contribution is the number of criteria whose first accepted evidence is exclusively from that law, divided by all selected criteria, in percentage points. If two laws first support evidence for the same criterion on the same publication date, this is a **shared first-evidence** count for both, not exclusive credit to either. The timeline counts the union once. Signed law scores are never added into a progress percentage. Programme comparison rows compare different commitments, not past assessment snapshots.

The party JSON export includes the same per-election-year dashboard aggregates, topic counts, law evidence references and monthly values, with an explicit `timeline_basis` and `fulfilment_history_available: false`. Existing rounded `statistics` fields remain compatible; precise dashboard percentages are separate fields. This is a build-time derivation only: no source records, evidence IDs, assessments, reviews or paid-model processing are changed.

## Voting behaviour and programme tensions

Votes have independent official evidence: DIP publication links and decisions, plenary protocols for explicitly named faction positions, and official spreadsheets for named individual ballots. Missing counts remain null; earlier readings, coalition membership and a law's effect cannot fill them in. Machine-sourced evidence is publishable without pretending that an editor reviewed it. Ambiguities and source errors remain visible in per-law coverage.

Only a unique confirmed final whole-law vote can be compared with an accepted Sol-final or editorial law effect. The programme must have existed and been eligible at the vote date as well as promulgation. Yes on a negative effect or no on a positive effect is a **potential tension**, not proof of a broken promise; compatible direction is not fulfilment. Mixed law effects, abstentions, absences and invalid ballots do not establish opposition. Split factions retain their actual ballots, not a majority label.

Patterns count distinct evidenced laws; programme comparisons count law × criterion × faction. Several criteria can concern one law and are not independent cases. No party ranking or promises-broken percentage is computed. Source coverage is the imported law corpus, not all Bundestag business. See [the voting evidence specification](voting.md) for exact matching, exclusions, provenance, API and correction behaviour.

## Migration and recovery

`all-party-sol-final-v2` reuses 9,211 retained screening outcomes and the prior spending ledger. Previously proposed links, whether Sonnet agreed or disagreed, go back through Sol; they are **not bulk-approved**. Existing record IDs and correction links are retained. Rejected old impact records remain traceable in Git/API but are not shown as accepted connections.

Each bounded Actions slice settles in-flight charges, persists screening/final/overall results, uploads the checkpoint, validates/publishes data and starts its successor. Failures are isolated by task with bounded retries. Credit exhaustion stops automatic continuation. Cached completed responses are reused. The new $20 allocation is added once to retained exposure during the explicit model transition; retries do not add another allowance. A restore never silently uses a fresh or older ledger.

Operator progress, costs and retry diagnostics are in Actions and the technical API, not a citizen-facing progress page. The site focuses on programmes, criteria, laws, final results and original sources. Methodology is linked rather than repeated as warnings on every card.

## Safety and corrections

Source text is untrusted data. Models have no tools or code execution. Strict schemas, exact citations, temporal eligibility and ID coverage are validated before publication. Quotations prove provenance, not infallible interpretation; corrections remain welcome. Preserve editorial changes and original IDs, and invalidate generated assessments when their underlying evidence changes. Votes need a separately sourced record.
