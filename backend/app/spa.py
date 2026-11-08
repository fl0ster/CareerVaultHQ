"""Serve the built React/Vite frontend as a single-page application.

Static assets under ``frontend/dist`` are served directly. Any other
non-API GET request falls back to ``index.html`` so client-side routing
works on hard refresh. If the dist folder does not exist (e.g. during
development when Vite serves the frontend itself) nothing is mounted.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, dist_dir: Path, api_prefix: str) -> None:
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        # Hashed Vite build assets; safe to cache aggressively.
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str):
        if full_path.startswith(api_prefix.lstrip("/")):
            raise HTTPException(status_code=404)

        candidate = (dist_dir / full_path).resolve()
        if (
            full_path
            and candidate.is_relative_to(dist_dir.resolve())
            and candidate.is_file()
        ):
            return FileResponse(candidate)

        return FileResponse(index_file)
