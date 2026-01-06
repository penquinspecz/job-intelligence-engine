FROM python:3.11-slim

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and source
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs
# Optionally bake snapshots for offline/snapshot runs (other data excluded by .dockerignore)
COPY data/openai_snapshots /app/data/openai_snapshots
COPY data/candidate_profile.json /app/data/candidate_profile.json

# Install project in editable mode (no dev extras)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

# Expect /app/data to be a mounted volume; runtime code will ensure dirs
VOLUME ["/app/data"]

ENTRYPOINT ["python", "scripts/run_daily.py"]
CMD ["--profiles", "cs", "--us_only", "--no_post"]

