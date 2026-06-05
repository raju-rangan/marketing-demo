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
import time
from typing import List, Optional
from google.adk.tools.tool_context import ToolContext
from ...adk_common.dtos.generated_media import GeneratedMedia
from ...adk_common.utils import utils_agents
from ...adk_common.utils.utils_logging import Severity, log_message, log_status, stream_status
from ...state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY,
    LOGO_VERTICAL_IMAGE_URI_STATE_KEY,
)
from ...utils.utils_gcs import get_public_url, set_output_folder
from ...shared_infra.utils_media import (
    stitch_videos,
    mix_audio_onto_video,
    overlay_logo_on_video,
    add_text_overlays,
    add_end_card_overlay,
)
from .utils import (
    resolve_asset_uris,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _sanitize_veo_prompt,
    _generate_single_veo_clip,
)

@stream_status("🎥 Rendering the final cinematic VEO commercial...")
async def generate_video_from_storyboard(
    tool_context: ToolContext, selected_campaign_name: str, segment_name: str, duration_seconds: int = 24,
    asset_tags: Optional[List[str]] = None, voiceover_script: Optional[str] = None, aspect_ratio: str = "16:9"
):
    """Produces the final stitched cinematic VEO video ad using a prioritized list of asset tags."""
    current_output_folder = set_output_folder(tool_context)
    storyline_data = tool_context.state.get("STORYLINE_DATA")

    storyboard_uris = resolve_asset_uris(tool_context, asset_tags)

    if not storyline_data or not storyboard_uris:
        return {"status": "error", "details": "No storyboard frames found. Run generate_campaign_storyboard or upload images first."}

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "")
    product_name = tool_context.state.get("PRODUCT_NAME", "product")

    log_message(f"Storyboard Studio: Launching video production with {len(storyboard_uris)} frames...", Severity.INFO)

    CLIP_SEC = 8
    ACTS = max(1, duration_seconds // CLIP_SEC)

    final_voiceover_script = voiceover_script if voiceover_script else storyline_data.get("storyline", "")
    lyria_prompt = storyline_data.get("lyria_prompt", "")
    acts = storyline_data.get("acts", [])
    while len(acts) < ACTS:
        acts.append(acts[-1] if acts else {"motion_prompt": "Cinematic camera movement"})
    acts = acts[:ACTS]

    logo_bytes = None
    if aspect_ratio == "9:16":
        logo_uri = tool_context.state.get(LOGO_VERTICAL_IMAGE_URI_STATE_KEY)
    else:
        logo_uri = tool_context.state.get(LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY)

    if not logo_uri:
        logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)

    if logo_uri:
        try:
            res = await utils_agents.load_resource(logo_uri, tool_context)
            if res: logo_bytes = res.media_bytes
        except Exception: pass

    log_status("🔊 Generating high-fidelity voiceover and background music...")
    vo_task = asyncio.create_task(_generate_voiceover_audio(final_voiceover_script))
    lyria_task = asyncio.create_task(_generate_lyria_music(lyria_prompt, product_name))

    async def _gen_clip(act_idx):
        act = acts[act_idx]
        motion = act.get("timestamped_visual_actions", "[00:00-00:08] Cinematic shot of human activity")
        transition = "CONTINUOUS SMOOTH MOTION. Constant cinematic movement throughout. REAL-LIFE PHYSICS."
        full_motion = _sanitize_veo_prompt(f"{motion}. TRANSITION EFFECT: {transition}")

        log_message(f"VEO FINAL PROMPT (Act {act_idx+1}):\n{full_motion}", Severity.INFO)
        log_status(f"🤖 Generating VEO scene {act_idx+1} of {ACTS}...")

        start_uri = storyboard_uris[act_idx] if act_idx < len(storyboard_uris) else storyboard_uris[-1]
        end_uri = storyboard_uris[act_idx + 1] if act_idx + 1 < len(storyboard_uris) else None

        return act_idx, await _generate_single_veo_clip(full_motion, start_uri, CLIP_SEC, end_uri, label=f"act_{act_idx+1}", aspect_ratio=aspect_ratio)

    log_message(f"Triggering {ACTS} VEO clips in parallel...", Severity.INFO)
    veo_results = await asyncio.gather(*[_gen_clip(i) for i in range(ACTS)])

    clip_map = {idx: b for idx, b in veo_results if b}
    if not clip_map: return {"status": "error", "details": "VEO generation failed."}
    clips = [clip_map[i] for i in sorted(clip_map.keys())]

    vo_bytes = await vo_task
    music_bytes = await lyria_task

    log_status("🎬 Mastering and stitching the final commercial...")
    log_message("Post-production: stitching and mixing...", Severity.INFO)
    stitched = stitch_videos(clips) if len(clips) > 1 else clips[0]
    
    final = mix_audio_onto_video(stitched, vo_bytes, music_bytes)

    if logo_bytes:
        final = overlay_logo_on_video(final, logo_bytes)

    from ..campaign import _CACHED_CAMPAIGNS_LIST
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
    await utils_agents.save_to_artifact_and_render_asset(asset=video_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder)

    return {"status": "success", "gcs_url": get_public_url(f"{current_output_folder}/{filename}")}
