# syntax=docker/dockerfile:1

# ---- build stage: resolve and install locked dependencies into /app/.venv ----
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- runtime stage ----
FROM python:3.14-slim AS runtime

ARG VERSION=dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="audible-web-downloader" \
      org.opencontainers.image.description="Self-hosted household web app that backs up Audible purchases to a shared Audiobookshelf/Plex library" \
      org.opencontainers.image.source="https://github.com/aronjanosch/audible-web-downloader" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

# ffmpeg: AAX -> M4B conversion. tini: proper PID 1 (signal forwarding, zombie reaping).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini \
 && rm -rf /var/lib/apt/lists/*

# Fixed unprivileged user; compose runs it as 1000:1000 as well.
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    FLASK_ENV=production \
    LOG_LEVEL=INFO

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --chown=app:app . .

# State lives in these directories; mount volumes over them. The rest of the
# image can be read-only (only /tmp and these paths are written at runtime).
RUN mkdir -p /app/config /app/downloads /app/library /app/library_data \
 && chown -R app:app /app/config /app/downloads /app/library /app/library_data
VOLUME ["/app/config", "/app/downloads", "/app/library", "/app/library_data"]

USER 1000:1000
EXPOSE 5505

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5505/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["tini", "--"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
