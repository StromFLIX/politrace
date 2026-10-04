# Luna Flex recovery — 2026-10-04

Checkpoint from GitHub run `37222491973`, restored without another paid extraction:

- 232/337 source leaves processed (including explicit abstentions).
- 1,051 source-cited criteria retained; all are unreviewed proposals.
- 171 laws available; the six existing pilot links are unchanged. The all-law pass has **not** completed.
- Cumulative provider-reported charges: **$0.219718** from 138 billed replies.
- Three replies have unknown charges: retain **$0.015493** conservative exposure, not a claim of actual spending.
- The run failed on an error inside an HTTP 200 OpenRouter envelope, not a successful completion and not a confirmed credit shortage. Such transient envelopes now receive bounded retries. Embedded authentication/credit/invalid-parameter errors are not blindly retried.
- Continuation `37227926567` restores the same data/cache/ledger; it does not reset the allowance or discard completed work.

Validation: 147 Python tests, 29 frontend tests, source validation, production build and 32 desktop/mobile browser tests passed locally. In this 1 GiB agent container, use `npm run test:e2e -- --trace=off`: retaining full DOM traces of the programme search can exhaust browser memory. CI retains tracing on its larger runner.

Political outputs are published as proposals pursuant to the operator's explicit main-branch publication instruction. No review or fulfilment status is changed. All other programme full-text imports remain subject to their documented source terms; this recovery does not grant or imply permission to republish them.
