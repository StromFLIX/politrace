# Methodology and limits

Politrace connects **a manifesto paragraph → a testable commitment → legal evidence**, with distinct human reviews. It is not a party ranking, a fact-checking oracle or legal advice.

## 1. Preserve the programme

`politrace program` extracts a supplied PDF with PyMuPDF4LLM. The resulting Markdown includes physical PDF page markers. Paragraph leaves keep exact text, an ID, a page and inclusive Markdown line range. Large blocks are split into bounded, verbatim leaves without paraphrasing.

An OpenRouter agent assigns every leaf to a readable section/subsection path, with previous section paths available for continuity. It has no tools and cannot change the paragraph text. The response must include every input leaf exactly once and in input order. The store validator checks tree coverage, duplicate IDs and exact citations. Full Markdown remains the authoritative reading order if the thematic tree groups passages differently.

The website uses the page-complete OCR reading edition as the **only** full-document renderer for both programmes and laws. It shows headings, paragraphs and tables in PDF page order, with search, a page navigator and links to criteria from each programme page. The original extraction tree is an API product, not a second reading view. If an edition is missing, the site shows an explicit pending state and links to the original source; it does not fall back to the retired extraction renderer.

Existing paragraph, source-disclosure and chapter bookmarks resolve to the **same physical PDF page** in the new reader. This preserves citation navigation but does not claim exact word-level alignment between old extraction text and new OCR. Criterion and impact pages retain their exact original quotations, and canonical Markdown, line ranges, IDs and API endpoints remain unchanged. New citation links and default Markdown downloads point to the OCR edition. Raw HTML is escaped, remote images are reduced to alt text and links allow only HTTP(S). Corrections and OCR warnings remain visible; presentation changes do not overwrite evidence.

These guarantees are about the **stored transcription**, not PDF extraction accuracy. Column order, footnotes, tables and headings can still be wrong. Empty/image-only pages block programme generation until reviewed OCR is supplied. A human must compare the original PDF with the transcription before marking the programme reviewed.

## 2. Derive atomic acceptance criteria

Every unprocessed leaf is submitted with its ancestor sections. The model must either produce observable commitments, each with one falsifiable test, or explain an abstention. Rhetoric, status-quo descriptions and unmeasurable aspirations should yield no criteria. Numbers and deadlines cannot be invented.

Each criterion has a stable ID, exact source quote, programme/party/leaf IDs, topic tags, searchable keywords, optional source-backed deadline and independent review metadata. The generator does **not yet deduplicate semantically equivalent commitments across leaves**. The same promise repeated in a preamble and a chapter can therefore produce multiple criteria; current totals must not be advertised as counts of unique political promises. See the [full-coverage and non-destructive grouping plan](full-coverage.md). Absence of a criterion is **not** proof that the paragraph makes no promise; the extraction audit can be challenged through a PR.

## 3. Import enacted publications, not voting guesses

The initial adapter reads the official [Bundesgesetzblatt Teil I RSS feed](https://www.recht.bund.de/rss/feeds/rss_bgbl-1.xml), accepting only entries labelled `Gesetz`. It verifies the official ELI path and obtains that publication's own PDF. IDs use the BGBl year and publication number, including letter suffixes.

The feed is an authoritative source of **promulgation**, not every Bundestag passage, all current German law, or a consolidated legal text. It has a finite look-back window. It does not itself establish commencement dates, Bundesrat decisions, party voting positions or political responsibility. Ordinances and corrections need separate future adapters and are not silently labelled parliamentary laws.

Laws with incomplete text remain visible as `needs_ocr`, with source metadata but no invented passages or matching evidence. Existing records are not silently overwritten when a remote source changes; corrections belong in a PR.

## 4. Retrieve cheaply, then challenge the evidence

1. Restrict candidates to non-rejected criteria and programmes whose explicit comparison windows contain the law's publication date.
2. Use German-stemmed BM25 over titles, tests, programme quotes, keywords and a transparent, curated topic vocabulary. A per-programme cap (default **6**) prevents one large programme consuming the entire candidate budget.
3. Evaluate each retrieved criterion against the legal text. For long laws, rank passages and include neighbours within a bounded context. The model is told whether the context is partial. Missing base legislation, applicability or scope should cause abstention, not an inferred legal effect.
4. Require exact quotations from a supplied law passage and the cited programme quote. Reject structurally invalid or fabricated quotations before publishing an impact.
5. A **second model call** challenges the proposed link, its sign, magnitude and exceptions. The reviewer model can be configured independently. A disagreement is retained as `needs_review`, not hidden. Agreement is not human approval or statistically independent corroboration.
6. All new links remain `proposed`. Only a human can approve an overall fulfilment assessment.

Source text and model output are untrusted data. Models have no tools, shell, network access or repository write access. Their output is strict JSON validated by Pydantic. There are no model instructions embedded in the website runtime.

### What the retrieval audit means

A law records candidate IDs, eligible and omitted counts, a retrieval version, a criteria-corpus digest and an analysis digest. An unchanged rerun skips work. Source, corpus, model or prompt-version changes invalidate the no-match audit; existing canonical impacts are still preserved for human revision. Prompt changes must bump `PROMPT_VERSION`.

`no_candidates` / `no_supported_links` are **search outcomes**, not claims of no political impact. Omitted criteria are unknown. Rejected proposals remain visible but do not count towards evidence coverage. Model responses are cached for repeated calls, not exposed as a public data product.

This POC has unit tests for retrieval and citation safety, **not a measured real-world recall/precision claim**. BM25 can miss synonyms, implicit references, cross-cutting laws and compound German legal terms. Exact quotations prove provenance, not correct interpretation.

Before relying on aggregate results: build a cross-party, expert-adjudicated reference set; measure candidate recall separately from final-link precision; inspect a random sample of omitted pairs; compare a hybrid lexical/embedding retriever; measure disagreement and abstention by topic; and publish versions, costs and error rates. Do not optimise merely for the number of links found.

### Programme-wide Luna Flex experiment

The separately capped [Grünen experiment](experiments-gruene-luna.md) adds proposed equivalence groups without changing raw criterion IDs or the reviewed denominator. Every merge is source-backed and complete-link checked, not a transitive topic cluster. Its all-law candidate search combines whole-law, overlapping provision-window and reverse retrieval; it records per-pair `missing_context`, unsupported and proposed-link outcomes. It remains lexical retrieval with unmeasured recall, not a guarantee of every true link or complete semantic deduplication. Existing six-candidate daily matching is a separate path; its audit must not be confused with the experiment report. The experiment retains its own frozen coverage and cumulative cost.

## Three quantities that must not be conflated

### Signed legal impact (ordinal, per law and criterion)

| Score | Meaning |
| ---: | --- |
| −2 | Directly contradicts the specific criterion |
| −1 | Impedes its implementation |
| 0 | Demonstrably mixed effect, **not missing evidence** |
| +1 | Supports it in part |
| +2 | Directly implements the narrowly stated criterion |

Scores are not additive and are never summed into a party score. `confidence` is uncalibrated model self-report, not a percentage of truth.

### Fulfilment (separate human assessment)

`unassessed`, `partial`, `fulfilled` or `contradicted`. A non-open assessment requires a reviewed programme, reviewed criterion, human reviewer, date, rationale and reviewed impact evidence for that criterion. Humans must consider relevant dates, exceptions and later reversals. A supportive law alone cannot establish the outcome of a broad policy promise.

### Voting (independent evidence)

A vote has its own source, date, motion and group counts (yes/no/abstain/absent). Only reviewed vote records are displayed as voting evidence. Government membership, party affiliations in an impact record and policy direction never substitute for a vote source. Not all parliamentary decisions have a roll-call record; uncertainty stays explicit. Automatic Bundestag/DIP enrichment is not implemented in this iteration.

## Statistics and time

- Denominator: all **non-rejected** criteria for the selected programme(s), including proposed and unassessed criteria. This does not establish coverage of the entire original manifesto.
- Fulfilled / partial / contradicted counts: only criteria with a reviewed programme and reviewed criterion, using the separate human assessment.
- Unknown: denominator minus those three assessed categories. Unknown is not failed.
- Evidence coverage: eligible criteria whose programme and criterion are reviewed and which have at least one reviewed impact, divided by that denominator.
- Zero denominator: percentages are `null` in JSON and “—” in the UI, never a fabricated 0%.

Historical rows compare different programmes and comparison windows at the **current repository revision**. They are not equally difficult baskets of promises, nor a point-in-time time series of a single promise. Earlier assessment states are available in Git history. Constitutional competence, opposition/government roles, budgets, courts and actual implementation are not controlled for in these statistics.

## Review, versioning and data rights

Every canonical record is editable through a PR. A merge publishes a snapshot; review fields remain explicit. There is no automatic merge of political evaluations. Dataset manifests, source PDF hashes, model/prompt provenance, strict schemas and Git commits provide an audit trail. See [contributing](../CONTRIBUTING.md), [data model](data-model.md) and [source rights](../DATA_LICENSE.md).

Demo records are fictional fixtures in a separate namespace and explicitly labelled in the UI/API. They are never evidence about actual parties, laws or votes.
