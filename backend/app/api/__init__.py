from fastapi import APIRouter

from app.api.routes import health, jobs, latex, scrape

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(latex.router, prefix="/latex", tags=["latex"])
api_router.include_router(scrape.router, prefix="/scrape", tags=["scrape"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
