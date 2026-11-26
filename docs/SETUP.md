# Configuring the CI/CD pipeline

Everything in this repository is already written. This document is the
configuration work that has to happen **in your GitHub account and on your
server** before the pipeline runs — the exact names, where each one goes, and
how to verify it worked.

Time: about 30 minutes, most of it waiting for the first workflow run.

```
Step 1  push the repo                  → CI runs on its own
Step 2  repository variables           → staging/production URLs and paths
Step 3  environments + approval        → the human gate
Step 4  SSH deploy key                 → the pipeline can reach your host
Step 5  prepare the host               → Docker, clone, .env, first up
Step 6  branch protection              → CI becomes a merge gate
Step 7  tag a release                  → CD builds, deploys, verifies
Step 8  verify everything              → checklist at the end
```

---

## Step 1 — Push the repository and let CI run

```bash
cd campus-helpdesk
git init -b main
git add .
git commit -m "feat: campus IT helpdesk with CI/CD pipeline"
git remote add origin https://github.com/<you>/campus-helpdesk.git
git push -u origin main
```

Then: **Settings → Actions → General → Actions permissions** = *Allow all
actions and reusable workflows*. This is the default; check it if the repository
was imported or forked.

Open the **Actions** tab. `CI` starts on its own for the push to `main`. It needs
no configuration at all — no secrets, no variables, no services. Expected
result: four green jobs (`Lint and format`, `Tests (3.10/3.11/3.12)` ×3,
`Security scans`, `Build and smoke-test image`) in about four minutes.

If `CI` is green here, **the CI half is fully configured**. Steps 2–7 are only
about delivery.

---

## Step 2 — Repository variables

**Settings → Secrets and variables → Actions → Variables tab → New repository
variable.** These are *not* secret; they are URLs and paths.

| Name | Example value | Used by |
|---|---|---|
| `STAGING_URL` | `https://staging-helpdesk.example.edu` | verify staging, environment link |
| `STAGING_APP_DIR` | `/opt/helpdesk` | `cd` on the staging host |
| `PRODUCTION_URL` | `https://helpdesk.example.edu` | verify production, environment link |
| `PRODUCTION_APP_DIR` | `/opt/helpdesk` | `cd` on the production host |

> `STAGING_URL` must be reachable from a GitHub runner (a public URL, or a
> tunnel). If your staging host has no DNS yet, use
> `http://<server-ip>:8000` for the first run.

---

## Step 3 — Environments and the approval gate

**Settings → Environments → New environment.**

### `staging`

- No protection rules needed.
- Add environment variables here instead of at repository level if you want
  them scoped: `STAGING_URL`, `STAGING_APP_DIR`.
- Add environment secrets: `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY`.

### `production`

- **Required reviewers** → add yourself (and your guide, if this is assessed).
  This is the manual gate between staging and production.
- **Deployment branches** → *Selected branches and tags* → add the pattern
  `v*` (tags) and `main`. This stops an arbitrary branch from deploying.
- Environment secrets: `PRODUCTION_HOST`, `PRODUCTION_USER`, `PRODUCTION_SSH_KEY`.

Why environments and not repository secrets: a repository secret is readable by
every workflow on every branch. An environment secret is only readable by a job
that declares that environment *and* has passed its protection rules. That is
the difference between "the pipeline can deploy" and "anything in the repo can
deploy".

---

## Step 4 — The SSH deploy key

The workflows deploy over SSH, so they need a key pair.

```bash
# on your laptop — one key per environment is better; one key is fine for a project
ssh-keygen -t ed25519 -C "github-actions-helpdesk" -f ~/.ssh/helpdesk_deploy -N ""

# copy the PUBLIC key to the server
ssh-copy-id -i ~/.ssh/helpdesk_deploy.pub <user>@<server>

# the PRIVATE key goes into GitHub, never into the repo
cat ~/.ssh/helpdesk_deploy
```

Paste the **private** key (including the `-----BEGIN…` and `-----END…` lines)
into the environment secret `STAGING_SSH_KEY` / `PRODUCTION_SSH_KEY`.

| Secret | Value |
|---|---|
| `STAGING_HOST` | `203.0.113.10` or `staging.example.edu` |
| `STAGING_USER` | `deploy` (a normal user in the `docker` group) |
| `STAGING_SSH_KEY` | contents of `~/.ssh/helpdesk_deploy` |

Test it before trusting it:

```bash
ssh -i ~/.ssh/helpdesk_deploy <user>@<server> 'docker version --format "{{.Server.Version}}"'
```

---

## Step 5 — Prepare the deployment host

One-time setup on each server (staging and production).

```bash
# 1. Docker Engine + Compose v2
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"      # log out and back in afterwards
docker compose version               # must print v2.x

# 2. The application directory
sudo mkdir -p /opt/helpdesk && sudo chown "$USER" /opt/helpdesk
git clone https://github.com/<you>/campus-helpdesk.git /opt/helpdesk
cd /opt/helpdesk

# 3. Runtime configuration (never committed)
cp .env.example .env
python3 - <<'EOF'
import secrets, pathlib
p = pathlib.Path(".env")
s = p.read_text().replace("change-me-to-a-long-random-string", secrets.token_urlsafe(48))
p.write_text(s.replace("SESSION_COOKIE_SECURE=0", "SESSION_COOKIE_SECURE=1"))
EOF
chmod 600 .env

# 4. First start from the local source (proves the host works before CI is involved)
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/readyz
```

`SESSION_COOKIE_SECURE=1` requires HTTPS. Terminate TLS at nginx or a load
balancer in front of the container (the `nginx` profile in
`docker-compose.yml` is a starting point); if you are testing over plain HTTP,
leave it at `0`.

The deploy script records the running tag in `/opt/helpdesk/.current_image`,
which is how it knows what to roll back to. The first deploy writes it; before
that, a failed deploy has nothing to revert to and will say so.

---

## Step 6 — Branch protection (make CI a real gate)

**Settings → Branches → Add branch ruleset** (or *Add rule*) for `main`:

- ✅ Require a pull request before merging (1 approval)
- ✅ Require status checks to pass → select:
  - `Lint and format`
  - `Tests (Python 3.10)`, `Tests (Python 3.11)`, `Tests (Python 3.12)`
  - `Security scans`
  - `Build and smoke-test image`
- ✅ Require branches to be up to date before merging
- ✅ Do not allow bypassing the above settings

The check names appear in the picker only after CI has run at least once, so do
this after Step 1.

---

## Step 7 — Release a version

CD is triggered by a tag, not by a push to `main`:

```bash
git checkout main && git pull
git tag -a v1.0.0 -m "First release"
git push origin v1.0.0
```

What happens, in order:

1. `build-and-push` builds the image, scans it, and pushes
   `ghcr.io/<you>/campus-helpdesk:1.0.0` (+ `1.0`, `sha-xxxxxxx`) with an SBOM
   and provenance attestation.
2. `deploy-staging` SSHes in, runs `scripts/deploy.sh`, waits for `/readyz`,
   then verifies `/version` and runs the full smoke test against `STAGING_URL`.
3. `deploy-production` waits for **your approval** in the Actions UI
   (*Review deployments → Approve*), then repeats the same steps against
   `PRODUCTION_URL`.

### Make the package pullable

GHCR packages are private by default. The deploy job authenticates with the
workflow's `GITHUB_TOKEN`, so pulling works either way. To let anyone pull it:

**Package settings → Change visibility → Public.** (Or leave it private and
add a PAT with `read:packages` as an environment secret if a host needs to pull
outside a workflow.)

---

## Step 8 — Verify the configuration

Work down this list once; each line is a specific thing that can be wrong.

| # | Check | Expected |
|---|---|---|
| 1 | Actions tab after a push | `CI` green, 6 job runs (lint, 3 tests, security, docker) |
| 2 | Open a pull request | all five required checks appear and block the merge button |
| 3 | `pytest` locally, `make cov` | 67 passed, coverage ≥ 85% |
| 4 | `docker build -t test .` locally | builds; `docker run` → `/healthz` returns `{"status":"ok"}` |
| 5 | Tag `v1.0.0` pushed | `CD` starts; `build-and-push` green; package visible under *Packages* |
| 6 | Staging job | `Deploy to staging` green; `curl $STAGING_URL/version` shows `1.0.0` and the commit SHA |
| 7 | Production job | waits for approval; after approving, green |
| 8 | Break it on purpose | change a test to fail → CI red, merge blocked |
| 9 | Rollback | Actions → *Rollback* → previous tag → green |

Check 8 matters more than it looks: a gate you have never seen fail is a gate
you do not know is wired up.

---

## Troubleshooting the configuration

| Symptom | Cause | Fix |
|---|---|---|
| `denied: permission_denied` on push to GHCR | workflow lacks `packages: write` | already set in `cd.yml`; if you edited it, restore the `permissions:` block |
| `Error: Environment 'production' not found` | environment name mismatch | create it in Settings → Environments with that exact name |
| `ssh: handshake failed: unable to authenticate` | wrong key, or key pasted with line breaks | re-paste the private key; confirm the public key is in `~/.ssh/authorized_keys` on the host |
| `Host key verification failed` | first connection to a new host | add the host's key to known_hosts, or set the action's `fingerprint` input |
| Deploy job green but old version serving | `IMAGE` not exported on the host | check `docker compose config` shows the new image; `deploy.sh` exports it |
| `!! New version failed its readiness check` | container crashed or `.env` missing | `docker compose logs app` on the host; usually a missing `SECRET_KEY` |
| Login works but the session does not stick | `SESSION_COOKIE_SECURE=1` over plain HTTP | set it to `0`, or put HTTPS in front |
| Required check never appears in branch protection | CI has not run on a PR yet | push a PR once, then re-open the ruleset settings |
| `vars.STAGING_URL` empty | variable added as a *secret* | variables and secrets are different tabs |
| CI `docker` job times out | first build has no cache | re-run; the `type=gha` cache makes the second run ~40 s |

---

## If you do not have a server yet

CD needs somewhere to deploy. Three honest options, in order of effort:

1. **Self-hosted runner on your laptop** — install the runner, register it with
   the repository, add `runs-on: self-hosted` to the deploy jobs, and point
   `STAGING_APP_DIR` at a local clone. Everything else is unchanged, and the
   whole pipeline is demonstrable offline.
2. **A free-tier VM** — any provider that gives you a public IP and root SSH.
   Steps 4 and 5 apply exactly as written.
3. **CI only** — if the assessment only needs continuous integration, Steps 1
   and 6 are the whole configuration; skip 2–5 and 7. The `docker` job still
   proves the image builds, boots and serves traffic, which is the part
   examiners usually want to see.

---

## What not to put in the repository

| Never commit | Where it belongs |
|---|---|
| `.env` | the host filesystem, `chmod 600` |
| SSH private keys | environment secret `*_SSH_KEY` |
| `SECRET_KEY` values | environment variables on the host |
| Registry tokens | `GITHUB_TOKEN` (automatic) or an environment secret |

`.gitignore` and `.dockerignore` already exclude all of the above, and the
Dockerfile copies only `app/` and `wsgi.py`, so a stray local file cannot reach
the image.
