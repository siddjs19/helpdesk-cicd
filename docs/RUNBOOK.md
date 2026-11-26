# Operations runbook

Short, specific procedures for the things that actually get asked at 2 a.m.

## Health checks

```bash
curl -fsS http://<host>:8000/healthz   # liveness  → {"status":"ok"}
curl -fsS http://<host>:8000/readyz    # readiness → ready + record counts
curl -fsS http://<host>:8000/version   # what is actually running
curl -fsS http://<host>:8000/metrics   # Prometheus exposition
```

`/readyz` returning 503 means the store has not finished seeding — during
start-up that is normal for a second; persistent 503 means a bad image.

## Deploy a specific version

```bash
cd /opt/helpdesk
bash ./scripts/deploy.sh ghcr.io/<owner>/<repo>:1.2.0
```

The script pulls, restarts the app service only, polls `/readyz` for up to
60 s, records the tag in `.current_image`, and rolls back automatically if the
health check never passes.

## Roll back

```bash
cd /opt/helpdesk
cat .current_image                      # what is running now
bash ./scripts/deploy.sh ghcr.io/<owner>/<repo>:1.1.0
```

Or use the **Rollback** workflow in GitHub Actions (Actions → Rollback → Run
workflow) and pass the image reference — same result, with an audit trail.

## Inspect logs

```bash
docker compose logs -f --tail=100 app            # JSON, one line per request
docker compose logs app | grep '"status":5'      # server errors only
docker compose logs app | grep '"event":"login_failed"'
docker compose logs app | jq -r 'select(.duration_ms > 500) | .path'
```

Every line carries `request_id`; grep it to follow one request end to end.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| Container restarts in a loop | `SECRET_KEY` unset and config rejected | set `SECRET_KEY` in `.env`, `docker compose up -d` |
| Login succeeds but the session does not stick | `SESSION_COOKIE_SECURE=1` while serving plain HTTP | set `SESSION_COOKIE_SECURE=0` for HTTP, or put TLS in front |
| All logins return 401 | `DEMO_PASSWORD` differs from the one you are typing | read it from `.env`, or unset it to fall back to `helpdesk123` |
| `/readyz` returns 503 | store failed to seed (bad `SEED_FILE`) | `docker compose logs app`; verify `app/data/seed_tickets.json` exists in the image |
| `403 CSRF token missing or invalid` on a form post | session expired mid-form | reload the page and submit again |
| `409 Cannot move ticket from 'X' to 'Y'` | illegal transition — by design | follow Open → In Progress → Resolved → Closed |
| `502` from nginx | app container not healthy yet | `docker compose ps`, wait for `healthy` |
| Port already in use | another stack on 8000/8080 | `APP_PORT=8010 docker compose up -d` |
| Disk full | old images accumulating | `docker image prune -af --filter until=168h` |

## Restart / reset

```bash
docker compose restart app        # keeps the container, re-runs the process
docker compose down && docker compose up -d   # new container, demo data reseeded
```

Because data is in memory, a restart restores the seeded demo dataset. That is
expected behaviour for this project, not data loss to investigate.

## Capacity and limits

- 3 gunicorn workers × 2 threads; a single container handles a campus-sized
  load (a few hundred requests per minute) comfortably.
- Memory limit in Compose: 512 MB. The dataset is ~22 tickets, so usage sits
  under 100 MB.
- Scale horizontally behind the proxy only if the store becomes shared
  (i.e. once a real database replaces the in-memory store).

## Incident checklist

1. `/readyz` and `/version` — is the right image even running?
2. `docker compose ps` — healthy, restarting, or exited?
3. `docker compose logs --tail=200 app` — 5xx, tracebacks, OOM kills.
4. Bad release? Roll back with `deploy.sh <previous tag>`; do not debug on
   production.
5. Record the incident: image tag, first bad timestamp, `request_id` samples,
   rollback time. The next pipeline run should encode whatever was missing.
