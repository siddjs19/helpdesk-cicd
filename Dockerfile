# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1 — builder: resolve and install dependencies into a virtualenv.
# Stage 2 — runtime: copy only the venv and the source, run as a non-root user.
# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt


FROM python:${PYTHON_VERSION}-slim AS runtime

# Build metadata is injected by CI so /version and /metrics can report it.
ARG APP_VERSION=1.0.0
ARG GIT_SHA=local
ARG BUILD_TIME=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME} \
    ENVIRONMENT=production \
    PORT=8000

# Principle of least privilege: never run the app as root.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app wsgi.py ./

USER app
EXPOSE 8000

# Docker/Kubernetes readiness probe — no curl in the slim image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "30", \
     "--graceful-timeout", "10", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "wsgi:app"]
