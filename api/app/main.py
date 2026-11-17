import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db, make_engine
from app.routers import clips, config, events, jobs, library, packages, research, thumbnails, videos
from app.services.clip_jobs import clip_export_job, clip_find_job, clip_package_job, clip_refine_job
from app.services.higgsfield import Higgsfield
from app.services.jobs import Bus, JobRunner
from app.services.llm.anthropic import ClaudeProvider
from app.services.llm.base import VideoProvider
from app.services.llm.gemini import GeminiProvider
from app.services.pipeline import Deps, analysis_job, import_job, package_job, research_job
from app.services.search_demand import YouTubeSuggest
from app.services.thumbnail_jobs import thumb_frames_job, thumbnail_job
from app.settings import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def gemini_factory(settings: Settings) -> Callable[[Callable[[str], None]], VideoProvider | None]:
    def make(on_status: Callable[[str], None]) -> VideoProvider | None:
        if not settings.gemini_api_key:
            return None
        # Paid calls: start in the background and poll, and retry at most once (BUILD_SPEC 12).
        return GeminiProvider(
            settings.gemini_api_key, settings.gemini_video_model,
            on_status=on_status, max_attempts=2, request_timeout_s=1800, background=True,
        )

    return make


def claude_factory(settings: Settings) -> Callable[[], ClaudeProvider | None]:
    cache: list[ClaudeProvider] = []

    def make() -> ClaudeProvider | None:
        if not settings.anthropic_api_key:
            return None
        if not cache:
            cache.append(ClaudeProvider(settings.anthropic_api_key, settings.anthropic_model))
        return cache[0]

    return make


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.db_path)
    init_db(engine)
    bus = Bus()
    suggest = YouTubeSuggest() if settings.search_demand == "youtube_suggest" else None
    images = (Higgsfield(settings.higgsfield_credential, settings.higgsfield_base_url)
              if settings.higgsfield_credential else None)
    runner = JobRunner(engine, bus, Deps(settings, gemini_factory(settings), claude_factory(settings),
                                         suggest_client=lambda: suggest, image_client=lambda: images))
    runner.register("import", import_job)
    runner.register("analysis", analysis_job)
    runner.register("research", research_job)
    runner.register("package", package_job)
    runner.register("thumbnail_frames", thumb_frames_job)
    runner.register("thumbnail", thumbnail_job)
    runner.register("clip_find", clip_find_job)
    runner.register("clip_export", clip_export_job)
    runner.register("clip_package", clip_package_job)
    runner.register("clip_refine", clip_refine_job)
    runner.recover()
    app.state.engine, app.state.bus, app.state.runner = engine, bus, runner
    yield
    await runner.shutdown()
    engine.dispose()


app = FastAPI(title="LazyCut API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition"],
)
app.include_router(config.router)
app.include_router(videos.router)
app.include_router(jobs.router)
app.include_router(events.router)
app.include_router(clips.router)
app.include_router(research.router)
app.include_router(packages.router)
app.include_router(library.router)
app.include_router(thumbnails.router)
