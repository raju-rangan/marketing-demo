# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import random
import time
from typing import List, Optional
from google.adk.tools.tool_context import ToolContext
from ...adk_common.dtos.generated_media import GeneratedMedia
from ...adk_common.utils import utils_agents, utils_gcs, utils_prompts
from ...adk_common.utils.utils_logging import Severity, log_message, log_status
from google import genai
from google.genai import types

from ...state import (
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_BUCKET_ARTIFACTS,
    GEMINI_IMAGE_MODEL,
    GEMINI_TTS_MODEL,
    GEMINI_TTS_VOICE,
    VEO_MODEL,
    LYRIA_MODEL,
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    ASSET_REGISTRY_STATE_KEY,
    STORYBOARD_ITERATION_STATE_KEY,
    VOICEOVER_STYLES,
    CHOSEN_VOICEOVER_STYLE_STATE_KEY,
)

# Initialize GenAI Client - Force global location to match source and support preview models
client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")

def ensure_gs_uri(uri: str) -> str:
    """Converts authenticated HTTPS URLs back to raw gs:// URIs for the GenAI SDK."""
    if not uri: return uri
    if uri.startswith("https://storage.cloud.google.com/"):
        return uri.replace("https://storage.cloud.google.com/", "gs://")
    if uri.startswith("https://storage.googleapis.com/"):
        return uri.replace("https://storage.googleapis.com/", "gs://")
    return uri

STORYLINE_MODEL = "gemini-3.5-flash"

_VARIATION_STYLES = [
    "PREMIUM STUDIO — Clean white/grey studio with precise product lighting, geometric shadows, ultra-minimal Apple-style composition. The product floats in perfect light.",
    "LIFESTYLE IN ACTION — The product being used in its natural environment by a real person. Warm, candid, aspirational. Think 'a day in the life' with the product as the hero.",
    "URBAN NIGHT — Dramatic cityscape at night with neon reflections, rain-slicked streets, moody teal-and-orange color grade. The product glows against the dark city.",
    "GOLDEN HOUR EPIC — Sweeping outdoor landscape at golden hour with warm amber backlighting, lens flares, and dramatic long shadows. Cinematic wide-angle grandeur.",
    "TECH NOIR — Dark, sophisticated, high-contrast. Brushed metal surfaces, precision engineering close-ups, holographic UI elements. The product as cutting-edge technology.",
    "COZY HOME — Warm, inviting home environment. Soft textures, natural wood, ambient lighting. The product fits seamlessly into a beautiful living space.",
    "AERIAL ADVENTURE — Bird's-eye or drone perspective showing the product in a vast, breathtaking outdoor environment. Scale and drama.",
    "INDUSTRIAL LUXE — Raw concrete, exposed steel, and architectural brutalism contrasted with the product's refined design. Moody volumetric lighting.",
    "NATURE MACRO — Extreme close-up details of the product surrounded by organic textures (water droplets, leaves, sand). Hyper-detailed macro photography.",
    "NEON FUTURISM — Cyberpunk-inspired with holographic accents, electric blue and magenta lighting, reflective surfaces. The product from 2035.",
    "CULINARY ARTISTRY — Rich textures, steam, condensation, warm tones. Food/beverage products presented like Michelin-star plating. For non-food: the product in an upscale dining context.",
    "SPORT PERFORMANCE — Dynamic motion blur, sweat, intensity. The product captured mid-action. Speed ramps, dramatic angles, peak performance moment.",
]

def _get_brand_wall_directive(company_name: str, guidelines: str = "") -> str:
    """Returns strict exclusionary rules and visual requirements for media models."""
    directive = f"\n\n**BRAND MANDATE: {company_name.upper()}**:\n"
    directive += f"- You represent '{company_name}'. DO NOT mention competitors or parent brands.\n"
    
    if guidelines:
        directive += f"- Adhere to these brand visual rules: {guidelines[:1000]}\n"
    
    return directive

async def _retry_generate_content(model, contents, config, label="LLM", max_attempts=4):
    if isinstance(contents, str):
        log_message(f"🤖 [GEN CONTENT PROMPT - {label}]: {contents[:1000]}...", Severity.INFO)
    for attempt in range(max_attempts):
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            is_429 = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_429 and attempt < max_attempts - 1:
                backoff = (2 ** attempt) * 3 + random.uniform(0, 2)
                log_message(f"{label}: 429 retry {attempt+1}, backoff {backoff:.1f}s", Severity.WARNING)
                await asyncio.sleep(backoff)
            elif attempt < max_attempts - 1:
                await asyncio.sleep(2)
            else:
                raise

def _get_image_mime_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG'): return "image/png"
    if data.startswith(b'\xff\xd8'): return "image/jpeg"
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return "image/webp"
    return "image/png"

async def _generate_gemini_image(prompt: str, reference_images: list[bytes], label: str = "image", aspect_ratio: str = None) -> bytes | None:
    safe_prompt = prompt + (
        "\n\nCRITICAL NEGATIVE DIRECTIVE: Do NOT render any of my stylistic, formatting, or layout instructions (e.g., 'mobile first typography', 'extreme readability', 'centered', 'bold claim') as literal text in the image. Any text in the image MUST ONLY be the actual educational content, titles, or data labels. Never write metadata or instructions on the canvas."
    )
    
    log_message(f"🖼️ [`IMAGE GEN ARGS]` Label: {label} | Aspect Ratio: {aspect_ratio}", Severity.INFO)
    log_message(f"📝 [IMAGE GEN PROMPT]: {safe_prompt}", Severity.INFO)
    log_message(f"📎 [IMAGE GEN REFS]: {len(reference_images)} images attached", Severity.INFO)

    parts = [types.Part.from_bytes(data=img, mime_type=_get_image_mime_type(img)) for img in reference_images if img]
    parts.append(types.Part.from_text(text=safe_prompt))

    contents = [types.Content(role="user", parts=parts)]

    image_config = None
    if aspect_ratio:
        image_config = types.ImageConfig(aspect_ratio=aspect_ratio)

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
        image_config=image_config
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
            import traceback
            error_str = str(e)
            full_error = traceback.format_exc()
            is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
            if is_429 and attempt < 4:
                await asyncio.sleep((2 ** attempt) * 2 + random.uniform(0, 3))
                continue
            log_message(f"{label} failed. Type: {type(e).__name__}, Msg: {error_str}\nTraceback:\n{full_error}", Severity.ERROR)
            if attempt == 4: raise e
        
        await asyncio.sleep((attempt + 1) * 2)
    return None

def _sanitize_veo_prompt(prompt: str) -> str:
    return prompt.replace("\n", " ").strip()[:2000]

async def _generate_single_veo_clip(prompt: str, start_frame_gcs_uri: str,
                                     clip_duration: int = 6, end_frame_gcs_uri: str | None = None,
                                     label: str = "clip", aspect_ratio: str = "16:9") -> bytes | None:
    log_message(f"📹 [VEO GEN ARGS] Label: {label} | Duration: {clip_duration}s", Severity.INFO)
    log_message(f"📝 [VEO GEN PROMPT]: {prompt}", Severity.INFO)
    log_message(f"🖼️ [VEO GEN START FRAME]: {start_frame_gcs_uri}", Severity.INFO)
    log_message(f"📏 [VEO GEN ASPECT RATIO]: {aspect_ratio}", Severity.INFO)
    if end_frame_gcs_uri:
        log_message(f"🏁 [VEO GEN END FRAME]: {end_frame_gcs_uri}", Severity.INFO)

    mode = "interpolation" if end_frame_gcs_uri else "i2v"
    try:
        img_mime = "image/png"
        last_frame = None
        if end_frame_gcs_uri:
            last_frame = types.Image(gcs_uri=ensure_gs_uri(end_frame_gcs_uri), mime_type=img_mime)

        veo_config = types.GenerateVideosConfig(
            number_of_videos=1, duration_seconds=clip_duration, aspect_ratio=aspect_ratio,
            last_frame=last_frame,
            generate_audio=False,
            person_generation="allow_all",
        )

        log_message(f"VEO {label} ({mode}): submitting {clip_duration}s clip...", Severity.INFO)

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
                    log_message(f"VEO {label}: 429 backoff {backoff:.1f}s", Severity.WARNING)
                    await asyncio.sleep(backoff)
                else:
                    raise

        if not operation:
            return None

        for poll in range(80):
            if operation.done:
                break
            await asyncio.sleep(10)
            operation = client.operations.get(operation)

        if not operation.done or operation.error:
            log_message(f"VEO {label} failed: {operation.error if operation.error else 'Timeout'}", Severity.ERROR)
            return None

        if not operation.response or not operation.response.generated_videos:
            return None

        generated = operation.response.generated_videos[0]
        if not generated.video or not generated.video.video_bytes:
            return None

        log_message(f"VEO {label} success ({len(generated.video.video_bytes):,} bytes)", Severity.INFO)
        return generated.video.video_bytes
    except Exception as e:
        log_message(f"VEO {label} exception: {e}", Severity.ERROR)
        return None

async def _generate_lyria_music(lyria_prompt: str, product_name: str) -> bytes | None:
    log_message(f"🎼 [LYRIA GEN PROMPT]: {lyria_prompt}", Severity.INFO)
    try:
        if not lyria_prompt or len(lyria_prompt) < 20:
            lyria_prompt = (
                f"Cinematic instrumental that builds with the story — starts with intrigue and sophistication, "
                f"builds momentum with layered instruments, and finishes with a powerful, unforgettable crescendo. "
                f"Match the vibe of a premium {product_name} commercial. "
                f"STRICTLY INSTRUMENTAL — no vocals, no singing, no humming."
            )

        log_message(f"Lyria prompt: {lyria_prompt[:100]}...", Severity.INFO)

        response = await _retry_generate_content(
            model=LYRIA_MODEL,
            contents=lyria_prompt,
            config=types.GenerateContentConfig(response_modalities=["AUDIO", "TEXT"]),
            label="lyria-music",
        )
        
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    log_message(f"Lyria music generated: {len(part.inline_data.data) // 1024} KB", Severity.INFO)
                    return part.inline_data.data

        log_message("Lyria returned no audio", Severity.WARNING)
        return None
    except Exception as e:
        log_message(f"Lyria music generation failed: {e}", Severity.ERROR)
        return None

async def _generate_voiceover_audio(script: str, voice_name: str = None) -> bytes | None:
    log_message(f"🗣️ [TTS GEN SCRIPT]: {script[:500]}...", Severity.INFO)
    import io
    import wave

    def _pcm_to_wav(pcm_data: bytes, channels=1, rate=24000, sample_width=2) -> bytes:
        with io.BytesIO() as wav_io:
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(rate)
                wf.writeframes(pcm_data)
            return wav_io.getvalue()

    try:
        if not script or len(script.strip()) < 5:
            return None

        selected_voice = voice_name or "Puck"
        log_message(f"Generating voiceover using Gemini TTS voice '{selected_voice}' for script: {script[:50]}...", Severity.INFO)

        for attempt in range(3):
            try:
                def call_tts():
                    return client.models.generate_content(
                       model="gemini-3.1-flash-tts-preview",
                       contents=script,
                       config=types.GenerateContentConfig(
                          response_modalities=["AUDIO"],
                          speech_config=types.SpeechConfig(
                              voice_config=types.VoiceConfig(
                                 prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=selected_voice,
                                 )
                              )
                          ),
                       )
                    )

                response = await asyncio.to_thread(call_tts)
                
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            pcm_bytes = part.inline_data.data
                            log_message(f"Voiceover PCM generated: {len(pcm_bytes)} bytes", Severity.INFO)
                            wav_bytes = _pcm_to_wav(pcm_bytes)
                            return wav_bytes

                log_message(f"TTS attempt {attempt + 1}/3 returned no audio data.", Severity.WARNING)
            except Exception as e:
                log_message(f"TTS attempt {attempt + 1}/3 failed: {e}", Severity.WARNING)
            if attempt < 2:
                await asyncio.sleep(2)
        return None
    except Exception as e:
        log_message(f"Voiceover generation failed: {e}", Severity.ERROR)
        return None

def register_asset(tool_context: ToolContext, tag: str, gcs_uri: str):
    """Registers an asset in the session registry."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    registry[tag] = gcs_uri
    tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
    log_message(f"Registered asset: {tag} -> {gcs_uri}", Severity.INFO)

def resolve_asset_uris(tool_context: ToolContext, tags: Optional[List[str]] = None) -> List[str]:
    """Resolves a list of tags to URIs. Falls back to uploads or latest storyboard."""
    from ..misc import process_user_uploads
    process_user_uploads(tool_context)
    
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    
    if tags:
        resolved = []
        for t in tags:
            uri = registry.get(t)
            if uri: resolved.append(uri)
            else: log_message(f"Warning: Asset tag '{t}' not found in registry.", Severity.WARNING)
        if resolved: return resolved

    all_tags = list(registry.keys())
    uploads = sorted([t for t in all_tags if t.startswith("upload-")], 
                     key=lambda x: int(x.split("-")[1]))
    if uploads:
        return [registry[t] for t in uploads]

    latest_iter = tool_context.state.get(STORYBOARD_ITERATION_STATE_KEY, 0)
    if latest_iter > 0:
        pattern = f"v{latest_iter}-f"
        latest_frames = sorted([t for t in all_tags if t.startswith(pattern)],
                               key=lambda x: int(x.split("-f")[1]))
        return [registry[t] for t in latest_frames]

    return tool_context.state.get("STORYBOARD_KEYFRAMES", [])
