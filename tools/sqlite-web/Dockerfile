# sqlite-web (browser UI for SQLite) built from the multi-arch Python base so it
# runs on the Raspberry Pi (arm/v7, arm64). The upstream coleifer/sqlite-web
# image is amd64-only.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir sqlite-web
EXPOSE 8080
ENTRYPOINT ["sqlite_web", "--host", "0.0.0.0", "--port", "8080"]
