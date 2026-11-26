#!/usr/bin/env python3
"""Wait until a Render deploy for the current commit is live.

Two modes:

* With ``RENDER_API_KEY`` and ``RENDER_SERVICE_ID`` set, poll the Render API
  until the newest deploy **for this exact commit** reports ``live``. This is
  the real gate: it proves the right code is serving traffic, not just that
  *something* answers.
* Without them, fall back to polling ``$RENDER_URL/readyz`` — weaker (it cannot
  tell old from new), but it keeps a demo working without API credentials.

Exit codes: 0 live, 1 failed or timed out, 2 misconfigured.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
FAILED_STATES = {"build_failed", "update_failed", "canceled", "deactivated", "pre_deploy_failed"}
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "15"))
MAX_WAIT = int(os.environ.get("MAX_WAIT", "900"))


def log(message: str) -> None:
    print(f"[wait-for-render] {message}", flush=True)


def api_get(path: str, token: str):
    request = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def readyz_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/readyz", timeout=10) as response:
            body = json.load(response)
            return response.status == 200 and body.get("ready") is True
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return False


def wait_for_api(service_id: str, token: str, commit: str) -> int:
    deadline = time.time() + MAX_WAIT
    seen: set[str] = set()

    while time.time() < deadline:
        try:
            payload = api_get(f"/services/{service_id}/deploys?limit=10", token)
        except urllib.error.HTTPError as exc:
            log(f"Render API returned {exc.code}: {exc.reason}")
            if exc.code in (401, 403, 404):
                log("check RENDER_API_KEY and RENDER_SERVICE_ID (service id looks like srv-xxxxxxxx)")
                return 2
            time.sleep(POLL_SECONDS)
            continue

        for item in payload:
            deploy = item.get("deploy", item)
            deploy_commit = (deploy.get("commit") or {}).get("id", "")
            if not deploy_commit.startswith(commit[:12]):
                continue

            status = deploy.get("status", "unknown")
            if deploy["id"] not in seen:
                seen.add(deploy["id"])
                log(f"deploy {deploy['id']} for {commit[:7]}: {status}")

            if status == "live":
                log("deploy is live")
                return 0
            if status in FAILED_STATES:
                log(f"deploy ended in state '{status}' — check the Render logs")
                return 1
            break

        time.sleep(POLL_SECONDS)

    log(f"no live deploy for {commit[:7]} within {MAX_WAIT}s")
    return 1


def wait_for_url(url: str) -> int:
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        if readyz_ok(url):
            log(f"{url}/readyz is green")
            return 0
        time.sleep(POLL_SECONDS)
    log(f"{url}/readyz did not turn green within {MAX_WAIT}s")
    return 1


def main() -> int:
    commit = os.environ.get("GITHUB_SHA", "")
    token = os.environ.get("RENDER_API_KEY", "").strip()
    service_id = os.environ.get("RENDER_SERVICE_ID", "").strip()
    url = os.environ.get("RENDER_URL", "").strip()

    if token and service_id:
        if not commit:
            log("GITHUB_SHA is not set")
            return 2
        log(f"watching service {service_id} for commit {commit[:7]}")
        return wait_for_api(service_id, token, commit)

    if url:
        log("RENDER_API_KEY / RENDER_SERVICE_ID not set — falling back to readiness polling")
        return wait_for_url(url)

    log("set RENDER_URL, or both RENDER_API_KEY and RENDER_SERVICE_ID")
    return 2


if __name__ == "__main__":
    sys.exit(main())
