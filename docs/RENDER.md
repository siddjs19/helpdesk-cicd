# Deploying to Render

Render runs the Dockerfile directly, so nothing in the application changes. It
builds the image on its own infrastructure, which means this path replaces the
"build once, push to GHCR, SSH deploy" chain in `cd.yml` with "Render builds,
GitHub Actions triggers and verifies".

Use **either** `deploy-render.yml` **or** the SSH jobs in `cd.yml` — running both
against the same service is how you get two half-deployed versions.

---

## 1. Create the service (5 minutes, once)

1. **render.com → New + → Web Service.**
2. Connect GitHub and pick your repository.
3. Settings on the form:
   - **Language / Runtime:** Docker (Render detects `./Dockerfile`)
   - **Region:** Singapore (lowest latency from India; US adds ~200 ms)
   - **Instance type:** Free to demo, Starter for anything real
   - **Health check path:** `/readyz`
4. **Environment variables** (Render → Environment):

   | Key | Value |
   |---|---|
   | `SECRET_KEY` | a long random string — `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
   | `ENVIRONMENT` | `production` |
   | `SESSION_COOKIE_SECURE` | `1` (Render serves HTTPS, so this is correct here) |
   | `DEMO_PASSWORD` | `helpdesk123` (or your own) |
   | `LOG_LEVEL` | `INFO` |

   Do **not** set `PORT` — Render injects it and the container now honours it.

5. **Build & Deploy → Auto-Deploy: No.** This is the important one. With
   auto-deploy on, every push to `main` ships to production without waiting for
   CI. Off, only a tag (or the deploy hook) deploys — which is the whole point
   of the pipeline.

6. Create the service. The first build takes 2–4 minutes.

## 2. Copy four values into GitHub

**Settings → Secrets and variables → Actions**, and create an environment named
`render` (Settings → Environments) so these are scoped to deployments only.

| Kind | Name | Where to find it |
|---|---|---|
| Variable | `RENDER_URL` | the service URL, e.g. `https://campus-helpdesk.onrender.com` |
| Secret | `RENDER_DEPLOY_HOOK` | Service → Settings → **Deploy Hook** → copy the URL |
| Secret | `RENDER_API_KEY` | Account Settings → **API Keys** → Create |
| Secret | `RENDER_SERVICE_ID` | Service → Settings, or the dashboard URL: `srv-xxxxxxxxxxxx` |

`RENDER_API_KEY` + `RENDER_SERVICE_ID` are what let the workflow wait for *your
commit* to go live rather than just any response. Without them the job falls
back to polling `/readyz`, which cannot tell the old version from the new one.

## 3. Release

```bash
git tag -a v1.0.0 -m "First Render release"
git push origin v1.0.0
