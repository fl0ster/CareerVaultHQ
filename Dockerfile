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

# TeX Live for the LaTeX -> PDF worker (app/workers/latex2pdf.py, app/tasks/latex.py).
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
#
# mirrors.ctan.org redirects to a random mirror, and some of them have broken TLS chains
# or lag behind, so pinned, reliable mirrors are tried first with the redirector as a
# last resort. Space-separated; override with --build-arg CTAN_MIRRORS="...".
ARG CTAN_MIRRORS="https://ftp.fau.de/ctan https://mirrors.mit.edu/CTAN https://mirrors.ctan.org"
RUN <<'EOF'
set -eu
TEXMFLOCAL="$(kpsewhich -var-value TEXMFLOCAL)"
mkdir -p "$TEXMFLOCAL/tex/latex/enumitem" "$TEXMFLOCAL/tex/latex/fontaxes" /tmp/ctan
python - "$CTAN_MIRRORS" "$TEXMFLOCAL" <<'PY'
import io, sys, time, urllib.request, zipfile

mirrors, texmf = sys.argv[1].split(), sys.argv[2]

def fetch(path, attempts=2):
    errors = []
    for mirror in mirrors:
        for _ in range(attempts):
            url = f"{mirror}/{path}"
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    print(f"fetched {url}", flush=True)
                    return response.read()
            except Exception as exc:  # noqa: BLE001 - any failure -> try next mirror
                errors.append(f"{url}: {exc}")
                print(f"failed  {url}: {exc}", file=sys.stderr, flush=True)
                time.sleep(2)
    sys.exit("could not download " + path + ":\n  " + "\n  ".join(errors))

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

# Default: the API. The LaTeX worker runs from the same image with
#   command: ["python", "-m", "app.workers.latex2pdf"]   (see docker-compose.yml)
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
