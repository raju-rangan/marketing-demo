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
import datetime
import json
import os
import random
import re
import string
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, cast

from google.adk.tools.tool_context import ToolContext
from google.adk.agents.readonly_context import ReadonlyContext
from .adk_common.dtos.generated_media import GeneratedMedia
from .adk_common.utils import ad_generation_constants, utils_agents, utils_gcs, utils_prompts
from .adk_common.utils.gemini_utils import generate_and_select_best_image
from .adk_common.utils.utils_logging import Severity, log_message
from google import genai
from google.genai import types

from .state import (
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_LOCATION,
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
    CUSTOMER_PERSONA_STATE_KEY,
    CHOSEN_CAMPAIGN_IDEA_STATE_KEY,
    OUTPUT_FOLDER,
    ASSET_REGISTRY_STATE_KEY,
    STORYBOARD_ITERATION_STATE_KEY,
    UPLOAD_COUNTER_STATE_KEY,
    VOICEOVER_STYLES,
    CHOSEN_VOICEOVER_STYLE_STATE_KEY,
)
from .utils_gcs import get_public_url, set_output_folder
from .shared_infra.utils_media import (
    stitch_videos,
    stitch_images,
    mix_audio_onto_video,
    overlay_logo_on_video,
    add_text_overlays,
    add_end_card_overlay,
)

...

async def create_image_composite(tool_context: ToolContext, image_urls: list[str]) -> dict:
    """Combines multiple images into a single horizontal composite (stitched) image for side-by-side review.
    
    Args:
        image_urls: A list of public GCS URLs for the images to be combined.
    """
    current_output_folder = set_output_folder(tool_context)
    log_message(f"Stitching {len(image_urls)} images into a composite...", Severity.INFO)

    try:
        image_bytes_list = []
        for url in image_urls:
            res = await utils_agents.load_resource(url, tool_context)
            if res:
                image_bytes_list.append(res.media_bytes)
            else:
                return {"status": "error", "details": f"Failed to load image at {url}"}

        stitched_bytes = stitch_images(image_bytes_list)
        if not stitched_bytes:
            return {"status": "error", "details": "Image stitching failed."}

        filename = f"composite_{int(time.time())}.png"
        media = GeneratedMedia(filename=filename, mime_type="image/png", media_bytes=stitched_bytes)
        saved = await utils_agents.save_to_artifact_and_render_asset(
            asset=media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        
        return {
            "status": "success",
            "composite_url": utils_gcs.normalize_to_gs_bucket_uri(saved.gcs_uri),
            "details": "Images stitched successfully into a side-by-side composite."
        }
    except Exception as e:
        log_message(f"Composite generation failed: {e}", Severity.ERROR)
        return {"status": "error", "details": str(e)}

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

STORYLINE_MODEL = "gemini-3.1-pro-preview"

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

# ============================================================
# Helper Functions
# ============================================================

def _get_brand_wall_directive(company_name: str) -> str:
    """Returns strict exclusionary rules to prevent brand bleeding."""
    if "chase" in company_name.lower():
        return (
            "\n\n**STRICT BRAND WALL — MANDATORY**:\n"
            "- You are representing 'Chase'.\n"
            "- DO NOT mention 'J.P. Morgan', 'JPMorgan', 'JPMC', or the parent company name anywhere.\n"
            "- Use ONLY the Chase blue/white color palette and logo provided.\n"
            "- This is a retail consumer brand. Keep it approachable yet premium.\n"
        )
    elif "j.p. morgan" in company_name.lower() or "jp morgan" in company_name.lower():
        return (
            "\n\n**STRICT BRAND WALL — MANDATORY**:\n"
            "- You are representing 'J.P. Morgan'.\n"
            "- DO NOT mention 'Chase' anywhere. This is NOT a retail product.\n"
            "- Use ONLY the J.P. Morgan navy/gold color palette and logo provided.\n"
            "- This is an elite wealth management brand. Aesthetic must be 'Quiet Luxury'.\n"
        )
    return ""

async def _retry_generate_content(model, contents, config, label="LLM", max_attempts=4):
    """Shared retry wrapper for all Gemini generate_content calls."""
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

async def _generate_gemini_image(prompt: str, reference_images: list[bytes], label: str = "image", aspect_ratio: str = None) -> bytes | None:
    parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in reference_images]
    parts.append(types.Part.from_text(text=prompt))

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
                                     label: str = "clip") -> bytes | None:
    """Generates a single VEO video clip using the source's operation polling pipeline."""
    mode = "interpolation" if end_frame_gcs_uri else "i2v"
    try:
        img_mime = "image/png"
        last_frame = None
        if end_frame_gcs_uri:
            last_frame = types.Image(gcs_uri=ensure_gs_uri(end_frame_gcs_uri), mime_type=img_mime)

        veo_config = types.GenerateVideosConfig(
            number_of_videos=1, duration_seconds=clip_duration, aspect_ratio="16:9",
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

        # Source Polling Pipeline
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

# ============================================================
# Audio Generation Helpers
# ============================================================

async def _generate_lyria_music(lyria_prompt: str, product_name: str) -> bytes | None:
    """Generates instrumental background music using Lyria."""
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
    """Generates voiceover audio using Gemini 3.1 Flash TTS Preview."""
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

        # Fallback to a default voice if none provided
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
                
                # Extract audio from response
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

# ============================================================
# Granular Asset Registry Helpers
# ============================================================

def register_asset(tool_context: ToolContext, tag: str, gcs_uri: str):
    """Registers an asset in the session registry."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    registry[tag] = gcs_uri
    tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
    log_message(f"Registered asset: {tag} -> {gcs_uri}", Severity.INFO)

def resolve_asset_uris(tool_context: ToolContext, tags: Optional[List[str]] = None) -> List[str]:
    """Resolves a list of tags to URIs. Falls back to uploads or latest storyboard."""
    from .tools_misc import process_user_uploads
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

# ============================================================
# Storyline & Storyboard Studio (HUMAN-FIRST UPDATE)
# ============================================================

async def _generate_storyline(company_name: str, product_name: str, rationale: str, reference_guidelines: str = "", customer_persona: str = "", duration_seconds: int = 24) -> dict:
    CLIP_SEC = 8
    ACTS = max(1, duration_seconds // CLIP_SEC)
    words_per_act = 25

    guidelines_context = f"\n\nReference Guidelines: {reference_guidelines[:1000]}" if reference_guidelines else ""
    persona_context = f"\n\nTARGET PERSONA: {customer_persona}" if customer_persona else ""
    brand_wall = _get_brand_wall_directive(company_name)
    
    prompt = (
        f"You are a LIFESTYLE DOCUMENTARY DIRECTOR. Your specialty is capturing the pure joy of human moments.\n\n"
        f"Create a BOLD, EMOTIONAL {ACTS}-act video story for {product_name} by {company_name}.\n"
        f"Concept: {rationale}\n{guidelines_context}{persona_context}\n\n"
        f"HUMAN-FIRST STORY MANDATE:\n"
        f"- THE PEOPLE ARE THE STORY. Focus on their expressions, their activities, and the happiness resulting from the moment.\n"
        f"- PRODUCT PLACEMENT MUST BE MINIMAL. Convey the product ONLY via natural action (e.g. a hand tap, holding it while laughing).\n"
        f"- NO heroic close-ups of the card or logo. The product enables the happiness, it doesn't take center stage.\n"
        f"- Frame for EXPANSIVE EMOTION. Show the environment and the shared experience.\n\n"
        f"REALISM MANDATE — ABSOLUTE:\n"
        f"- REAL locations, REAL lighting, REAL people — as if filmed with a REAL camera.\n"
        f"- Products sit on surfaces, liquids flow down, people stand on ground.\n\n"
        f"{brand_wall}\n"
        f"Output EXACTLY this JSON (no markdown):\n"
        f'{{"acts": ['
        f'{{"act_number": 1, "scene_description": "HUMAN EMOTION wide shot", "end_scene_description": "Emotional beat transition", '
        f'"motion_prompt": "Continuous cinematic movement", "voiceover": "Energized text focus on the feeling (~{words_per_act} words)"}},'
        f'... ],'
        f'"lyria_prompt": "Cinematic build with strings and subtle bass" }}'
    )

    try:
        response = await _retry_generate_content(
            model=STORYLINE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=1.0, response_mime_type="application/json"),
            label="storyline"
        )
        result = json.loads(response.text)
        acts = result.get("acts", [])
        result["storyline"] = " ".join(act.get("voiceover", "") for act in acts)
        return result
    except Exception as e:
        log_message(f"Storyline failed: {e}", Severity.WARNING)
        return {
            "acts": [{"act_number": i+1, "scene_description": f"Happy moments with {product_name}", "voiceover": ""} for i in range(ACTS)],
            "storyline": "",
            "lyria_prompt": ""
        }

async def generate_campaign_storyboard(
    tool_context: ToolContext, segment_name: str, selected_campaign_name: str, duration_seconds: int = 24
):
    """Generates a multi-frame storyboard following a Human-First documentary pipeline."""
    set_output_folder(tool_context)
    product_image_uri = tool_context.state.get(PRODUCT_IMAGE_URI_STATE_KEY)
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "JPMC")
    product_name = tool_context.state.get("PRODUCT_NAME", "product")
    ref_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    persona = tool_context.state.get(CUSTOMER_PERSONA_STATE_KEY, "")

    current_iter = tool_context.state.get(STORYBOARD_ITERATION_STATE_KEY, 0) + 1
    tool_context.state[STORYBOARD_ITERATION_STATE_KEY] = current_iter

    from .tools_campaign import _CACHED_CAMPAIGNS_LIST
    rationale = "A cinematic journey"
    if _CACHED_CAMPAIGNS_LIST:
        for c in _CACHED_CAMPAIGNS_LIST:
            if c.name == selected_campaign_name:
                rationale = c.hook
                break

    log_message(f"Storyboard Iteration {current_iter}: Directing the storyline...", Severity.INFO)
    storyline_data = await _generate_storyline(company_name, product_name, rationale, ref_guidelines, persona, duration_seconds)
    tool_context.state["STORYLINE_DATA"] = storyline_data

    res = await utils_agents.load_resource(product_image_uri, tool_context)
    if not res: return {"status": "error", "details": "Product image missing."}
    product_bytes = res.media_bytes

    logo_bytes = None
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    if logo_uri:
        lres = await utils_agents.load_resource(logo_uri, tool_context)
        if lres: logo_bytes = lres.media_bytes

    CLIP_SEC = 8
    ACTS = max(1, duration_seconds // CLIP_SEC)
    NUM_KEYFRAMES = ACTS + 1
    acts = storyline_data.get("acts", [])

    base_kf_environments = [
        "BRIGHT DAYLIGHT — vivid sunlight, wide cinematic vista, sharp shadows. Fresh, energetic atmosphere.",
        "GOLDEN HOUR — warm amber backlighting, lens flares, dramatic long shadows. Magical cinematic warmth.",
        "DRAMATIC DUSK — deep sky colors, moody city atmosphere, wow factor. Silhouette edges.",
        "NIGHT / NEON — dramatic artificial lighting, city reflections, urban grandeur.",
    ]
    kf_environments = [base_kf_environments[i % len(base_kf_environments)] for i in range(NUM_KEYFRAMES)]

    kf_descriptions = []
    for i in range(NUM_KEYFRAMES):
        if i == 0:
            kf_descriptions.append(acts[0].get("scene_description", "Opening wide reveal of human happiness"))
        elif i < ACTS:
            kf_descriptions.append(acts[i-1].get("end_scene_description", acts[i].get("scene_description", "Joyful activity")))
        else:
            kf_descriptions.append(acts[-1].get("end_scene_description", "Final emotional payoff"))

    refs = [product_bytes] + ([logo_bytes] if logo_bytes else [])
    brand_wall = _get_brand_wall_directive(company_name)
    
    compliance = (
        f"\n\n**VIDEO PRODUCTION DIRECTIVE — HUMAN-FIRST**:\n"
        f"- NO PRODUCT HERO SHOTS. The focus MUST be on people, their activity, and their happiness.\n"
        f"- Product placement is MINIMAL and only conveyed via natural ACTION (e.g. held while hugging, tapped while smiling).\n"
        f"- WIDE-ANGLE CINEMATIC SHOT. Show the EXPANSIVE environment and the shared experience.\n"
        f"- If people appear, show them at a distance or from side/back angles. NO CLOSE-UP FACES.\n"
        f"- The product '{product_name}' MUST be at its EXACT real-world physical size.\n"
        f"{brand_wall}"
    )

    async def _gen_kf(idx):
        current_refs = refs if (idx % 2 == 0 or idx == NUM_KEYFRAMES - 1) else []
        prompt = (
            f"Photorealistic lifestyle storyboard frame {idx+1} of {NUM_KEYFRAMES} for {product_name} by {company_name}.\n"
            f"SCENE: {kf_descriptions[idx]}\n"
            f"LIGHTING: {kf_environments[idx]}\n"
            f"{compliance}\n"
            f"16:9 landscape. Return only the image. NO text labels or counters."
        )
        return await _generate_gemini_image(prompt, current_refs, label=f"storyboard_frame", aspect_ratio="16:9")

    log_message(f"Generating {NUM_KEYFRAMES} human-first keyframes for v{current_iter}...", Severity.INFO)
    kf_results = await asyncio.gather(*[_gen_kf(i) for i in range(NUM_KEYFRAMES)])
    
    storyboard_uris = []
    output_folder = tool_context.state.get("CURRENT_OUTPUT_FOLDER", "generated")
    for i, img_bytes in enumerate(kf_results):
        if img_bytes:
            tag = f"v{current_iter}-f{i+1}"
            filename = f"storyboard_frame_{tag}.png"
            blob_path = f"{output_folder}/{filename}"
            
            uri = utils_gcs.upload_to_gcs(
                bucket_path=GOOGLE_CLOUD_BUCKET_ARTIFACTS, 
                file_bytes=img_bytes, 
                destination_blob_name=blob_path,
                metadata={"tag": tag, "iteration": str(current_iter), "frame": str(i+1)}
            )
            
            register_asset(tool_context, tag, uri)
            storyboard_uris.append(uri)
            
            media = GeneratedMedia(filename=filename, mime_type="image/png", media_bytes=img_bytes)
            await utils_agents.save_to_artifact_and_render_asset(asset=media, context=tool_context, save_in_gcs=False, save_in_artifacts=False)

    tool_context.state["STORYBOARD_KEYFRAMES"] = storyboard_uris
    return {
        "status": "success", 
        "iteration": current_iter,
        "storyboard_uris": storyboard_uris,
        "storyline": storyline_data.get("storyline", ""),
        "tags": [f"v{current_iter}-f{i+1}" for i in range(len(storyboard_uris))]
    }

# ============================================================
# Display Ad Generation (Sophisticated SOURCE port)
# ============================================================

async def _create_display_ad_task(
    tool_context: ToolContext,
    prompt_description: str,
    asset_sheet_bytes: Optional[bytes],
    product_bytes: bytes,
    logo_bytes: Optional[bytes],
    variation_index: int = 0,
    filename_prefix: str = "ad"
) -> Dict[str, Any]:
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "JPMC")
    product_name = tool_context.state.get("PRODUCT_NAME", "Product")
    ref_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    persona = tool_context.state.get(CUSTOMER_PERSONA_STATE_KEY, "")

    reference_parts = []
    reference_parts.append(types.Part.from_bytes(data=product_bytes, mime_type="image/png"))
    if asset_sheet_bytes:
        reference_parts.append(types.Part.from_bytes(data=asset_sheet_bytes, mime_type="image/png"))

    style_rule = _VARIATION_STYLES[variation_index % len(_VARIATION_STYLES)]
    brand_wall = _get_brand_wall_directive(company_name)

    # Source Prompt Block
    final_prompt = (
        f"**ROLE**: Expert Digital Ad Designer for {company_name}.\n\n"
        f"**CONCEPT**: {prompt_description}\n\n"
        f"**VISUAL STYLE DIRECTIVE**: {style_rule}\n\n"
        f"**AESTHETIC**: Ultra-premium luxury commercial photography. Masters of color and light.\n\n"
        f"**RULES**:\n"
        f"1. Reproduce product with pixel-perfect fidelity.\n"
        f"{'2. Use characters/aesthetic from the ASSET SHEET (2nd image).' if asset_sheet_bytes else ''}\n"
        f"3. Product at CORRECT real-world scale. Physics must be real.\n"
        f"4. EXPANSIVE COMPOSITION. Show context. NO close-up faces.\n"
        f"5. Do not force the product image into the scene. Make it natural.\n"
        f"6. The output should feel like a premium,luxury commercial.\n"
        f"7. Focus on the activity and the emotion. Product should be secondary.\n"
        f"8. Show people enjoying the moment or activity that the product facilitates.\n"
        f"9. There should be an element of sophistication and elegance in the composition.\n"
        f"10. Use natural lighting and shadows to create a realistic and premium feel.\n"
        f"11. The composition should be visually balanced and appealing to the eye.\n"
        f"12. The colors should be vibrant but natural, reflecting the premium nature of the product.\n"
        f"13. The output should be a high-quality, professional advertisement.\n"
        f"14. The output should be suitable for use in a marketing campaign.\n"
        f"{brand_wall}\n"
        f"{'**TARGET AUDIENCE**: ' + persona if persona else ''}\n"
        f"**FINAL OUTPUT**: Return ONLY the ad image. NO text labels, counters, or logos."
    )

    return await generate_and_select_best_image(
        filename_without_extension=filename_prefix,
        input_images=reference_parts,
        prompt=final_prompt,
    )

async def generate_display_ad(
    tool_context: ToolContext, 
    prompt: str, 
    selected_campaign_name: str,
    asset_sheet_uri: Optional[str] = None,
    num_images: int = 1
):
    """Generates final, high-quality Display Ads using the source evaluation pipeline."""
    current_output_folder = set_output_folder(tool_context)
    product_image_uri = tool_context.state.get(PRODUCT_IMAGE_URI_STATE_KEY)
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)

    # Resource loading
    product_res = await utils_agents.load_resource(product_image_uri, tool_context)
    if not product_res: return {"status": "error", "details": "Product image missing."}
    product_bytes = product_res.media_bytes

    logo_bytes = None
    if logo_uri:
        lres = await utils_agents.load_resource(logo_uri, tool_context)
        if lres: logo_bytes = lres.media_bytes

    asset_sheet_bytes = None
    if asset_sheet_uri:
        ares = await utils_agents.load_resource(asset_sheet_uri, tool_context)
        if ares: asset_sheet_bytes = ares.media_bytes

    final_urls = []
    for i in range(num_images):
        ts = int(time.time() * 1000)
        prefix = f"display_ad_{ts}_{i}"
        result = await _create_display_ad_task(tool_context, prompt, asset_sheet_bytes, product_bytes, logo_bytes, i, prefix)

        if result and result.get("status") == "success" and result.get("image_bytes"):
            generated_media = GeneratedMedia(filename=result["file_name"], mime_type="image/png", media_bytes=result["image_bytes"])
            generated_media = await utils_agents.save_to_artifact_and_render_asset(
                asset=generated_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
            )
            final_urls.append(utils_gcs.normalize_to_gs_bucket_uri(generated_media.gcs_uri))

    return {"status": "success", "image_urls": final_urls}

# ============================================================
# Video Production Pipeline (DIRECT SOURCE PORT)
# ============================================================

async def generate_video_from_storyboard(
    tool_context: ToolContext, selected_campaign_name: str, segment_name: str, duration_seconds: int = 24,
    asset_tags: Optional[List[str]] = None, voiceover_script: Optional[str] = None
):
    """Produces the final stitched cinematic VEO video ad using a prioritized list of asset tags."""
    current_output_folder = set_output_folder(tool_context)
    storyline_data = tool_context.state.get("STORYLINE_DATA")

    # Priority Resolver Logic
    storyboard_uris = resolve_asset_uris(tool_context, asset_tags)

    if not storyline_data or not storyboard_uris:
        return {"status": "error", "details": "No storyboard frames found. Run generate_campaign_storyboard or upload images first."}

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "")
    product_name = tool_context.state.get("PRODUCT_NAME", "product")

    log_message(f"Storyboard Studio: Launching video production with {len(storyboard_uris)} frames...", Severity.INFO)
    _pipeline_start = time.time()

    CLIP_SEC = 8
    ACTS = max(1, duration_seconds // CLIP_SEC)

    # Use provided voiceover_script if available, otherwise fall back to storyline
    final_voiceover_script = voiceover_script if voiceover_script else storyline_data.get("storyline", "")
    lyria_prompt = storyline_data.get("lyria_prompt", "")
    acts = storyline_data.get("acts", [])
    while len(acts) < ACTS:
        acts.append(acts[-1] if acts else {"motion_prompt": "Cinematic camera movement"})
    acts = acts[:ACTS]

    logo_bytes = None
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    if logo_uri:
        try:
            res = await utils_agents.load_resource(logo_uri, tool_context)
            if res: logo_bytes = res.media_bytes
        except Exception: pass

    # Start audio tasks in parallel
    vo_task = asyncio.create_task(_generate_voiceover_audio(final_voiceover_script))
    lyria_task = asyncio.create_task(_generate_lyria_music(lyria_prompt, product_name))

    async def _gen_clip(act_idx):
        act = acts[act_idx]
        motion = act.get("timestamped_visual_actions", "[00:00-00:08] Cinematic shot of human activity")
        transition = "CONTINUOUS SMOOTH MOTION. Constant cinematic movement throughout. REAL-LIFE PHYSICS."
        full_motion = _sanitize_veo_prompt(f"{motion}. TRANSITION EFFECT: {transition}")

        log_message(f"VEO FINAL PROMPT (Act {act_idx+1}):\n{full_motion}", Severity.INFO)

        start_uri = storyboard_uris[act_idx] if act_idx < len(storyboard_uris) else storyboard_uris[-1]
        end_uri = storyboard_uris[act_idx + 1] if act_idx + 1 < len(storyboard_uris) else None

        return act_idx, await _generate_single_veo_clip(full_motion, start_uri, CLIP_SEC, end_uri, label=f"act_{act_idx+1}")

    log_message(f"Triggering {ACTS} VEO clips in parallel...", Severity.INFO)
    veo_results = await asyncio.gather(*[_gen_clip(i) for i in range(ACTS)])

    clip_map = {idx: b for idx, b in veo_results if b}
    if not clip_map: return {"status": "error", "details": "VEO generation failed."}
    clips = [clip_map[i] for i in sorted(clip_map.keys())]

    # Wait for audio tasks
    vo_bytes = await vo_task
    music_bytes = await lyria_task

    # Post-production
    log_message("Post-production: stitching and mixing...", Severity.INFO)
    stitched = stitch_videos(clips) if len(clips) > 1 else clips[0]
    
    final = mix_audio_onto_video(stitched, vo_bytes, music_bytes)
    if logo_bytes:
        final = overlay_logo_on_video(final, logo_bytes)

    from .tools_campaign import _CACHED_CAMPAIGNS_LIST
    tagline = ""
    if _CACHED_CAMPAIGNS_LIST:
        for c in _CACHED_CAMPAIGNS_LIST:
            if c.name == selected_campaign_name:
                tagline = c.tagline or ""
                break

    final = add_text_overlays(final, company_name, tagline, duration_seconds, product_name=product_name, acts=acts, clip_sec=CLIP_SEC)
    final = add_end_card_overlay(final, company_name, tagline)

    filename = f"video_ad_final_{int(time.time())}.mp4"
    video_media = GeneratedMedia(filename=filename, mime_type="video/mp4", media_bytes=final)
    await utils_agents.save_to_artifact_and_render_asset(asset=video_media, context=tool_context, save_in_gcs=True, save_in_artifacts=True, gcs_folder=current_output_folder)

    return {"status": "success", "gcs_url": get_public_url(f"{current_output_folder}/{filename}")}

async def generate_text_ad(tool_context: ToolContext, selected_campaign_name: str, segment_name: str):
    return {"status": "success", "headlines": ["Chase Your Dreams"], "descriptions": ["Premium rewards with JPMC."]}
