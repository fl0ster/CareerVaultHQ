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

# TeX Live for the LaTeX -> PDF worker (app/tasks/latex.py).
# Only base + recommended: that covers geometry, hyperref, xcolor, microtype and
# koma-script (scrextend). The few packages the CV template needs from the >1 GB
# texlive-latex-extra / texlive-fonts-extra (enumitem, fontaxes, carlito) are pulled
# straight from CTAN below instead. Override with
#   docker build --build-arg TEXLIVE_PACKAGES="..." .
ARG TEXLIVE_PACKAGES="texlive-latex-base texlive-latex-recommended"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ${TEXLIVE_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

# Extra LaTeX packages fetched from CTAN into TEXMFLOCAL (Python, already in the image,
# does the download/unzip):
#   carlito  - Calibri clone used by the CV template; TDS zip, needs its font map enabled
#   fontaxes - required by carlito.sty; ships as .dtx/.ins so it is unpacked with tex
#   enumitem - compact bullet lists; a single .sty
ARG CTAN_MIRROR="https://mirrors.ctan.org"
RUN <<'EOF'
set -eu
TEXMFLOCAL="$(kpsewhich -var-value TEXMFLOCAL)"
mkdir -p "$TEXMFLOCAL/tex/latex/enumitem" "$TEXMFLOCAL/tex/latex/fontaxes" /tmp/ctan
python - "$CTAN_MIRROR" "$TEXMFLOCAL" <<'PY'
import io, sys, urllib.request, zipfile

mirror, texmf = sys.argv[1], sys.argv[2]

def fetch(path):
    with urllib.request.urlopen(f"{mirror}/{path}", timeout=120) as response:
        return response.read()

zipfile.ZipFile(io.BytesIO(fetch("install/fonts/carlito.tds.zip"))).extractall(texmf)
zipfile.ZipFile(io.BytesIO(fetch("macros/latex/contrib/fontaxes.zip"))).extractall("/tmp/ctan")
with open(f"{texmf}/tex/latex/enumitem/enumitem.sty", "wb") as f:
    f.write(fetch("macros/latex/contrib/enumitem/enumitem.sty"))
PY
(cd /tmp/ctan/fontaxes && tex -interaction=batchmode fontaxes.ins >/dev/null && cp ./*.sty "$TEXMFLOCAL/tex/latex/fontaxes/")
rm -rf /tmp/ctan
mktexlsr
updmap-sys --enable Map=carlito.map
kpsewhich carlito.sty fontaxes.sty enumitem.sty >/dev/null
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
