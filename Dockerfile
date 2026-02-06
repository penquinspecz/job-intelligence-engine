# syntax=docker/dockerfile:1.4
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

# Create non-root user early (will own /app before final runtime)
RUN groupadd -r app && useradd -m -r -g app app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency metadata first for better layer caching
COPY requirements.txt /app/requirements.txt
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md

ARG RUN_TESTS=0
ARG PRINT_SNAPSHOT_SHA=0
ENV PYTHONHASHSEED=0
ENV TZ=UTC
ENV LC_ALL=C.UTF-8

# Install dependencies (no secrets required)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r /app/requirements.txt

# Copy package source before installing the distribution
COPY src /app/src

# Install the package itself
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .

# Copy project code
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs
COPY ops /app/ops
COPY tests /app/tests
COPY schemas /app/schemas
# Copy committed snapshot fixtures (deterministic/offline)
COPY --chown=app:app data/openai_snapshots/ /app/data/openai_snapshots/
COPY --chown=app:app data/anthropic_snapshots/ /app/data/anthropic_snapshots/
COPY --chown=app:app data/candidate_profile.json /app/data/candidate_profile.json

# Install dev/test extras only when running tests in CI (moto, pytest, etc.)
RUN if [ "$RUN_TESTS" = "1" ]; then pip install ".[dev]"; fi

# Debug: prove fixtures exist during build
RUN ls -la /app/data && \
    ls -la /app/data/openai_snapshots && \
    ls -la /app/data/anthropic_snapshots

# Run tests during build (deterministic, offline)
RUN if [ "$PRINT_SNAPSHOT_SHA" = "1" ]; then sha256sum /app/data/openai_snapshots/index.html && wc -c /app/data/openai_snapshots/index.html; fi
RUN if [ "$RUN_TESTS" = "1" ]; then python -m pytest -q; fi

# Ensure runtime user can write only to /app/data and /app/state (and ashby_cache)
RUN mkdir -p /app/data /app/state /app/data/ashby_cache /app/state/runs \
    && chown -R app:app /app/data /app/state \
    && chmod -R u+rwX,g+rwX /app/data /app/state \
    && ls -ld /app/data /app/state /app/state/runs /app/data/ashby_cache

# Expect /app/data and /app/state to be mounted; runtime code will ensure dirs
VOLUME ["/app/data", "/app/state"]

# Drop privileges for runtime
USER app

# Default container behavior runs the daily pipeline.
ENTRYPOINT ["python", "scripts/run_daily.py"]
CMD ["--profiles", "cs", "--us_only", "--no_post"]
