# Retained programme and law-analysis results — 2026-10-05

Recovered from GitHub Actions artifacts, not regenerated or hand-authored:

- Five programme imports: [37231988025](https://github.com/StromFLIX/politrace/actions/runs/37231988025), **completed**.
- Grünen cumulative experiment: [37234594141](https://github.com/StromFLIX/politrace/actions/runs/37234594141), **failed after retained progress**.

| Programme | Processed / source leaves | Source-cited criteria | Latest retained reported cost (USD) |
| --- | ---: | ---: | ---: |
| Grüne | 337 / 337 | 1,640 | 6.408905 |
| CDU/CSU | 1,060 / 1,060 | 965 | 0.180367 |
| SPD | 708 / 708 | 787 | 0.138763 |
| AfD | 1,154 / 1,154 | 683 | 0.164713 |
| Die Linke | 841 / 841 | 1,384 | 0.197706 |
| SSW | 1,134 / 1,134 | 1,011 | 0.175284 |
| **Total** | **5,234 / 5,234** | **6,470** | **7.265738** |

Grünen's cost includes extraction, grouping, matching and second-model challenges from this cumulative experiment, not just the latest attempt. The five other programme totals are extraction/source preparation only. Earlier independent POC/model-comparison spending is excluded. The Grünen ledger also retains **$0.061199 of unknown-charge reservations** across 15 calls; no pending calls remain in this saved artifact. The five programme ledgers report no uncertain charges. These values are provider reports, not a reconciled account invoice.

The published Grünen audit contains **70 of 171 laws**; 101 remain pending. **138 total proposed connections** were saved (including preserved previous proposals). There are **1,639 proposed groups**, not a verified unique-promise denominator. No other party's law matching or deduplication is claimed. Every source leaf has either criteria or an explicit abstention; this is not evidence that the model found every promise or that PDF transcription is perfect.

## Recovery and continued execution

Recovery compared existing records before copying: published programme/criterion/source/impact records were unchanged; existing law metadata changed only in `matching`; the audit extended existing law results and its cost snapshot. Only each additional programme's own files were copied from its isolated artifact. No review or assessment status was promoted. Source attribution and actual terms remain unchanged.

The failed analysis returned `finish_reason=error` and later an HTTP 200 error envelope with code 502. The next implementation treats both as bounded provider retries, not malformed model JSON that poisons the subdivision cache. Transport timeouts remain conservatively reserved. Exhausted transient errors defer that law while unaffected laws continue, followed by one bounded retry pass. Persistent errors still fail the run and remain pending; they are never recorded as no-impact findings. Credit/auth/configuration and budget errors stop paid work.

The continuation points to the retained ledger from 37234594141. The dollar ceiling remains **$25 cumulative**, including rejected outputs, fallbacks and uncertain exposure. The secondary call-count ceiling increases from 2,000 to 10,000 so cheap Flex batches do not hit an unrelated low request ceiling; this cannot reset or bypass the monetary cap. Existing completed law audits, validated responses, criterion IDs, grouping and cost records are reused.

## Larger-corpus presentation

The full corpus exposed mobile horizontal overflow in long legal text and excessive browser/build memory use. Programme chapters and law PDF pages now open selectively (all text stays in HTML, source fragments reveal it, search and print retain access). API bulk lists are serialized record-by-record with unchanged JSON values. Browser checks use a lightweight static test server; Docker CI separately tests production nginx. Chromium's back/forward DOM cache is disabled only in tests to keep repeated multi-megabyte document navigation within the 1 GB test container.
