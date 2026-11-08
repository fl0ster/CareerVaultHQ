# syntax=docker/dockerfile:1.7
#
# Multi-arch image for CareerVaultHQ (FastAPI API + built React/Vite frontend).
# Targets linux/arm/v7 (Raspberry Pi 2) but builds for any platform.
#
# Build on your workstation and run on the Pi:
#   docker buildx build --platform linux/arm/v7 -t careervaulthq:latest --load .
#   docker save careervaulthq:latest | gzip > careervaulthq.tar.gz
#   scp careervaulthq.tar.gz pi@raspberrypi:~ && ssh pi@raspberrypi 'gunzip -c careervaulthq.tar.gz | docker load'

# ---------- Stage 1: build the frontend (runs natively on the build host) ----------
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: runtime image (target platform, e.g. linux/arm/v7) ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime dependencies from pyproject (cached separately from app code).
COPY backend/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -r requirements.txt \
    && rm requirements.txt

COPY backend/app ./app
COPY --from=frontend /src/dist ./frontend/dist

# Runtime configuration (override with -e / compose environment).
ENV HOST=0.0.0.0 \
    PORT=8000 \
    FRONTEND_DIST=/app/frontend/dist \
    CORS_ORIGINS=""

RUN useradd --system --uid 1001 --create-home appuser \
    && mkdir -p /data && chown appuser:appuser /data
USER appuser
VOLUME ["/data"]

EXPOSE 8000

# HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
#    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
