# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: install the application and its dependencies.
#
# The app uses a src-layout with `pyproject.toml` at the repo root (setuptools
# backend). Only the files needed for the build are copied so no secrets or
# dev-only artifacts end up in builder layers.
# ---------------------------------------------------------------------------
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install .

# ---------------------------------------------------------------------------
# Runtime stage: a slim, non-root image with only what the app needs to run.
# ---------------------------------------------------------------------------
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a non-root user/group (uid/gid 1000) to run the application.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app --shell /usr/sbin/nologin app

WORKDIR /app

# Copy only the installed packages from the build stage. The app is invoked via
# `python -m offroad_scraper`, so no console scripts need copying.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Create the writable data dir and read-only config dir, owned by the app user.
# At runtime `/data` is typically backed by a PVC and `/config/sites.yaml` is
# mounted from a ConfigMap; these dirs just provide sane defaults.
RUN mkdir -p /data /config \
    && chown -R app:app /data /config

# Run as the non-root user.
USER app

ENTRYPOINT ["python", "-m", "offroad_scraper"]
CMD ["serve"]
