import asyncio
import random

from google.genai import types

from ...adk_common.utils.utils_logging import Severity, log_message
from ...state import VEO_MODEL
from .core import client, ensure_gs_uri

def _sanitize_veo_prompt(prompt: str) -> str:
    return prompt.replace("\n", " ").strip()[:2000]

async def _generate_single_veo_clip(prompt: str, start_frame_gcs_uri: str,
                                     clip_duration: int = 6, end_frame_gcs_uri: str | None = None,
                                     label: str = "clip", aspect_ratio: str = "16:9") -> bytes | None:
    """Generates a video clip using VEO, supporting long polling for production quality."""
    log_message(f"📹 [VEO GEN ARGS] Label: {label} | Duration: {clip_duration}s | Aspect: {aspect_ratio}", Severity.INFO)
    log_message(f"📝 [VEO GEN PROMPT]: {prompt}", Severity.INFO)
    log_message(f"🖼️ [VEO GEN START FRAME]: {start_frame_gcs_uri}", Severity.INFO)
    
    mode = "interpolation" if end_frame_gcs_uri else "i2v"
    try:
        img_mime = "image/png"
        last_frame = types.Image(gcs_uri=ensure_gs_uri(end_frame_gcs_uri), mime_type=img_mime) if end_frame_gcs_uri else None

        veo_config = types.GenerateVideosConfig(
            number_of_videos=1, 
            duration_seconds=clip_duration, 
            aspect_ratio=aspect_ratio,
            last_frame=last_frame,
            generate_audio=False,
            person_generation="allow_all",
        )

        log_message(f"VEO {label} ({mode}): submitting job...", Severity.INFO)

        operation = None
        for veo_attempt in range(3):
            try:
                operation = client.models.generate_videos(
                    model=VEO_MODEL,
                    prompt=prompt,
                    image=types.Image(gcs_uri=ensure_gs_uri(start_frame_gcs_uri), mime_type=img_mime),
                    config=veo_config,
                )
                break
            except Exception as submit_err:
                if "429" in str(submit_err) or "RESOURCE_EXHAUSTED" in str(submit_err):
                    backoff = (2 ** veo_attempt) * 5 + random.uniform(0, 3)
                    await asyncio.sleep(backoff)
                else:
                    raise

        if not operation:
            return None

        # Source Polling Pipeline: Increase to 120 polls (20 minutes max) to support heavy generation
        for poll in range(120):
            if operation.done:
                break
            # Status update every 30s
            if poll % 3 == 0:
                log_message(f"VEO {label}: still processing (poll {poll+1}/120)...", Severity.INFO)
            await asyncio.sleep(10)
            operation = client.operations.get(operation)

        if not operation.done or operation.error:
            log_message(f"VEO {label} failed: {operation.error if operation.error else 'Timeout after 20 mins'}", Severity.ERROR)
            return None

        if not operation.response or not operation.response.generated_videos:
            return None

        generated = operation.response.generated_videos[0]
        if not generated.video or not generated.video.video_bytes:
            return None

        return generated.video.video_bytes
    except Exception as e:
        log_message(f"VEO {label} exception: {e}", Severity.ERROR)
        return None
