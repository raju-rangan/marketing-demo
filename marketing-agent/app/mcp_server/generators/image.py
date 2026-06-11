import asyncio
import random
import traceback

from google.genai import types

from app.adk_common.utils.utils_logging import Severity, log_message
from app.state import GEMINI_IMAGE_MODEL
from app.mcp_server.generators.core import client

def _get_image_mime_type(data: bytes) -> str:
    """Detects image mime type from bytes."""
    if data.startswith(b'\x89PNG'): return "image/png"
    if data.startswith(b'\xff\xd8'): return "image/jpeg"
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return "image/webp"
    return "image/png"

async def _generate_gemini_image(prompt: str, reference_images: list[bytes], label: str = "image", aspect_ratio: str = None) -> bytes | None:
    safe_prompt = prompt + (
        "\n\nCRITICAL NEGATIVE DIRECTIVE: "
        "Do NOT render any storyboard descriptions, act summaries, scene labels, or descriptive text (e.g., 'THE ENTREPRENEUR IS WALKING...') as literal text in the image. "
        "Do NOT render color palettes, swatches, hex codes, or reference UI elements on the canvas. "
        "The image should ONLY contain the visual scene. If text is not explicitly requested as an object within the scene (like a sign), do not render any text at all."
    )
    
    log_message(f"🖼️ [`IMAGE GEN ARGS]` Label: {label} | Aspect Ratio: {aspect_ratio}", Severity.INFO)
    log_message(f"📝 [IMAGE GEN PROMPT]: {safe_prompt}", Severity.INFO)
    log_message(f"📎 [IMAGE GEN REFS]: {len(reference_images)} images attached", Severity.INFO)

    parts = [types.Part.from_bytes(data=img, mime_type=_get_image_mime_type(img)) for img in reference_images if img]
    parts.append(types.Part.from_text(text=safe_prompt))

    contents = [types.Content(role="user", parts=parts)]
    image_config = types.ImageConfig(aspect_ratio=aspect_ratio) if aspect_ratio else None

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
        image_config=image_config,
    )

    for attempt in range(5):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=GEMINI_IMAGE_MODEL,
                    contents=contents,
                    config=config,
                ),
                timeout=120,
            )
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data
        except Exception as e:
            error_str = str(e)
            full_error = traceback.format_exc()
            if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str) and attempt < 4:
                await asyncio.sleep((2 ** attempt) * 2 + random.uniform(0, 3))
                continue
            log_message(f"{label} failed. Type: {type(e).__name__}, Msg: {error_str}\nTraceback:\n{full_error}", Severity.ERROR)
            if attempt == 4: raise e
        
        await asyncio.sleep((attempt + 1) * 2)
    return None
