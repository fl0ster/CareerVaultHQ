from fastapi import APIRouter

from app.api.routes import candidate_profile, health, jobs, latex, scrape, work_history

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(latex.router, prefix="/latex", tags=["latex"])
api_router.include_router(scrape.router, prefix="/scrape", tags=["scrape"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(work_history.router, prefix="/work-history", tags=["work-history"])
api_router.include_router(
    candidate_profile.router, prefix="/candidate-profile", tags=["candidate-profile"]
)
