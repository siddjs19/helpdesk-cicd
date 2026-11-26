# CI/CD pipeline

Two workflows do all the work: `ci.yml` proves a change is safe, `cd.yml` ships
it. A third, `rollback.yml`, is the manual escape hatch.

```
 push / PR                        tag v1.2.0 (or manual run)
     │                                    │
     ▼                                    ▼
┌──────────────────────┐        ┌──────────────────────────┐
│ CI  ci.yml           │        │ CD  cd.yml               │
│                      │        │                          │
│ 1 lint  (Ruff,       │        │ 1 build + push to GHCR   │
│          Hadolint)   │        │   (semver + sha tags,    │
│ 2 test  (3.10/3.11/  │        │    SBOM, provenance)     │
│          3.12, ≥85%) │        │ 2 Trivy: fail on CRITICAL│
│ 3 security (bandit,  │        │ 3 deploy → staging       │
│    pip-audit, Trivy) │        │ 4 verify (health+smoke)  │
│ 4 docker build      │        │ 5 deploy → production    │
│   + boot + smoke     │        │   (manual approval)      │
│   + Trivy image      │        │ 6 verify, else rollback  │
└──────────────────────┘        └──────────────────────────┘
```

## Stage 1 — Continuous Integration (`ci.yml`)

Triggers: push to `main` / `develop`, every pull request, manual dispatch.
Concurrency cancels superseded runs on the same ref, so a quick second push
does not pay for the first one.

### Job: `lint` (~40 s)

| Step | Command | Why it gates |
|---|---|---|
| Ruff lint | `ruff check --output-format=github .` | unused imports, undefined names, bugbear rules; findings annotate the diff |
| Ruff format | `ruff format --check .` | ends formatting arguments in review |
| Hadolint | `hadolint Dockerfile` (threshold: warning) | catches `latest` tags, root user, missing `--no-install-recommends` |

It runs first and alone: a style failure costs 40 seconds instead of a
three-version test matrix.

### Job: `test` (~1 min per version)

Matrix on Python **3.10, 3.11 and 3.12** with `fail-fast: false` so one broken
version still reports the others.

```bash
pytest --cov=app --cov-report=term-missing --cov-report=xml \
       --cov-fail-under=85 --junitxml=reports/junit.xml
```

- **85% coverage gate** — below it the job fails. Current: 90%.
- `coverage.xml` and `junit.xml` are uploaded as artifacts for 7 days, so a
  reviewer can see the report of any historical run.
- No service containers: the app seeds its own data, so the matrix costs
  nothing extra.

### Job: `security` (~1 min)

| Scanner | Target | Behaviour |
|---|---|---|
| `bandit -r app -ll` | source | fails on medium/high findings (no `eval`, no `subprocess`, no `assert` on security paths) |
| `pip-audit -r requirements.txt --strict` | dependencies | reports known CVEs; non-blocking today because it depends on upstream releases |
| Trivy (filesystem) | repo | SARIF uploaded to GitHub code scanning, so findings appear on the Security tab |

### Job: `docker` (~2 min)

1. Build with `docker/build-push-action` and GitHub Actions layer cache
   (`cache-from/to: type=gha`) — a warm rebuild takes seconds.
2. `load: true` keeps the image local (CI never publishes).
3. Start the container and **run the real smoke test** against it:
   `/healthz`, `/readyz`, `/version`, `/api/v1/meta`, login with CSRF, list
   tickets, create a ticket, scrape `/metrics`.
4. Trivy image scan: fails the build on **CRITICAL** CVEs with a fix available.
5. Always remove the container; dump logs on failure.

This is the step that makes CI meaningful — it proves the *image*, not just the
source tree, serves traffic.

## Stage 2 — Continuous Delivery (`cd.yml`)

Triggers: a `v*.*.*` tag, or a manual dispatch with an environment choice.

### Job: `build-and-push`

- Logs in to GHCR with the workflow's `GITHUB_TOKEN` (`packages: write`).
- `docker/metadata-action` derives tags from the tag name:
  `1.2.0`, `1.2`, `sha-abc1234`, and `latest` only on the default branch.
- Builds and pushes with `provenance: true` and `sbom: true`, so the registry
  stores a signed build record and a dependency SBOM alongside the image.
- Scans the pushed image; a CRITICAL finding stops the release before it can be
  deployed.

### Job: `deploy-staging`

Runs inside the `staging` GitHub Environment (its variables and secrets are
scoped there). Over SSH it logs in to GHCR, then runs `scripts/deploy.sh`:

```bash
bash ./scripts/deploy.sh ghcr.io/<owner>/<repo>:1.2.0
```

`deploy.sh` pulls the exact image, restarts only the app service, and polls
`/readyz` for up to 60 seconds. If the new version never becomes ready it
re-deploys `.current_image` (the last known-good tag) and exits non-zero — the
workflow stops there, and production is never touched.

The job then re-verifies over HTTPS: `/version`, `/readyz`, and the full smoke
test against the public URL.

### Job: `deploy-production`

Identical mechanics against the `production` environment, which is configured
with **required reviewers** in GitHub. That approval is the human gate between
staging and production. If post-deploy verification fails, a final step SSHes
back in and re-deploys the previous image.

### Job: `rollback` (`rollback.yml`)

Manual dispatch with an image reference and an environment. Useful when a
problem appears after the deploy window closed. Because `deploy.sh` always
health-checks and always remembers the previous tag, rollback is the same code
path as deploy — nothing special to get wrong.

## Configuration the pipeline needs

### Repository secrets

| Secret | Used by | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | both | provided automatically; GHCR push/pull |
| `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY` | staging deploy | SSH access |
| `PRODUCTION_HOST`, `PRODUCTION_USER`, `PRODUCTION_SSH_KEY` | production deploy | SSH access |

### Repository / environment variables

| Variable | Example |
|---|---|
| `STAGING_URL` | `https://staging-helpdesk.example.edu` |
| `STAGING_APP_DIR` | `/opt/helpdesk` |
| `PRODUCTION_URL` | `https://helpdesk.example.edu` |
| `PRODUCTION_APP_DIR` | `/opt/helpdesk` |

### Host prerequisites

```bash
# once per host
sudo mkdir -p /opt/helpdesk && cd /opt/helpdesk
git clone <repo> .
cp .env.example .env && vi .env      # SECRET_KEY, SESSION_COOKIE_SECURE=1
docker compose up -d --build
```

## Branching and gates

```
feature/*  ──PR──►  develop  ──PR──►  main  ──tag v1.2.0──►  staging ──approval──► production
                    CI gate            CI gate              CD verify            CD verify
```

- A pull request cannot merge with a red `lint`, `test`, `security` or `docker`
  check (branch protection).
- `main` is always deployable: the same commit that passed CI is the one tagged.
- Every image is immutable and traceable — tag → commit SHA → `/version` output.

## Pipeline metrics to watch

| Metric | Target | Where |
|---|---|---|
| CI wall-clock time | < 5 min | Actions run summary |
| Pipeline success rate | > 95% | Actions insights |
| Time from merge to staging | < 8 min | run timestamps |
| Failed deploys needing manual rollback | 0 | deploy logs |
| Image size | < 120 MB | `docker image ls` in CI |
