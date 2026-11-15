"""The full video pass (BUILD_SPEC 7.3): Gemini watches the proxy once."""

from app.services.analysis import run_analysis
from app.services.events.base import CallRecord, Detection, DetectionContext
from app.services.llm.base import LLMError


class GeminiDetector:
    id = "gemini"

    def enabled_for(self, ctx: DetectionContext) -> bool:
        return ctx.video_provider is not None

    async def detect(self, ctx: DetectionContext) -> list[Detection]:
        assert ctx.video_provider is not None
        try:
            run = await run_analysis(
                ctx.video_provider, ctx.proxy, ctx.preset, ctx.video,
                fps=ctx.fps, media_resolution=ctx.media_resolution, playbook=ctx.playbook,
            )
        except LLMError as exc:
            ctx.on_call(CallRecord("gemini", "", "analysis", getattr(exc, "prompt", ""), status=f"error: {exc}"[:500]))
            raise
        ctx.on_call(CallRecord(
            provider="gemini", model=run.model, purpose="analysis", prompt=run.prompt,
            tokens_in=run.usage.get("total_input_tokens"), tokens_out=run.usage.get("total_output_tokens"),
            latency_ms=round(run.latency_s * 1000),
        ))
        ctx.outputs[self.id] = run
        return [
            Detection(
                t_start=e.t_start, t_end=e.t_end, type=e.type, label=e.label, confidence=e.confidence,
                intensity=e.intensity, crop_safe_9x16=e.crop_safe_9x16, detector=self.id,
            )
            for e in run.analysis.events
        ]
