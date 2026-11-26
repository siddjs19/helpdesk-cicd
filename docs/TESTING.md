# Testing strategy

## Shape of the suite

```
        ┌───────────────────────────┐
        │  smoke test (post-deploy) │  1 script, real HTTP, real container
        ├───────────────────────────┤
        │  view tests        16     │  rendered HTML, forms, role-specific UI
        ├───────────────────────────┤
        │  API contract      23     │  status codes, JSON shape, RBAC
        ├───────────────────────────┤
        │  store unit tests  13     │  SLA maths, state machine, validation
        ├───────────────────────────┤
        │  auth / ops tests  15     │  login, CSRF, health, metrics
        └───────────────────────────┘
                   67 tests · 90% coverage · 85% gate
```

| File | Tests | What it protects |
|---|---|---|
| `tests/test_store.py` | 13 | SLA breach maths with an injected clock, every legal and illegal transition, validation rules, analytics consistency |
| `tests/test_api_tickets.py` | 23 | the JSON contract: filters, 201/400/401/403/404/409 paths, assignee rules, comment rules |
| `tests/test_views.py` | 16 | pages render for each role, forms work, error pages, buttons only appear where allowed |
| `tests/test_auth.py` | 9 | login/logout, wrong password, open-redirect guard, CSRF enforcement |
| `tests/test_health.py` | 6 | `/healthz`, `/readyz`, `/metrics`, `/version`, security headers |

## Principles used

**Fresh state per test.** The `app` fixture builds a new application, which
builds a new `InMemoryStore` seeded from JSON. No test can leak state into
another, and there is no teardown to forget.

**Time is injected, never slept.** SLA behaviour is the most time-dependent part
of the app, so the store takes a `clock` callable:

```python
store = InMemoryStore(seed_path=..., clock=lambda: NOW)
assert store.tickets["HD-1001"].sla_state(NOW) == "breached"
```

The suite runs in ~30 s with zero `sleep()` calls and no flaky boundary tests.

**Test behaviour, not implementation.** Assertions are on HTTP status codes,
rendered text and returned JSON — not on private methods — so refactoring the
store does not break the API tests.

**Security rules are tested, not assumed.** CSRF is disabled in the default
`TestConfig` for convenience, and two dedicated tests re-enable it to prove the
token is actually required and actually accepted. The same for the open-redirect
guard and cross-tenant access (a student reading another student's ticket gets
403).

**The pipeline tests the artefact.** `scripts/smoke_test.sh` runs against a live
container in CI and against the public URL after every deploy: health, metadata,
login with a real CSRF round-trip, ticket creation, metrics. Unit tests can pass
while the image is broken; the smoke test cannot.

## Running

```bash
make test                          # whole suite
make cov                           # coverage + 85% gate
pytest tests/test_api_tickets.py -v
pytest -k "sla or transition" -v    # focused runs
pytest --cov=app --cov-report=html  # open htmlcov/index.html
```

## Coverage policy

- Measured on `app/` with branch coverage.
- Gate at **85%**; the suite currently reports **90%**.
- Uncovered lines are the ones that are hard to reach *and* low risk: process
  start-up, `__main__` blocks, and a few defensive branches in error handlers.
- A new feature is expected to arrive with tests that keep the gate green.

## Adding a test

1. Pick the layer: domain rule → `test_store.py`; JSON contract →
   `test_api_tickets.py`; page behaviour → `test_views.py`.
2. Use the `client` fixture, or `as_student` / `as_technician` / `as_admin` for
   an already-authenticated client.
3. Assert on observable output (status code, JSON field, rendered text).
4. Run `make check` before pushing — that is exactly what CI runs.

## What is deliberately not tested

- **Browser rendering** — no Selenium/Playwright layer; the UI is server-rendered
  HTML with a tiny progressive-enhancement script, and layout is verified
  manually. Adding Playwright would be the next step for a real deployment.
- **Load and performance** — no k6/Locust scenario. The app is I/O-trivial; the
  bottleneck would be gunicorn workers, which the runbook covers.
- **Multi-instance behaviour** — the in-memory store is single-process by
  design; a shared store is a documented future change.
