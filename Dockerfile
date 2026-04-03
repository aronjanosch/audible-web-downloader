FROM python:3.13-slim

# Install system dependencies (ffmpeg required for AAX→M4B conversion)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Install dependencies first — this layer is cached until pyproject.toml or uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Copy application code and do the final sync (installs the project itself)
COPY . .
RUN uv sync --locked --no-dev

RUN mkdir -p /app/config /app/downloads /app/library

EXPOSE 5505

CMD ["uv", "run", "python", "run.py"]
