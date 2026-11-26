# Campus IT Helpdesk & Issue Management System

A working web application **and** a complete CI/CD pipeline around it — the
deliverable for *Option 1: CI/CD Pipeline for a Web Application using DevOps
Tools*.

Students and faculty raise IT tickets (Wi-Fi, lab PCs, projectors, software,
printers, accounts); the IT desk triages, assigns and resolves them against
per-priority SLAs, and the admin gets analytics on what breaks most often.

There is **no database**. All records live in an in-memory store seeded with 22
realistic demo tickets at start-up, so the whole stack runs with a single
container and no external service.

```
    Developer                GitHub                      Runtime
  ┌──────────┐   push   ┌────────────────┐  image   ┌──────────────┐
  │ feature  │ ───────► │  CI (ci.yml)   │ ───────► │  GHCR        │
  │ branch   │          │  lint → test   │          │  registry    │
  └──────────┘          │  → scan → build│          └──────┬───────┘
                        └────────┬───────┘                 │ pull
                                 │ merge to main           ▼
                        ┌────────▼───────┐          ┌──────────────┐
                        │ CD (cd.yml)    │ ───────► │ staging      │
                        │ tag v1.2.0     │          │ → production │
                        └────────────────┘          └──────────────┘
```

## What's inside

| Layer | Technology | Notes |
|---|---|---|
| Web app | Python 3.12, Flask 3.1 | application-factory pattern, blueprints |
| Views | Jinja2 + hand-written CSS | no frontend build step, no npm |
| Data | in-memory store + JSON seed | thread-safe, swap for a DB later |
| Tests | pytest 9, pytest-cov | 67 tests, 90% coverage, 85% gate |
| Lint/format | Ruff | one tool for both |
| Container | Docker multi-stage, gunicorn | non-root, read-only root FS, healthcheck |
| Orchestration | Docker Compose | app + optional nginx profile |
| CI | GitHub Actions | lint, test matrix, SAST, image build, smoke test |
| CD | GitHub Actions + GHCR | semver tags, SBOM, staging → production gate |
| Observability | `/healthz`, `/readyz`, `/metrics`, JSON logs | Prometheus-format metrics |

## Quick start

### 1. Run locally (no Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app wsgi run --debug --port 8000
```

Open <http://127.0.0.1:8000> and sign in with any demo account — the password
for all of them is `helpdesk123`.

### 2. Run in Docker

```bash
docker build -t campus-helpdesk:local .
docker run --rm -p 8000:8000 \
  -e SECRET_KEY=local-dev -e SESSION_COOKIE_SECURE=0 \
  campus-helpdesk:local
```

### 3. Run the full stack (with nginx)

```bash
docker compose up -d --build              # app  → http://localhost:8000
docker compose --profile proxy up -d      # + nginx → http://localhost:8080
docker compose logs -f app
```

### 4. Everything through make

```bash
make install     # venv + dependencies
make test        # pytest
make cov         # coverage with the 85% gate
make check       # lint + tests, exactly what CI runs
make docker-build && make docker-run && make smoke
```

## Demo accounts

| Role | Email | Password | Sees |
|---|---|---|---|
| Student | `aarav@campus.edu` | `helpdesk123` | own tickets only |
| Student | `priya@campus.edu` | `helpdesk123` | own tickets only |
| Faculty | `meera@campus.edu` | `helpdesk123` | own tickets only |
| Technician | `kabir@campus.edu` | `helpdesk123` | full queue, assignment, status changes |
| Technician | `sneha@campus.edu` | `helpdesk123` | full queue |
| Technician | `imran@campus.edu` | `helpdesk123` | full queue (network team) |
| Admin | `ananya@campus.edu` | `helpdesk123` | everything + analytics |

Passwords are stored as PBKDF2-SHA256 hashes (600k iterations) — the demo
password is hashed once per process and cached.

## Features

- **Ticket lifecycle** — Open → In Progress → Resolved → Closed, with reopening.
  Illegal jumps are rejected by the store with HTTP 409.
- **Priority SLAs** — Critical 4 h, High 8 h, Medium 24 h, Low 72 h. Every ticket
  shows *on track / at risk / breached*, computed live.
- **Role-based access** — requesters see only their own tickets; staff see the
  queue; analytics is staff-only. Enforced in the store *and* in the routes.
- **Assignment** — assigning an open ticket to a technician moves it to
  In Progress automatically and is recorded in the activity history.
- **Conversation** — public comments plus staff-only internal notes.
- **Analytics** — status/category/priority mix, average resolution time, SLA
  compliance, technician workload, oldest unresolved tickets.
- **Ops endpoints** — `/healthz`, `/readyz`, `/metrics`, `/version`.
- **Structured logs** — one JSON object per request with a request ID, duration
  and authenticated user.

## API

Session-cookie authenticated (the same login as the UI). JSON in, JSON out.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/meta` | service metadata, categories, priorities (public) |
| GET | `/api/v1/tickets` | list; filters `status`, `category`, `priority`, `q`, `mine=1` |
| POST | `/api/v1/tickets` | create a ticket |
| GET | `/api/v1/tickets/<id>` | one ticket with comments and history |
| PATCH | `/api/v1/tickets/<id>` | change `status` and/or `assignee_id` |
| POST | `/api/v1/tickets/<id>/comments` | add a comment |
| GET | `/api/v1/analytics` | aggregated metrics (staff only) |

```bash
# log in, keep the cookie, then create a ticket
curl -s -c jar.txt http://localhost:8000/login > /dev/null
curl -s -b jar.txt -c jar.txt -X POST http://localhost:8000/login \
  -d "email=ananya@campus.edu" -d "password=helpdesk123" \
  -d "csrf_token=$(sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' jar.txt | head -1)"

curl -s -b jar.txt -H 'Content-Type: application/json' \
  -X POST http://localhost:8000/api/v1/tickets \
  -d '{"title":"Projector dead in CS-204","description":"No signal on any input.","category":"Projector / AV","priority":"High"}'
```

Error responses are always `{"error": {"code": 400, "message": "...", "field": "..."}}`.

## Project structure

```
.
├── app/
│   ├── __init__.py          application factory, request logging, error handlers
│   ├── config.py            Config / TestConfig / ProductionConfig (env driven)
│   ├── models.py            Ticket, User, Comment, SLA rules, state machine
│   ├── store.py             thread-safe in-memory store + analytics
│   ├── security.py          session auth, role guards, CSRF
│   ├── logging_setup.py     JSON log formatter
│   ├── data/seed_tickets.json   22 demo tickets, 8 demo users
│   ├── routes/{auth,views,api,health}.py
│   ├── templates/           Jinja2 pages
│   └── static/              CSS + vanilla JS
├── tests/                   67 tests: store, API, views, auth, ops
├── scripts/
│   ├── smoke_test.sh        post-deploy verification (used by CI and CD)
│   └── deploy.sh            deploy with readiness gate + automatic rollback
├── nginx/nginx.conf         reverse proxy, rate limiting, security headers
├── .github/workflows/
│   ├── ci.yml               lint → test matrix → security → image + smoke test
│   ├── cd.yml               build/push → staging → production
│   └── rollback.yml         manual redeploy of a previous image
├── Dockerfile               multi-stage, non-root, healthcheck
├── docker-compose.yml       app + optional nginx profile
├── Makefile                 developer shortcuts
└── pyproject.toml           pytest, coverage and ruff configuration
```

## Testing

```bash
make test     # 67 tests
make cov      # coverage report, fails below 85%
```

| Suite | Tests | Covers |
|---|---|---|
| `test_store.py` | 13 | SLA maths with an injected clock, state machine, validation, analytics |
| `test_api_tickets.py` | 23 | JSON contract, filters, RBAC, 400/401/403/404/409 paths |
| `test_views.py` | 16 | rendered pages, forms, flash messages, role-specific UI |
| `test_auth.py` | 9 | login/logout, open-redirect guard, CSRF enforcement |
| `test_health.py` | 6 | health, readiness, metrics, version, security headers |

Current coverage: **90%** of `app/` (branch coverage on).

## CI/CD pipeline

| Stage | Tool | Gate |
|---|---|---|
| Lint & format | Ruff, Hadolint | fails the build on any finding |
| Tests | pytest, 3 Python versions | 85% coverage minimum |
| Security | bandit, pip-audit, Trivy | blocks on medium+ SAST findings, CRITICAL image CVEs |
| Build | Docker buildx, GHCR cache | image must build reproducibly |
| Smoke test | `scripts/smoke_test.sh` | live container must serve health, login and a ticket create |
| Deploy | GitHub Actions + SSH | readiness gate, automatic rollback |

**Configuring the pipeline in your own GitHub account** (variables,
environments, SSH key, host setup, branch protection, first release):
[`docs/SETUP.md`](docs/SETUP.md).

Full detail: [`docs/PIPELINE.md`](docs/PIPELINE.md) · architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · operations:
[`docs/RUNBOOK.md`](docs/RUNBOOK.md) · testing:
[`docs/TESTING.md`](docs/TESTING.md).

## Configuration

All settings are environment variables (12-factor):

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev key | session signing — **must** be set in production |
| `ENVIRONMENT` | `development` | selects production hardening |
| `SESSION_COOKIE_SECURE` | `0` | set to `1` behind HTTPS |
| `DEMO_PASSWORD` | `helpdesk123` | password for all seeded accounts |
| `APP_VERSION`, `GIT_SHA`, `BUILD_TIME` | `1.0.0`, `local`, `unknown` | injected at build time |
| `LOG_LEVEL` | `INFO` | log verbosity |
| `PORT` | `8000` | bind port for the dev server |

## Known limitations

- **In-memory data** — by design for this project. Restarting the container
  resets tickets to the seeded set. `app/store.py` is the single seam where a
  real database (PostgreSQL + SQLAlchemy) would slot in.
- **Session auth only** — the JSON API reuses the browser session; a real
  deployment would add token or OIDC auth for machine clients.
- **No TLS in the repo** — TLS is expected to terminate at the proxy or load
  balancer in front of the container.
- **Single-host deploy** — Compose on one VM. Kubernetes manifests are the
  natural next step.
