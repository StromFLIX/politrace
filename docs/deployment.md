# Docker Compose and Coolify

## Architecture

The runtime is one `web` service: unprivileged Nginx containing Astro's prebuilt HTML, JSON and Markdown. Python/OCR/model processing runs in GitHub Actions, not on the web server. There is no database, writable data volume, migration or runtime model secret.

- Build: root `Dockerfile` and `docker-compose.yml`.
- Internal HTTP port: **8080**; health: **`GET /api/health.json`** (200, JSON status `ok`).
- Read-only filesystem, temporary `/tmp`, all Linux capabilities dropped.
- No production host-port binding. `docker-compose.local.yml` adds `127.0.0.1:${PORT:-8080}:8080` only for local/CI tests. Publishing host port 8080 conflicts with the existing proxy.
- Coolify routes HTTPS to `web:8080` through its managed network.
- Local fonts/scripts; no CDN, tracker or browser model calls. Security headers: `deploy/nginx.conf`.
- Only real-source `/live/` data is built. Retired `/demo/` routes must return **404**; fictional test fixtures never enter the image.

## Local production test

```sh
export COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:8080/api/health.json
curl --fail http://127.0.0.1:8080/api/v1/live/laws.json
curl --fail http://127.0.0.1:8080/api/v1/live/readings.json
curl -I http://127.0.0.1:8080/api/v1/live/does-not-exist.json # 404
curl -I http://127.0.0.1:8080/demo/ # 404

docker compose logs --tail=100 web
docker compose down
```

Set `PORT` to an available host port if necessary. This changes only the local mapping, not the container or proxy port. Public traffic uses the existing HTTPS reverse proxy, not a new firewall opening.

## Production application

| Setting | Value |
| --- | --- |
| Coolify instance | `https://coolify.admin.stromflix.com` |
| API base | `/api/v1` (not the dashboard's `/security/api-tokens`) |
| Application | `politrace-production` · `bjmkjtfrbqjt41amhqksghti` |
| Git source | Installed `github.repository` GitHub App · `a04040skcskc40ogw0004o80` |
| Repository / branch | `StromFLIX/politrace` · `main` |
| Repository ID | `1404125346` |
| Build pack / directory | Docker Compose · `/` |
| Compose file / service | `/docker-compose.yml` · `web` |
| Public domain | `https://politrace.stromflix.com` |
| Service-domain input | `https://politrace.stromflix.com:8080` |
| Runtime secrets | **None** |

In Coolify's service-domain syntax, `:8080` selects the backend port. Users still visit standard HTTPS without a port suffix.

The previous replacement (`iwowpdg1qk96hugpif5eackd`) used Coolify's public Git source (`source_id=0`, no repository ID). Its auto-deploy toggle was enabled, but it had no installed-App webhook association. Successful Actions pushes therefore did **not** deploy it. The new application uses the existing installed GitHub App and matching repository ID; authenticated push events now trigger builds. The old replacement is stopped and retained for rollback, along with the earlier deprecated `clear-politics` application (`vkgcs40gg0k884o8os4c0k8s`). Do not leave two running applications assigned to the production domain.

Secrets are never committed, placed in build args, or copied into the web container. The existing GitHub App manages webhook authentication; the repository does not need a broad Coolify API token just to rebuild on a push.

## Automated publication and verification

1. A production processing slice saves its data, caches and cumulative ledgers before publication.
2. Source/schema/unit/build/browser checks run against the publishable snapshot, including valid partial results.
3. The publisher fetches/rebases instead of force-pushing; conflicting citizen corrections stop publication.
4. Coolify receives the installed GitHub App's push event for `main` and builds the Compose image.
5. A `GITHUB_TOKEN` push suppresses GitHub push-workflow triggers, so the publisher explicitly dispatches `ci.yml` with the original tested revision. Only bot dispatches can use that hint. CI skips repeated code-only checks only when Git proves the code still matches that tested revision and all differences are under `data/live/`; missing history, invalid hints or concurrent code/schema changes get full checks. Data validation, schema drift checks, the build and the full local browser suite always run.
6. CI runs Python and frontend checks in parallel. A separate Compose build/smoke job runs when packaging inputs change (Dockerfile, Compose, Nginx, package/lock/build configuration or CI scope logic), or when history is unavailable. The existing `test` status requires every applicable job to pass.
7. A separate **Verify production deployment** status downloads the exact probe files from the frontend's tested build, without rebuilding. `scripts/verify_deployment.py` waits up to ten minutes for that **exact built snapshot** over public HTTPS, then a small read-only desktop/mobile `@smoke` browser suite checks the homepage, API, reader and a citation round-trip. A failed deployment/probe remains a failure, not a green "queued" result, but does not keep the code-test status pending.

The exhaustive production browser suite is available through the **Full production browser checks** (`production-browser.yml`) manual workflow on `main`. Use it for investigations or release checks; it no longer repeats on every push. Browser tests use two workers on GitHub-hosted runners and one in small local containers. New smoke tests should be tagged `@smoke` so they also remain part of the full local suite.

The HTTPS probe compares the political data index, reading-edition index, OCR progress, all-party progress, landing/progress HTML, every programme reader and a law reader. This deliberately checks more than `data_sha256`: that legacy digest alone does not cover OCR-only or presentation-only changes. It also requires genuine 404s for unknown API records and removed demo routes, and checks that the snapshot did not change during the probe. Provider error bodies are not logged.

Coolify starts building on a push; it does not wait for the newly dispatched CI job. The data publisher already validates its snapshot before pushing. Review and protect code changes to `main`; never describe this arrangement as a branch-protection or human-review substitute. CI never probes/deploys a pull request as production.

## Manual HTTPS verification

Build the exact intended checkout first, then:

```sh
uv run python scripts/verify_deployment.py --timeout 600
POLITRACE_TEST_BASE_URL=https://politrace.stromflix.com npm run test:e2e -- --grep @smoke
# Optional exhaustive production checks:
POLITRACE_TEST_BASE_URL=https://politrace.stromflix.com npm run test:e2e
```

The probe verifies that the public response matches the local build, not merely that the server is healthy. `curl --fail https://politrace.stromflix.com/api/health.json` alone cannot detect a stale image.

## Build memory

Prefer at least 2 GiB of build memory. The six-programme/173-law corpus with all-party audits was verified in a 1 GiB development container using `ASTRO_TELEMETRY_DISABLED=1 NODE_OPTIONS=--max-old-space-size=448 npm run build` and the configured single Playwright worker. The earlier 320 MiB heap limit is no longer sufficient for type checking this checkout. Do not run heavy PDF processing and browser/build tests simultaneously. Static API serialization is streamed to avoid retaining duplicate exports. Larger corpora may require more memory.

The Docker context excludes `.env`, caches, PDFs and development environments. Reading editions and source citations are Git-backed public data, not runtime files fetched from a provider.

## Rollback and operations

- Redeploy an earlier tested Git commit/image, or move the domain back to the retained replacement after stopping the current app. Never force-push or erase later data history to roll back a website.
- The durable record is Git plus retained paid-work checkpoints. Back up repository access and ledgers; there is no application database backup.
- Monitor processing outcomes, the newest source date, per-programme coverage and the deployed snapshot separately. A healthy static container does not prove current or complete analysis.
- The public progress page is `/fortschritt/`; operations details and continuation limits are in [production.md](production.md).
- Actual operator/contact/Impressum and privacy/hosting-retention information still need to be supplied by the operator. Do not invent those details or describe the placeholder notice as complete legal compliance.
