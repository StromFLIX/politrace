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

## Migration and recovery

`all-party-sol-final-v2` reuses 9,211 retained screening outcomes and the prior spending ledger. Previously proposed links, whether Sonnet agreed or disagreed, go back through Sol; they are **not bulk-approved**. Existing record IDs and correction links are retained. Rejected old impact records remain traceable in Git/API but are not shown as accepted connections.

Each bounded Actions slice settles in-flight charges, persists screening/final/overall results, uploads the checkpoint, validates/publishes data and starts its successor. Failures are isolated by task with bounded retries. Credit exhaustion stops automatic continuation. Cached completed responses are reused. The new $20 allocation is added once to retained exposure during the explicit model transition; retries do not add another allowance. A restore never silently uses a fresh or older ledger.

Operator progress, costs and retry diagnostics are in Actions and the technical API, not a citizen-facing progress page. The site focuses on programmes, criteria, laws, final results and original sources. Methodology is linked rather than repeated as warnings on every card.

## Safety and corrections

Source text is untrusted data. Models have no tools or code execution. Strict schemas, exact citations, temporal eligibility and ID coverage are validated before publication. Quotations prove provenance, not infallible interpretation; corrections remain welcome. Preserve editorial changes and original IDs, and invalidate generated assessments when their underlying evidence changes. Votes need a separately sourced record.
