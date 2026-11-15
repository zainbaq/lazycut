"""In-process job runner and the per-video update stream (BUILD_SPEC 7.11).

Jobs are asyncio tasks tracked in the `job` table. Each handler gets a `JobContext`
to report progress; every change is pushed to the video's SSE subscribers.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine
from sqlmodel import select

from app.db import session
from app.models import Job, utc_now

log = logging.getLogger(__name__)

INTERRUPTED = "Interrupted by a restart"


class Bus:
    """Fan-out of live events per video. Nothing is kept: a new subscriber sees only what follows."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, video_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.setdefault(video_id, set()).add(queue)
        return queue

    def unsubscribe(self, video_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(video_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subs.pop(video_id, None)

    def publish(self, video_id: str | None, kind: str, data: Any) -> None:
        if video_id is None:
            return
        message = f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        for queue in list(self._subs.get(video_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # a stalled client; it refetches state on reconnect
                log.warning("Dropping an update for a slow subscriber of video %s", video_id)


def job_dict(job: Job) -> dict:
    return job.model_dump()


@dataclass
class JobContext:
    runner: "JobRunner"
    job_id: str
    video_id: str | None
    kind: str
    options: dict = field(default_factory=dict)

    @property
    def engine(self) -> Engine:
        return self.runner.engine

    def publish(self, kind: str, data: Any) -> None:
        self.runner.bus.publish(self.video_id, kind, data)

    def progress(self, progress: float | None = None, message: str | None = None) -> None:
        self.runner.update(self.job_id, progress=progress, message=message)


Handler = Callable[[JobContext], Awaitable[None]]


class JobRunner:
    def __init__(self, engine: Engine, bus: Bus, deps: Any = None) -> None:
        self.engine = engine
        self.bus = bus
        self.deps = deps  # what handlers need besides the database (settings, providers)
        self.handlers: dict[str, Handler] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._stopping = False

    def register(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def recover(self) -> int:
        """Mark jobs that a restart killed. Returns how many there were."""
        with session(self.engine) as s:
            stale = s.exec(select(Job).where(Job.status.in_(("queued", "running")))).all()
            for job in stale:
                job.status, job.error, job.message, job.updated_at = "error", INTERRUPTED, None, utc_now()
                s.add(job)
            s.commit()
        return len(stale)

    def running(self, video_id: str, kind: str) -> Job | None:
        with session(self.engine) as s:
            return s.exec(
                select(Job).where(Job.video_id == video_id, Job.kind == kind, Job.status.in_(("queued", "running")))
            ).first()

    def start(self, kind: str, video_id: str | None, **options: Any) -> Job:
        """Queue a job. Call it on the event loop (from async code), never from a worker thread."""
        if kind not in self.handlers:
            raise KeyError(f"no handler for job kind `{kind}`")
        job = Job(video_id=video_id, kind=kind)
        with session(self.engine) as s:
            s.add(job)
            s.commit()
        self.bus.publish(video_id, "job.progress", job_dict(job))
        ctx = JobContext(self, job.id, video_id, kind, options)
        self.tasks[job.id] = asyncio.create_task(self._run(ctx), name=f"job:{kind}:{job.id}")
        return job

    def update(self, job_id: str, **changes: Any) -> Job | None:
        with session(self.engine) as s:
            job = s.get(Job, job_id)
            if job is None:  # the video and its jobs were deleted
                return None
            for key, value in changes.items():
                if value is not None or key in {"error"}:
                    setattr(job, key, value)
            job.updated_at = utc_now()
            s.add(job)
            s.commit()
        kind = {"done": "job.done", "error": "job.error"}.get(job.status, "job.progress")
        self.bus.publish(job.video_id, kind, job_dict(job))
        return job

    async def _run(self, ctx: JobContext) -> None:
        try:
            self.update(ctx.job_id, status="running")
            await self.handlers[ctx.kind](ctx)
            self.update(ctx.job_id, status="done", progress=1.0)
        except asyncio.CancelledError:
            self.update(ctx.job_id, status="error", error=INTERRUPTED if self._stopping else "Stopped")
            raise
        except Exception as exc:
            log.exception("Job %s (%s) failed", ctx.job_id, ctx.kind)
            self.update(ctx.job_id, status="error", error=str(exc) or type(exc).__name__)
        finally:
            self.tasks.pop(ctx.job_id, None)

    async def cancel_for_video(self, video_id: str) -> None:
        """Stop every running job of a video, and wait until they have stopped."""
        with session(self.engine) as s:
            ids = s.exec(select(Job.id).where(Job.video_id == video_id)).all()
        tasks = [self.tasks[i] for i in ids if i in self.tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        self._stopping = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
