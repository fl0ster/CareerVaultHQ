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

# TeX Live for the LaTeX -> PDF worker (app/tasks/latex.py). Override with
#   docker build --build-arg TEXLIVE_PACKAGES="..." .
ARG TEXLIVE_PACKAGES="texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ${TEXLIVE_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

# The CV template uses the carlito font (Calibri clone). Debian only ships its LaTeX support
# inside texlive-fonts-extra (>1 GB), so fetch just that package's TDS zip from CTAN into
# TEXMFLOCAL and register its font map. Python (already in the image) does the download + unzip.
ARG CARLITO_TDS_URL="https://mirrors.ctan.org/install/fonts/carlito.tds.zip"
RUN <<'EOF'
set -eu
TEXMFLOCAL="$(kpsewhich -var-value TEXMFLOCAL)"
mkdir -p "$TEXMFLOCAL"
python - "$CARLITO_TDS_URL" "$TEXMFLOCAL" <<'PY'
import io, sys, urllib.request, zipfile

url, texmf = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=120) as response:
    zipfile.ZipFile(io.BytesIO(response.read())).extractall(texmf)
PY
mktexlsr
updmap-sys --enable Map=carlito.map
kpsewhich carlito.sty >/dev/null
EOF

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
    CORS_ORIGINS="" \
    REDIS_URL=redis://redis:6379/0 \
    LATEX_UPLOAD_ROOT=/data/static/uploads/latex \
    LATEX_JOBS_ROOT=/data/static/jobs/latex

RUN useradd --system --uid 1001 --create-home appuser \
    && mkdir -p /data && chown appuser:appuser /data
USER appuser
VOLUME ["/data"]

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
