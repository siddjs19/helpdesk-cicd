# Architecture

## 1. Application architecture

```
                    ┌────────────────────────────────────────────┐
   Browser ────────►│  Flask app (gunicorn, 3 workers × 2 threads)│
   curl / CI        │                                            │
                    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
                    │  │ routes/  │  │ routes/  │  │ routes/  │  │
                    │  │ views    │  │ api      │  │ health   │  │
                    │  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
                    │       └─────────────┼─────────────┘        │
                    │              ┌──────▼──────┐               │
                    │              │ security.py │ session, RBAC │
                    │              │             │ CSRF          │
                    │              └──────┬──────┘               │
                    │              ┌──────▼──────┐               │
                    │              │  store.py   │ RLock, seed   │
                    │              │  (in-memory)│ analytics     │
                    │              └──────┬──────┘               │
                    │              ┌──────▼──────┐               │
                    │              │  models.py  │ SLA + states  │
                    │              └─────────────┘               │
                    └────────────────────────────────────────────┘
```

Layers, top to bottom:

1. **Routes** — thin HTTP adapters. They parse input, call the store, and map
   domain exceptions to status codes. No business rules live here.
2. **security.py** — resolves the session user on every request, enforces
   `login_required` / `role_required`, and validates CSRF tokens on form posts.
3. **store.py** — the single source of truth: users, tickets, comments, history
   and analytics. Every mutation takes a re-entrant lock, so the app is safe
   under gunicorn's threads.
4. **models.py** — plain dataclasses plus the domain rules that must never be
   duplicated: SLA hours per priority, the allowed status transitions, and the
   derived `sla_state` (met / breached / at-risk / on-track).

### Why no database

The brief only needs a credible application to put a pipeline around. An
in-memory store keeps the pipeline honest (one container, no migrations, no
service containers in CI) and still exercises every code path a database would:
validation, role checks, state transitions, aggregation queries.

The seam is deliberate: `InMemoryStore` exposes `get_ticket`, `list_tickets`,
`create_ticket`, `update_status`, `assign`, `add_comment` and `analytics`. A
`SqlStore` implementing the same methods drops in without touching a route.

### Data model

```
User 1───n Ticket n───1 User (assignee)
              │
              ├──n Comment ──1 User (author)
              └──n HistoryEvent (append-only audit trail)
```

`Ticket` fields: `id` (`HD-1001`…), `title`, `description`, `category`,
`priority`, `status`, `requester_id`, `assignee_id`, `location`, `created_at`,
`updated_at`, `resolved_at`, `comments[]`, `history[]`.

### Status machine

```
        ┌────────────── reopen ──────────────┐
        ▼                                    │
     ┌──────┐  assign / start   ┌─────────────┐  resolve  ┌──────────┐
     │ Open │ ────────────────► │ In Progress │ ────────► │ Resolved │
     └──┬───┘                   └──────┬──────┘           └────┬─────┘
        │ close                        │ reopen                │ close
        ▼                              ▼                       ▼
     ┌────────┐ ◄──────────────────────┴───────────────────────┘
     │ Closed │
     └────────┘
```

Anything not in this graph raises `ConflictError` → HTTP 409.

### SLA model

| Priority | Target | Breach definition |
|---|---|---|
| Critical | 4 h | unresolved longer than target |
| High | 8 h | same |
| Medium | 24 h | same |
| Low | 72 h | same |

`at-risk` is 75–100% of the target elapsed, so the dashboard warns before a
breach happens. The clock is injected (`InMemoryStore(clock=...)`), which is what
makes the SLA tests deterministic instead of time-dependent.

## 2. Runtime architecture

```
   Internet
      │  :443 (TLS terminated by proxy / load balancer)
      ▼
┌───────────────┐        ┌──────────────────────────────────────┐
│ nginx (opt.)  │ :8000  │ helpdesk container                   │
│ rate limit,   ├───────►│  gunicorn → Flask                    │
│ gzip, headers │        │  non-root uid 1001                   │
└───────────────┘        │  read-only root FS, /tmp tmpfs       │
                         │  HEALTHCHECK → /healthz              │
                         └──────────────────────────────────────┘
```

Image design decisions:

| Decision | Reason |
|---|---|
| Multi-stage build | build tools and pip caches never reach the runtime image |
| `python:3.12-slim` | small, glibc-based, patched by the Python image maintainers |
| Non-root user (uid 1001) | a compromised app cannot write to the filesystem or install packages |
| `read_only: true` + tmpfs `/tmp` | container immutability; gunicorn's heartbeat has a writable temp dir |
| `cap_drop: ALL`, `no-new-privileges` | removes Linux capabilities the app never needs |
| `HEALTHCHECK` on `/healthz` | Docker, Compose and Kubernetes all understand it |
| Build args for version/SHA/time | `/version` and `/metrics` report exactly what is running |
| `--workers 3 --threads 2` | CPU-bound work is negligible; threads keep I/O latency low |

## 3. Observability

| Endpoint | Purpose | Consumer |
|---|---|---|
| `/healthz` | liveness — process answers | Docker HEALTHCHECK, load balancer |
| `/readyz` | readiness — store seeded, counts | deploy script, orchestrator |
| `/metrics` | Prometheus text: tickets by status/category, SLA breaches, MTTR, compliance ratio, build info | Prometheus scrape |
| `/version` | version, git SHA, build time, environment | smoke test, support |

Every response carries `X-Request-ID` (echoed from the request when supplied)
and `X-Response-Time-ms`. Logs are one JSON object per line on stdout, so the
container runtime is the log store — the app never writes log files.

```json
{"ts":"2026-11-26T18:20:29.577+00:00","level":"INFO","logger":"app","msg":"request",
 "event":"http_request","request_id":"1659069d3ebe","method":"GET","path":"/dashboard",
 "status":200,"duration_ms":69.0,"user":"ananya@campus.edu"}
```

## 4. Security posture

| Control | Implementation |
|---|---|
| Password storage | PBKDF2-SHA256, 600k iterations, constant-time compare |
| Session | signed cookie, HttpOnly, SameSite=Lax, `Secure` in production |
| CSRF | per-session token, checked on every form POST, compared with `hmac.compare_digest` |
| Open redirect | `next` is only honoured when it starts with `/` |
| Authorisation | role checks in routes *and* ownership checks in the store |
| Response headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` |
| Input limits | `MAX_CONTENT_LENGTH` 1 MB, field length caps, category/priority allow-lists |
| Container | non-root, read-only FS, no capabilities |
| Supply chain | pinned dependencies, pip-audit, Trivy, SBOM + provenance on every published image |
| Secrets | environment only; nothing secret is baked into the image or the repo |
