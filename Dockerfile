FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app/src

# Create non-root user early (will own /app before final runtime)
RUN groupadd -r app && useradd -m -r -g app app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency metadata first for better layer caching
COPY pyproject.toml /app/pyproject.toml
COPY requirements.txt /app/requirements.txt
COPY README.md /app/README.md

# Install dependencies + dev test deps (no secrets required)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir pytest

# Copy project code
COPY src /app/src
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs
COPY tests /app/tests
# Optionally bake snapshots for offline/snapshot runs (other data excluded by .dockerignore)
COPY --chown=app:app data/openai_snapshots /app/data/openai_snapshots
COPY --chown=app:app data/candidate_profile.json /app/data/candidate_profile.json

# Run tests during build (deterministic, offline)
RUN python -m pytest -q

# Ensure runtime user can write only to /app/data and /app/state
RUN mkdir -p /app/data /app/state && chown app:app /app/data /app/state

# Expect /app/data and /app/state to be mounted; runtime code will ensure dirs
VOLUME ["/app/data", "/app/state"]

# Drop privileges for runtime
USER app

# Default container behavior runs the daily pipeline.
ENTRYPOINT ["python", "scripts/run_daily.py"]
CMD ["--profiles", "cs", "--us_only", "--no_post"]
