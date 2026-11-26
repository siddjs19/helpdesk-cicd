#!/usr/bin/env bash
# Post-deploy smoke test.
#
# Verifies that a freshly started container actually serves traffic: health,
# readiness, metadata, the login page, an authenticated API call and ticket
# creation. Used by the CI docker job and by the CD deploy job.
#
#   BASE_URL=http://127.0.0.1:8000 ./scripts/smoke_test.sh
#
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
MAX_WAIT="${MAX_WAIT:-60}"
DEMO_EMAIL="${DEMO_EMAIL:-ananya@campus.edu}"
DEMO_PASSWORD="${DEMO_PASSWORD:-helpdesk123}"

TMP_DIR="$(mktemp -d)"
COOKIE_JAR="${TMP_DIR}/cookies.txt"
trap 'rm -rf "${TMP_DIR}"' EXIT

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }

echo "Smoke test against ${BASE_URL}"

# 1. Wait for the container to answer.
waited=0
until curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1; do
  if [ "${waited}" -ge "${MAX_WAIT}" ]; then
    fail "service did not become healthy within ${MAX_WAIT}s"
  fi
  sleep 2
  waited=$((waited + 2))
done
pass "GET /healthz (${waited}s)"

# 2. Readiness: the in-memory store must be seeded.
ready="$(curl -fsS "${BASE_URL}/readyz")"
python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['ready'] and d['tickets'] > 0 else 1)" <<<"${ready}" \
  || fail "GET /readyz did not report a seeded store"
pass "GET /readyz (tickets seeded)"

# 3. Build metadata.
version="$(curl -fsS "${BASE_URL}/version")"
python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['version'] else 1)" <<<"${version}" \
  || fail "GET /version returned no version"
pass "GET /version ($(python3 -c "import json,sys; print(json.load(sys.stdin)['version'])" <<<"${version}"))"

# 4. Public API metadata.
curl -fsS "${BASE_URL}/api/v1/meta" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'categories' in d else 1)" \
  || fail "GET /api/v1/meta"
pass "GET /api/v1/meta"

# 5. Login page renders and carries a CSRF token.
login_page="$(curl -fsS -c "${COOKIE_JAR}" "${BASE_URL}/login")"
grep -q 'name="csrf_token"' <<<"${login_page}" || fail "login page has no CSRF token"
pass "GET /login (CSRF token present)"

csrf="$(sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' <<<"${login_page}" | head -n1)"

# 6. Sign in as the seeded admin.
status="$(curl -s -o /dev/null -w '%{http_code}' -b "${COOKIE_JAR}" -c "${COOKIE_JAR}" \
  -X POST "${BASE_URL}/login" \
  --data-urlencode "email=${DEMO_EMAIL}" \
  --data-urlencode "password=${DEMO_PASSWORD}" \
  --data-urlencode "csrf_token=${csrf}")"
[ "${status}" = "302" ] || fail "login returned ${status}, expected 302"
pass "POST /login (302 to dashboard)"

# 7. Authenticated API call.
count="$(curl -fsS -b "${COOKIE_JAR}" "${BASE_URL}/api/v1/tickets" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['meta']['count'])")"
[ "${count}" -gt 0 ] || fail "ticket list was empty"
pass "GET /api/v1/tickets (${count} demo tickets)"

# 8. Create a ticket through the API.
created="$(curl -fsS -b "${COOKIE_JAR}" -H 'Content-Type: application/json' \
  -X POST "${BASE_URL}/api/v1/tickets" \
  -d '{"title":"Smoke test ticket","description":"Created by scripts/smoke_test.sh after deploy.","category":"Wi-Fi / Network","priority":"Low"}')"
ticket_id="$(python3 -c "import json,sys; print(json.load(sys.stdin)['data']['id'])" <<<"${created}")"
pass "POST /api/v1/tickets (${ticket_id})"

# 9. Metrics endpoint is scrapeable.
curl -fsS "${BASE_URL}/metrics" | grep -q 'helpdesk_tickets_total' || fail "GET /metrics"
pass "GET /metrics"

echo "Smoke test passed."
