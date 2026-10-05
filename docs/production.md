# Production operations

## One durable data queue

`production.yml` runs daily at 06:00 Europe/Berlin and self-dispatches bounded continuations. This is a repository GitHub Action, not a chat/orchestration workflow. `.github/production.json` owns its model, price-route, concurrency, inherited cumulative budget and maximum slices.

- Monitor: `gh run list --workflow production.yml` / `gh run view RUN --log`.
- Start a new safe continuation: `gh workflow run production.yml --ref main`.
- Do **not** use GitHub's rerun button after paid work. A new invocation discovers the newest charge checkpoint; a rerun could restore stale costs and is rejected.
- Restore **data + validated response cache + cumulative ledger** together. Missing/expired checkpoints after a paid step are concrete blockers, never a reason to start a fresh ledger.
- `production-checkpoint` artifacts retain `data/live`, `.cache/production` and OCR page/usage caches for 90 days. Back up long-lived ledgers externally if the project is inactive beyond artifact retention. Never include keys, original PDFs, image-base64 responses or provider error bodies.
- The one-time migration cancels the configured legacy runner using the workflow's Actions token, waits for its final checkpoint, and preserves prior spending/reservations. Repository App tokens used by an operator may not have Actions cancellation permission.

## Work units and failure behavior

The corpus is retrieved law-first across all temporally applicable programmes with independent programme quotas. A law passage index is shared; OCR can improve search terms but the original source passages remain judgment evidence. Luna Flex screens 16 candidates per work unit. Sol Flex then decides 12 proposed effects per shared-law batch, across parties, and separately synthesizes eight criteria per overall-assessment batch. Content-sensitive IDs and cached responses prevent repeat spending. Legacy negative/context outcomes are reused; every legacy positive goes through Sol, regardless of Sonnet's old objection. Criterion changes invalidate corresponding pair signatures.

Each validated batch is saved immediately. A 45-second heartbeat logs queue/cost progress while requests wait. The default slice accepts new calls for fifteen minutes, then lets in-flight requests settle (up to the provider timeout); no fallback or retry can begin past that boundary. A time boundary does not consume an item's failure allowance. Citizen results update after validated snapshots deploy. Heartbeats, costs and diagnostic errors stay in Actions/artifacts and the technical API; there is no public progress page.

The explicit Sonnet-to-Sol ledger migration retains all prior charges/reservations and adds the newly authorized $20 once to retained exposure. A `budget-before-sol.json` copy and migration entry document the change. Resumption does not add another $20. New spending is broken down by model/stage, including paid invalid responses and retries. Credit checks compare funds with **remaining** allowance, not historical spending already paid for.

Provider/validation failures have bounded retries and batch-level deferral; persistent errors remain visible. A quarantined batch does not stop unrelated laws or programmes. Once only exhausted items remain, the run explicitly needs attention. Credit errors stop automatic spending. Source-sensitive signatures invalidate stale audits after editorial changes; new zero-candidate laws still update coverage. The maximum slice count bounds continuations of the same corpus, not all future daily imports. Completed pairs can legitimately be no-supported-link or missing-context decisions; neither means the programme was fulfilled.

Deduplication stays within programme ownership and preserves every criterion/source ID. Singleton fallback groups are marked pending, not falsely labelled fully deduplicated. Large programmes cannot consume smaller programmes' retrieval allowance. Omitted candidates remain **unknown**, not disproven.

## OCR and local acceptance testing

`reading_editions.py` uses SHA-pinned original PDFs, bounded 16-page uploads, per-page caches, bounded concurrency, a shared approximately 120-pages/minute gate, six-attempt backoff and an exclusive cumulative-ledger lock. The page cap counts requests, including retries. It does not assert an invoice in USD.

Local live-service acceptance tests covered Grünen pages 11, 12 and 27, and both pages of BGBl I 2025 Nr. 173; the real batch then reused these cached pages. Law samples retained full native-word coverage; programme samples were approximately 0.85–0.87. Coverage is a warning heuristic, **not a correctness metric**.

A duplicated word fragment at a programme column boundary was checked against the rendered original PDF. `reading_quality.py` records that exact reversible correction, its source page and the original OCR-text hash. It also flags repeated header/footer hallucinations. Other suspicious pages remain visibly unreviewed; source evidence is not rewritten. Source outages leave a reading edition pending, not silently replaced by a different document. `data/sources/document-mirrors.json` allows attributed mirrors only for an exactly matching PDF SHA-256. AfD's 28 February 2025 Internet Archive capture is byte-for-byte identical to the recorded 177-page original; readers link to that available copy and retain the publisher address.

The local backfill now covers all six programmes and 171 laws. The table acceptance check caught 384 pages whose Mistral output linked to separate Markdown table payloads. The parser now expands those payloads in place, preserves them in each page record, and rejects missing, duplicate or unplaced table content. Only those pages were reprocessed; each repaired edition records its prior Markdown digest. Original citation text and IDs were not changed. Unknown provider metadata (such as word confidence arrays) is not passed through into public records.

## Publication and source limits

Safe partial records are validated, browser-tested and published to `main`. The publisher fetches/rebases rather than force-pushing; citizen corrections and reviewed objects are retained. A conflict or branch-protection rejection stops publication and retains the artifact. `GITHUB_TOKEN` pushes do not trigger push workflows, so CI is explicitly dispatched afterward. Coolify's installed GitHub App receives the push and rebuilds the production Compose application automatically. CI then waits for the exact public API/OCR/methodology/reader snapshot and runs the browser suite against HTTPS. A green publisher alone is not proof of deployment; see [deployment.md](deployment.md).

Restoring a checkpoint can advance an effect before its overall assessment is rebuilt. Stale machine-generated criterion scores are invalidated after merging; editorial corrections are not. Rejected citizen-corrected evidence cannot be resurrected by a saved automatic assessment.

Historical coverage is still constrained by the disclosed dated official inventory when archive search is blocked. RSS does not establish a complete new historical end date. Full programme leaf processing does not establish semantic completeness. There is no invented voting-data backfill or automatic human approval.

Operational hardening does not supply missing legal operator details. The privacy page still identifies the need for the actual operator/contact, hosting retention information and an imprint; do not invent these or grant rights to third-party material on a user's behalf.
