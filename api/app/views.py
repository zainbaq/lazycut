"""JSON payloads the web app reads (`api/API_SHAPES.md`)."""

from sqlmodel import Session, col, select

from app.models import Analysis, Event, Fact, Job, Package, Video
from app.services.presets import Preset


def latest_jobs(s: Session, video_id: str) -> list[Job]:
    jobs = s.exec(select(Job).where(Job.video_id == video_id).order_by(col(Job.created_at).desc(), col(Job.id))).all()
    latest: dict[str, Job] = {}
    for job in jobs:
        latest.setdefault(job.kind, job)
    return sorted(latest.values(), key=lambda j: j.created_at)


def display_status(s: Session, video: Video, jobs: list[Job], preset: Preset | None) -> str:
    active = {j.kind for j in jobs if j.status in ("queued", "running")}
    if video.status == "importing" or "import" in active:
        return "importing"
    if video.status == "error":
        return "error"
    if "analysis" in active:
        return "analyzing"
    if video.published_at:
        return "published"
    if s.exec(select(Package.id).where(Package.video_id == video.id)).first():
        return "packaged"
    required = {f.key for f in preset.facts if f.required} if preset else set()
    if required:
        confirmed = set(s.exec(select(Fact.key).where(Fact.video_id == video.id, Fact.confirmed)).all())
        if not required <= confirmed:
            return "needs_confirmation"
    return "ready"


def video_dict(s: Session, video: Video, presets: dict[str, Preset]) -> dict:
    jobs = latest_jobs(s, video.id)
    analysis = s.exec(
        select(Analysis).where(Analysis.video_id == video.id).order_by(col(Analysis.created_at).desc())
    ).first()
    summary = None
    if analysis is not None:
        count = len(s.exec(select(Event.id).where(Event.video_id == video.id, Event.hidden == False)).all())
        summary = {
            "id": analysis.id, "model": analysis.model, "fps": analysis.fps,
            "created_at": analysis.created_at, "event_count": count,
        }
    data = video.model_dump(exclude={"source_path", "proxy_path"})
    return data | {
        "display_status": display_status(s, video, jobs, presets.get(video.preset_id)),
        "analysis": summary,
        "jobs": [j.model_dump() for j in jobs],
        "media_url": f"/videos/{video.id}/media",
    }

