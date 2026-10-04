# Docker Compose and Coolify

## Architecture

The entire runtime is one `web` service: an unprivileged Nginx image containing Astro's prebuilt HTML, JSON and Markdown. The Python/model pipeline runs in GitHub Actions, not on the web server. There is no database, writable data volume, migration or runtime secret.

- Build: repository-root `Dockerfile` and `docker-compose.yml`.
- Internal HTTP port: **8080**.
- Health check: **`GET /api/health.json`** (200, JSON status `ok`).
- Filesystem: read-only, with a temporary `/tmp`; all Linux capabilities dropped.
- Host binding: **none in production**. The optional `docker-compose.local.yml` adds `127.0.0.1:${PORT:-8080}:8080` for local/CI smoke tests only. Publishing 8080 on the Coolify host conflicts with its existing services.
- Proxy: Coolify connects to `web:8080` through its managed network and terminates TLS.
- Assets: local fonts and scripts, no CDN, tracker or browser model calls. Security headers are in `deploy/nginx.conf`.

## Local production smoke test

```sh
export COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
curl --fail http://127.0.0.1:8080/api/health.json
curl --fail http://127.0.0.1:8080/api/v1/live/laws.json
curl --fail http://127.0.0.1:8080/api/v1/demo/programs/demo-spd-2025/source.md
curl -I http://127.0.0.1:8080/api/v1/live/does-not-exist.json # must be 404

docker compose logs --tail=100 web
docker compose down
```

If the host port is occupied, set `PORT` to an available port. This changes only the host mapping, not the container/proxy target. Public traffic should go through the HTTPS reverse proxy, not through a newly opened host firewall port.

## Reuse the existing Politrace domain

The inspected legacy Coolify application is:

- Application UUID: `vkgcs40gg0k884o8os4c0k8s`
- Domain: `https://politrace.stromflix.com`
- Old repository: **`StromFLIX/clear-politics`**, branch `main`
- Old build: Nixpacks, base `/website`, exposed port `80`

Those old settings will **not** build this new repository. Redeploying the old application without changing its source will only redeploy the deprecated site.

A separate replacement application has been created using the official Coolify CLI (v1.8.0) and API:

- Replacement UUID: `iwowpdg1qk96hugpif5eackd`
- Repository: `StromFLIX/politrace`, branch `main`
- Coolify instance: `https://coolify.admin.stromflix.com` (API base `/api/v1`, not the dashboard's `/security/api-tokens` page)

Credentials are supplied only at invocation time, never committed or added to the web container. The CLI archive checksum was checked against the release's checksums. Keep the old application for rollback; only move the domain after the replacement is healthy.

### Target configuration

Prefer a separate replacement app so rollback remains easy. If changing the existing app instead, record its current settings first.

| Setting | New value |
| --- | --- |
| Git repository | `StromFLIX/politrace` |
| Branch | `main` |
| Build pack | **Docker Compose** |
| Base directory | `/` |
| Compose file | `/docker-compose.yml` |
| Web service | `web` |
| Service domain / port | `https://politrace.stromflix.com:8080` in Coolify's service-domain input |
| Optional build selection | `POLITRACE_DATASET=auto` (or explicit `demo` / `live`) |
| Runtime model secret | **None** |

In Coolify's domain syntax, `:8080` selects the backend container port; the public site should still be standard HTTPS without users adding a port to the address bar. If your Coolify version exposes a separate service-port field, set that to 8080 instead.

1. Ensure the Coolify GitHub App can read the new repo and that `main` has been pushed.
2. Load/parse the root Compose file; remove inherited Nixpacks `/website` settings.
3. Build the replacement without assigning the old domain yet, using an operator-chosen preview domain if available.
4. Confirm the container is healthy and the API/site smoke checks pass.
5. Remove the domain from the old resource, assign it to `web` on the replacement, and deploy/reload proxy routing. Avoid two resources claiming the domain simultaneously.
6. Verify the public HTTPS URL, API content types, dataset labels, deep links and health response.
7. Retain the old application for rollback until review is complete. Stop/delete it only once the cutover is verified and desired.

A domain change/build is not successful merely because Coolify queued a deployment. Inspect its deployment result and verify the public response.

## Build memory

The web runtime is small, but building a full legal corpus is not. Prefer at least 2 GiB of build memory. In a 1 GiB development container, the 171-law corpus was verified with `NODE_OPTIONS=--max-old-space-size=320 npm run build` and a single Playwright worker. Do not run heavy PDF extraction and browser/build checks simultaneously in that container. The API serializes one route at a time rather than retaining every JSON export twice; the dataset index offers lightweight `counts` without downloading all law text. Larger corpora may need more memory. None of these build settings belongs in a runtime model-secret configuration.

## Rebuild after data merges

Enable Coolify's GitHub auto-deploy webhook for `main` if desired. Merged data requires a new image build; runtime containers do not read the Git checkout or poll GitHub. Protect `main` so source-backed data and reviews are validated before automatic deployment.

`POLITRACE_DATASET` is a Compose **build argument**, not a runtime switch. Both `/demo/` and `/live/` remain built and accessible; it only selects the landing-page dataset. Do not place secrets in build arguments. The Docker build context excludes `.env`, caches, PDFs and development environments.

## Verify through HTTPS

After deployment:

```sh
curl --fail https://politrace.stromflix.com/api/health.json
curl --fail https://politrace.stromflix.com/api/v1/index.json
curl --fail https://politrace.stromflix.com/api/v1/live/laws.json
curl -I https://politrace.stromflix.com/api/v1/live/does-not-exist.json
```

In a browser, check the demo warning, live-source links, party period switch, criterion → programme anchor, activity filters, law source/vote states and mobile navigation. Nginx must return JSON/Markdown with correct content types, not a catch-all HTML index. The CSP allows only local scripts; the application does not need inline JavaScript exceptions.

## Rollback and operations

- Deploy an earlier Git commit/image or restore the previous app's domain routing. Do not force-push or delete later data history to roll back a website.
- The durable record is Git. Back up repository access/history and relevant deployment configuration; no application database backup is needed.
- A healthy static container does not mean the law feed is fresh. Monitor GitHub workflow outcomes, open data PRs, date of the newest source and latest deployed commit separately.
- Before public production operation, supply the operator's actual contact/Impressum and privacy/hosting retention details. Do not treat the placeholder pilot notice as complete legal compliance.
