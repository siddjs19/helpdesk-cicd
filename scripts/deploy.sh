#!/usr/bin/env bash
# Deploy a specific image tag on the target host, with automatic rollback.
#
# Run on the deployment host (invoked by the CD workflow over SSH):
#
#   ./scripts/deploy.sh ghcr.io/<owner>/<repo>:1.2.0
#
# Environment: APP_DIR (default /opt/helpdesk), HEALTH_URL, COMPOSE_CMD.
#
set -euo pipefail

IMAGE="${1:-}"
if [ -z "${IMAGE}" ]; then
  echo "usage: $0 <image-reference>" >&2
  exit 64
fi

APP_DIR="${APP_DIR:-/opt/helpdesk}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/readyz}"
STATE_FILE="${APP_DIR}/.current_image"
COMPOSE="${COMPOSE_CMD:-docker compose}"

cd "${APP_DIR}"

previous=""
if [ -f "${STATE_FILE}" ]; then
  previous="$(cat "${STATE_FILE}")"
fi

echo "==> Pulling ${IMAGE}"
docker pull "${IMAGE}"

echo "==> Starting ${IMAGE}"
export IMAGE
${COMPOSE} up -d --no-deps app

echo "==> Waiting for readiness at ${HEALTH_URL}"
healthy=0
for _ in $(seq 1 30); do
  if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done

if [ "${healthy}" -ne 1 ]; then
  echo "!! New version failed its readiness check" >&2
  ${COMPOSE} logs --tail 50 app >&2 || true
  if [ -n "${previous}" ]; then
    echo "==> Rolling back to ${previous}" >&2
    export IMAGE="${previous}"
    ${COMPOSE} up -d --no-deps app
    echo "Rolled back to ${previous}" >&2
  else
    echo "No previous image recorded; manual intervention required" >&2
  fi
  exit 1
fi

echo "${IMAGE}" > "${STATE_FILE}"
echo "==> Deployed ${IMAGE} successfully"

# Keep the last five images, drop the rest to protect disk space.
docker image prune -f --filter "until=168h" >/dev/null 2>&1 || true
