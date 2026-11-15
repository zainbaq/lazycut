import asyncio

from app.db import init_db, make_engine, session
from app.models import Job, Video
from app.services.jobs import INTERRUPTED, Bus, JobRunner


def runner(tmp_path) -> JobRunner:
    engine = make_engine(tmp_path / "app.db")
    init_db(engine)
    return JobRunner(engine, Bus())


async def wait(r: JobRunner, job_id: str) -> Job:
    for _ in range(200):
        with session(r.engine) as s:
            job = s.get(Job, job_id)
        if job.status in ("done", "error"):
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


async def test_jobs_report_progress_finish_and_fail(tmp_path):
    r = runner(tmp_path)
    with session(r.engine) as s:
        s.add(Video(id="v1", title="Test"))
        s.commit()
    queue = r.bus.subscribe("v1")

    async def ok(ctx):
        ctx.progress(0.5, "Halfway")

    async def broken(ctx):
        raise ValueError("ffmpeg failed")

    r.register("ok", ok)
    r.register("broken", broken)
    done = await wait(r, r.start("ok", "v1").id)
    failed = await wait(r, r.start("broken", "v1").id)

    assert (done.status, done.progress, done.message) == ("done", 1.0, "Halfway")
    assert (failed.status, failed.error) == ("error", "ffmpeg failed")
    kinds = []
    while not queue.empty():
        kinds.append(queue.get_nowait().split("\n")[0])
    assert kinds[-1] == "event: job.error" and "event: job.done" in kinds


async def test_a_restart_marks_unfinished_jobs(tmp_path):
    r = runner(tmp_path)
    with session(r.engine) as s:
        s.add_all([Job(kind="import", status="running"), Job(kind="analysis", status="queued"), Job(kind="x", status="done")])
        s.commit()
    assert r.recover() == 2
    with session(r.engine) as s:
        assert sorted((j.status, j.error) for j in s.query(Job).all()) == [
            ("done", None), ("error", INTERRUPTED), ("error", INTERRUPTED),
        ]


async def test_shutdown_stops_running_jobs_as_interrupted(tmp_path):
    r = runner(tmp_path)

    async def slow(ctx):
        await asyncio.sleep(30)

    r.register("slow", slow)
    job = r.start("slow", None)
    await asyncio.sleep(0.05)
    await r.shutdown()
    with session(r.engine) as s:
        assert s.get(Job, job.id).error == INTERRUPTED
