from fastapi import APIRouter, HTTPException, Request

from app.db import session
from app.models import Job

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    with session(request.app.state.engine) as s:
        job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    return job.model_dump()


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, request: Request) -> dict:
    runner = request.app.state.runner
    with session(request.app.state.engine) as s:
        job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    if job.status in ("queued", "running"):
        raise HTTPException(409, "This job is still running")
    if job.video_id and runner.running(job.video_id, job.kind):
        raise HTTPException(409, f"A {job.kind} job is already running for this video")
    if job.kind == "analysis" and not runner.deps.can_watch():
        raise HTTPException(409, "Set GEMINI_API_KEY in .env to analyze videos")
    return runner.start(job.kind, job.video_id).model_dump()
