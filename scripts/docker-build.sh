#!/usr/bin/env sh
# Cross-build the image for Raspberry Pi 2 (ARMv7) and export it as a tarball.
# Usage: scripts/build-pi.sh [tag]            -> careervaulthq-<tag>.tar.gz
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

TAG="${1:-latest}"
IMAGE="careervaulthq:${TAG}"
OUT_FOLDER="build"
OUT="${OUT_FOLDER}/careervaulthq-${TAG}.tar.gz"

mkdir -p "${OUT_FOLDER}"

docker buildx build --platform linux/arm/v7 -t "${IMAGE}" --load .
docker save "${IMAGE}" | gzip > "${OUT}"
echo "Wrote ${OUT}"
echo "Copy to the Pi and load it:  scp ${OUT} pi@raspberrypi:~ && ssh pi@raspberrypi 'gunzip -c ${OUT} | docker load'"
