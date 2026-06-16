# syntax=docker/dockerfile:1.7
# --- Manuscript Editor Pro -------------------------------------------
# Multi-stage build: install deps in a builder, then copy into a slim
# runtime image. Runs as a non-root user. Healthchecks Streamlit.
# ---------------------------------------------------------------------

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps for psycopg/bcrypt wheels; build-essential kept for any
# source-only wheels (none expected with the pinned versions).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8501 \
    DATA_DIR=/data \
    OUTPUT_DIR=/data/outbound \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=50 \
    LLM_CONFIG_LOCKED=1

# libpq runtime for psycopg
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --shell /bin/bash app

COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=app:app . /app

# Persistent data + outputs live on a mounted volume.
RUN mkdir -p /data/outbound && chown -R app:app /data

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent http://localhost:8501/_stcore/health || exit 1

CMD ["sh", "-c", "streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false"]
