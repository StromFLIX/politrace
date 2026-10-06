# Bundestag voting evidence

The voting importer is deterministic and independent of the law-effect models. It makes **no model calls** and does not change criterion assessments, impact scores, programme quotations or OCR editions.

## Run and resume

```sh
uv run politrace votes
# A small, explicit scope; other laws and their coverage remain untouched:
uv run politrace votes --law-ids bgbl-1-2026-286
uv run politrace votes --since 2026-01-01 --limit 10
# Recheck official sources, including previously unresolved lookups:
uv run politrace votes --refresh
# Official sources only (skip the optional supplementary JSON check):
uv run politrace votes --no-crosscheck
uv run politrace validate
```

`--since` refers to **law publication**, not the vote date. `--limit` selects newest publications first and must be positive. It does not certify coverage of the remaining laws. Repeating a scoped run against the same snapshots is idempotent. Source errors preserve completed records and write an explicit per-law error before failing the command. A changed/disappeared decision link retains earlier records and raises `source_changed` rather than deleting historical evidence.

The existing daily `production.yml` runs this after law inventory reconciliation. Its existing 06:00 Europe/Berlin schedule is unchanged. Voting failures are reported independently of OCR and paid analysis; validated partial data and public-source caches are retained with the production checkpoint. There is no new paid analysis or spending allowance.

DIP accepts an optional **`DIP_API_KEY` environment secret**. Without one, the client retrieves the Bundestag's published shared public access key from its official API-help document. The help response is never cached; authentication uses the Authorization header, never URL parameters. No key is put in canonical data, diagnostics, build inputs or caches. If the published key is unavailable/expired or access fails, the importer fails explicitly. It does not bypass access restrictions.

Public responses are hash-checked under ignored `.cache/votes`. Settled source snapshots expire after a day; discovery indices and negative API lookups expire after an hour. Cached sources retain their actual retrieval dates. `--refresh` fetches each URL once per run. Official requests are paced; the supplementary API stays below its published 30 requests/minute and honours bounded `Retry-After` delays. Exhausted failures are remembered only within that run to avoid hammering the same unavailable source for every law.

Downloads are bounded and HTTPS-only, with separate allowlists for official sources and `www.abgeordnetenwatch.de/api/v2`. Redirects and interactive browser challenges are not followed or bypassed. Pagination is checked for duplicate/missing identities, stalled cursors and changing totals. XML entities are disabled. Workbook expansion, row and column counts are bounded; formulas are rejected. All source content is untrusted data, never executable instructions.

## Evidence chain

1. Resolve a promulgation to **one DIP legislative procedure** by exact BGBl issue/ELI and publication date. A unique exact-title match without a BGBl entry is provisional, visibly labelled, and excluded from programme comparisons. Procedures explicitly discontinued at the end of a term cannot be the enacted law. Competing live title matches remain ambiguous.
2. Retain Bundestag plenary decisions and their exact DIP position/index, stage, date, document references and printed protocol page. Bundesrat votes, amendments and resolutions do not stand in for the Bundestag's whole-law decision. Earlier/uncertain final versions and mediation cases are not automatically compared with the final promulgated text.
3. For non-named decisions, discover the **official Open Data XML** for the exact term/sitting. Prefer it to the DIP-linked XML, because the two official copies can have different completeness despite identical metadata. If Open Data is unavailable, the explicitly DIP-linked XML is an attributed fallback, never a guessed URL or PDF. Validate term, sitting and date. Read only chair paragraphs in `sitzungsverlauf/tagesordnungspunkt`; TOCs, speeches, interjections and named-ballot rosters are not faction announcements. Keep the agenda/block and a verbatim excerpt of the selected chair text. A decision must be uniquely anchored to the relevant Drucksachen. Second reading, third reading and resolutions remain separate. An immediate “all parts adopted in second reading” summary after a partial decision can carry the bill's reference identity into the final vote, never the parts' voting positions. Only **explicitly named whole factions** receive positions. Unanimity without named factions, coalition names, partial factions, applause, a majority or the preceding reading's positions do not fill gaps. Even “same result as before” remains unexpanded.
4. For a named whole-law decision, join the dated official roll-call entry using **all bill/report references**, rejecting partial-law, amendment and resolution motions. Confirm its complete detail-page heading, motion, date and structured overall/faction chart counts; check embedded JSON too when available. Prefer exact download titles plus **all five counts for every faction**. If official short titles differ, require unique overall totals in the complete day's roll-call index and a unique dated workbook matching every faction subtotal. Collisions remain unresolved. Validate the XLSX term/sitting, one positive ballot identifier, unique members/source rows, exactly one selected choice per row and all subtotals. The identifier comes from the workbook: filename suffixes are not reliable ballot numbers. No ballot-cover PDF is downloaded.
5. Optionally cross-check named final decisions against **abgeordnetenwatch JSON**. Require the same Bundestag term/date/acceptance and an explicitly linked bill in the lead paragraph, not a later background link. Match unique normalized names and historical factions; never fuzzy-match missing names or infer them from current membership. Report matched, partial, mismatched, ambiguous, unmatched, absent and unavailable checks separately. Exact member-level disagreements suspend programme comparisons until resolved. For unchanged official ballots, skipping the check, a supplementary outage or an incomplete new identity match cannot clear an existing disagreement; a complete agreeing check or an editorial correction is required. A supplementary outage does not erase verified official ballots. The third-party JSON never fills missing official votes.

No source match is guessed from government membership, title similarity, impact direction or a party majority.

## Canonical contracts

- `data/live/votes/vote-{law_id}-{dip_position_id}-{decision_index}.json`: stable per-law decision identity, independent editorial state (import defaults to `proposed`, **not invented human review**).
- `type=roll_call`: counted `yes`, `no`, `abstain`, `absent`, `invalid`, plus all named `members` and spreadsheet `source_row` provenance. Identity is local to that official sheet, not a guessed cross-term MP identifier.
- `type=group_record`: explicitly quoted faction positions, **all counts null**, no invented member ballots.
- `type=plenary_record`: the decision is documented, but no faction or member positions have been reliably recovered.
- `evidence.method=bundestag-structured-v2`: DIP procedure/position/index, document references, XML agenda/block and any explicit fallback, extraction status, official workbook index/number/match and optional separately attributed `cross_check`. The DIP printed page is retained as a reference, not a claimed XML page coordinate. Hashes cover original downloaded JSON/XML/HTML/XLSX bytes, not reserialized votes. Legacy `bundestag-dip-v1` evidence remains readable so unavailable sources or citizen corrections are not destroyed; new imports do not parse voting PDFs.
- `compares_to_law`: only a confirmed final whole-law decision linked to the promulgation; not a provisional title match, earlier reading or unresolved later version.
- `import_sha256`: digest of the importer-owned canonical record excluding this field. If a citizen edits any content or changes its review, the importer preserves that file instead of overwriting it. Rejected records stay in the audit and are excluded from public comparisons. Git records revisions of machine-owned sources.
- `data/live/voting/coverage.json`: separate from the publication inventory, with per-law checked date, procedure/vote IDs and `recorded`, `decision_only`, `not_found`, `ambiguous`, `source_error` or `source_changed`. It describes **imported laws**, not all parliamentary business. A missing record is never proof that Parliament did not vote.

Machine imports with fingerprinted official evidence are publishable without an editorial gate. Optional corrections still take priority. Consumer code must distinguish `null` (not counted/unknown) from `0` (known zero).

## Programme comparisons and patterns

The site joins a unique confirmed final whole-law vote with an **accepted Sol-final or editorial law effect**, the owning criterion and its programme. Programme publication and comparison window must precede/include the vote **and** the later promulgation. Rejected criteria/programmes, rejected/missing-context/draft impacts, unrelated parties, unresolved source errors and multiple possible finals are excluded.

| Documented position | Positive law effect | Negative law effect |
| --- | --- | --- |
| Yes | Direction consistent | Potential tension |
| No | Potential tension | Direction consistent |
| Abstention / no valid yes–no position | Neither support nor opposition inferred | Neither support nor opposition inferred |
| Split named ballots | Keep all counts and both directions | Keep all counts and both directions |

A zero effect is mixed/contextual, not agreement or conflict. Unknown is not zero. A mixed faction is **not collapsed to its majority**. Directional alignment is not fulfilment; potential tension is not a proven broken promise or an explanation of motives. Broad bills, competing goals and alternatives require political/legal context.

Pattern denominators are explicit:

- Coverage: all imported laws, including decisions without recoverable positions.
- Faction positions: distinct laws with a unique confirmed final decision and an explicit faction position.
- Programme comparisons: **law × criterion × faction**. Multiple criteria on one law are correlated; these are not independent breaches or a party ranking. There is no percentage-of-promises-broken metric.

Citizen entry points: `/live/abstimmungen/`, individual law/criterion pages, and party pages scoped to the selected programme year. Law pages expose searchable/filterable individual ballots, original protocol quotes, source links, JSON and correction links. Without JavaScript, all published rows and source links remain accessible.

API endpoints (static snapshots, not live parliamentary services):

- `/api/v1/live/votes.json` and `/votes/{id}.json`
- `/api/v1/live/voting-coverage.json`
- `/api/v1/live/voting-summary.json`
- `/api/v1/live/voting-comparisons.json`
- `/api/v1/schemas/votes.schema.json` and `/voting-coverage.schema.json`

The full votes export includes named ballots and preserved excerpts; use per-record endpoints when possible. Technical extraction reasons and failures belong in these records/CI diagnostics, not a citizen-page importer incident report. Regression tests cover XML identity/completeness, speech/TOC/interjection exclusion, stage confusion, shared reports, singular abstention wording, unknown/partial factions, duplicate/formula ballots, tally collisions, filename ambiguity, independently attributed JSON checks, source failures, throttling, credential-free caches, corrections, programme timing and comparison denominators.

Public source documentation: [DIP API](https://dip.bundestag.de/über-dip/hilfe/api#content), [Bundestag Open Data](https://www.bundestag.de/services/opendata), [abgeordnetenwatch API](https://www.abgeordnetenwatch.de/api). DIP identifies proceedings and decisions; it is not an MP-level voting-table API. XML is machine-readable but its chair announcements still require conservative interpretation.
