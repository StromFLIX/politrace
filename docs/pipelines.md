# Running the data pipelines

Python performs the expensive/offline work. The website only serves a built snapshot. **Do not put an OpenRouter key in Coolify, the frontend, a Docker build argument, a PR, or a committed `.env` file.**

## GitHub setup

1. In **Settings → Secrets and variables → Actions**, add repository secret **`OPENROUTER_API_KEY`**. This is the one key needed for the AI stages. It is not needed for the public law feed or website.
2. In **Settings → Actions → General → Workflow permissions**, allow Actions to create pull requests. Repository/organisation policy may also need to permit write permissions; the workflows explicitly request `contents: write` and `pull-requests: write`.
3. Optional repository **variables**:

   | Variable | Default | Meaning |
   | --- | --- | --- |
   | `OPENROUTER_MODEL` | `openai/gpt-4.1-mini` | Outline, criteria and initial legal judge |
   | `OPENROUTER_REVIEW_MODEL` | `openai/gpt-4.1-mini` | Second-pass legal challenger |
   | `POLITRACE_MAX_USD` | `5` | Manifesto action's maximum per-run reserved cost |
   | `POLITRACE_MAX_CALLS` | `200` | Maximum uncached model attempts, including retries (1–2000) |

   Law and standalone-criteria actions also expose a per-run USD budget input. Max supported budget is $100. Start small, check the run summary, then expand deliberately.

4. Optional secret **`DATA_PR_TOKEN`**: a repository-scoped token with Contents and Pull requests read/write. If absent, workflows use `GITHUB_TOKEN`. GitHub normally suppresses new workflow runs triggered by `GITHUB_TOKEN` events, so a generated PR may not automatically receive CI checks. The generation job validates the data and runs Python tests, but this is not a replacement for full UI/Compose CI. With the default token, a maintainer must validate the proposed branch before merging. Do not weaken required checks or use unsafe `pull_request_target` execution to work around this.
5. Recommended branch rules: protect `main`, require CI, require a human PR review, and require review of data/schema/workflow changes. CODEOWNERS does not enable branch protection by itself. Never auto-merge political evaluations.

The action dependencies are pinned to commits. Paid work runs via `workflow_dispatch` on `main` or the daily default-branch schedule. PR CI has no OpenRouter secret and read-only repository permissions. Workflow inputs are passed as environment values into Python, not interpolated into executable shell commands.

## 1. Programme PDF → Markdown and tree

Run **Actions → Propose a manifesto & criteria → Run workflow** on `main`.

Supply:
- Public HTTPS PDF URL and canonical source URL;
- existing party ID and election year;
- source-backed title and publication date;
- an explicit comparison start and optional exclusive end;
- optional new edition ID (defaults to `party-year`);
- whether to extract criteria in the same run.

Dates are intentional inputs. Do not guess a publication date or infer an election window from the current date. Check republication rights before importing full manifesto text; see [DATA_LICENSE.md](../DATA_LICENSE.md).

The pipeline validates the source, downloads the PDF with size/page limits, extracts every page, makes a tree, optionally derives criteria, validates the complete data graph, runs tests, and proposes `data/manifesto` → `main`. All generated records remain proposed. An existing programme ID is an error, not an overwrite.

For staged review, turn **extract_criteria off**, review and merge the tree first, then run the next action. This gives you the first API data product independently of acceptance-criteria extraction.

## 2. Reviewed/imported tree → acceptance criteria

Run **Propose criteria for an imported manifesto**, giving its live `program_id` and a budget. The programme must already be on `main`; merging the tree does not itself mark it reviewed.

Every unprocessed leaf is evaluated with its ancestor sections. Existing criteria and recorded abstentions are preserved. The result is a `data/criteria` PR. Nothing is marked fulfilled. If all leaves have already been processed, there are no model calls and no new data PR.

## 3. New laws → candidate impacts

Run **Propose new laws & evidence**, with a maximum number of new publications (default 10) and optional earliest publication date. It:

1. imports unseen entries of type `Gesetz` from the official BGBl I RSS feed;
2. obtains and transcribes their own official PDFs;
3. retrieves applicable criteria, judges candidate effects, and challenges supported links;
4. validates citations and graph constraints;
5. proposes only canonical changes through `data/law-feed`.

Existing laws are also reconsidered when relevant source/corpus/model/prompt inputs change; they are not re-imported. Existing impacts and editorial fields are never overwritten. The run can publish new official law metadata with **no key** when no criterion requires an AI call. If an AI call is necessary and the secret is missing, it fails explicitly; it does not claim a successful no-op.

An unchanged run opens no PR. An initial matching audit or newly applicable criteria may change data even when the feed has no new law. `no_candidates` is not a conclusion of no legal impact.

### Scheduling

**The law pipeline is scheduled daily at 06:00 `Europe/Berlin`**, as requested by the operator. `law-feed.yml` specifies `cron: '0 6 * * *'` and `timezone: Europe/Berlin` together. All actions also remain manually runnable.

[GitHub supports timezone-aware schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule); the IANA timezone handles seasonal offsets rather than hard-coding a summer/winter conversion. During a DST spring-forward gap GitHub advances to the next valid time. GitHub can also delay/drop scheduled jobs, especially around busy hour boundaries, and public-repository schedules may be disabled after inactivity. Monitor feed freshness rather than promising exact execution times.

Do not schedule the potentially expensive full-manifesto import every day. Programme ingestion is an explicit event; the law feed and matching are the recurring task.

## Safety, cost and resumability

- Programme downloads: HTTPS, public addresses, checked redirect destinations, no embedded credentials, max 40 MiB / 400 PDF pages. Law downloads additionally stay on the official host allowlist. This is an application-level guard, not a substitute for network egress isolation in hostile multi-tenant use.
- Models have no tools. Untrusted PDF content cannot execute shell commands or request other services. Only schema-validated JSON is accepted; exact citations are separately validated.
- The model/provider must support structured JSON output. Provider routing requires parameter support and disallows data collection according to OpenRouter's provider policy; independently review the chosen provider's actual privacy terms.
- Provider routing is capped at **$1 per million prompt tokens and $4 per million output tokens**. A model above those rates has no eligible route; use a supported model rather than silently raising spending limits.
- The script conservatively reserves input bytes plus schema/system overhead and max output tokens against the budget **before every attempt**, including retries. Reported `reserved_usd_upper_bound` is not the actual provider invoice. Also set a provider-side key/account spending limit; local accounting is not an absolute guarantee against changed provider billing semantics.
- Cache keys include system prompt, task, model, input and schema. Structured completed responses are cached under `.cache/llm`, with no credentials. Treat cached public source/model text as untrusted. Caches are not published in the site or committed to Git.
- Actions restore/save caches even after a failed budget-limited run. A fresh retry can reuse completed calls and continue. Budget/call limits apply to each run, so repeatedly resuming increases the cumulative cost. Large programmes may need a deliberate limit increase or multiple cache-backed retries.
- A stage validates its proposed records before completion. A failed pipeline never opens a partial PR, even if its disposable checkout contains partial files. When using the CLI locally, inspect/discard only your own partial new outputs and preserve existing work; do not reset the whole repository.
- Each pipeline checks for its own open PR before network/model work, then waits for review rather than overwriting citizen edits. All data actions share one concurrency group. GitHub concurrency queues are not guaranteed to preserve arbitrarily many manual submissions; submit/import programmes one at a time and wait for completion/review.

## Local CLI

Install with `uv sync --frozen`. Export `OPENROUTER_API_KEY` through your local secret mechanism for AI stages. The CLI does **not** automatically read `.env`. Never paste a real key into a tracked script or command example.

```sh
# Read-only checks and schema export
uv run politrace validate
uv run politrace schemas

# Source ingestion without a model
uv run politrace laws --limit 3

# Programme input example: replace every SOURCE/DATE placeholder with verified metadata
uv run politrace program \
  --pdf /path/to/authorised-programme.pdf \
  --source-url https://publisher.example/programme \
  --party spd --year 2025 --title 'Verified programme title' \
  --published YYYY-MM-DD --period-start YYYY-MM-DD

uv run politrace criteria --program spd-2025
uv run politrace match --per-program 6
```

Global `--data` and `--cache` options go **before** the subcommand. Use a copied data directory to rehearse without changing your checkout:

```sh
cp -R data /tmp/politrace-data
uv run politrace --data /tmp/politrace-data --cache /tmp/politrace-llm laws --limit 1
```

There is no automatic DIP/roll-call adapter yet. Add independently sourced vote records through a PR; the UI and schema already support them. The RSS feed is not a full historical archive. See [methodology](methodology.md) for retrieval recall, legal-context and comparison limits.
