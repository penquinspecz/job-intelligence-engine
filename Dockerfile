FROM python:3.11-slim

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency metadata first for better layer caching
COPY pyproject.toml /app/pyproject.toml
COPY requirements.txt /app/requirements.txt

# Install dependencies + dev test deps (no secrets required)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir -e ".[dev]"

# Copy project code
COPY src /app/src
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs
COPY tests /app/tests
# Optionally bake snapshots for offline/snapshot runs (other data excluded by .dockerignore)
COPY data/openai_snapshots /app/data/openai_snapshots
COPY data/candidate_profile.json /app/data/candidate_profile.json

# Run tests during build (deterministic, offline)
RUN python -m pytest -q

# Expect /app/data to be a mounted volume; runtime code will ensure dirs
VOLUME ["/app/data"]

# Default container behavior runs the daily pipeline, but ENTRYPOINT is python
# so you can run other scripts like:
#   docker run ... jobintel:local scripts/run_ai_augment.py
#   docker run ... jobintel:local scripts/score_jobs.py --profile cs --us_only
ENTRYPOINT ["python"]
CMD ["scripts/run_daily.py", "--profiles", "cs", "--us_only", "--no_post"]

