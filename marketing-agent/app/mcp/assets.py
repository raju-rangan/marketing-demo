import json
import logging
import asyncio
import time
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from .generators import (
    _generate_gemini_image,
    _generate_single_veo_clip,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _get_brand_wall_directive,
)
from .generators.core import _download_uri, _upload_bytes
from ..adk_common.utils import utils_agents, utils_gcs
from ..state import GOOGLE_CLOUD_BUCKET_ARTIFACTS

logger = logging.getLogger(__name__)

def add_asset_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def create_visual_assets(
        company_name: str,
        product_name: str,
        scene_descriptions: List[str],
        reference_image_uris: Optional[List[str]] = None,
        aspect_ratio: str = "16:9",
        guidelines: str = ""
    ) -> str:
        """
        Generates a sequence of keyframe images based on scene descriptions.
        Typically used for creating the visual storyboard frames.
        Returns a JSON list of generated GCS URIs.
        """
        try:
            # Download reference images (like product or logo)
            ref_bytes = []
            if reference_image_uris:
                for uri in reference_image_uris:
                    b = await _download_uri(uri)
                    if b: ref_bytes.append(b)

            brand_wall = _get_brand_wall_directive(company_name, guidelines=guidelines)
            compliance = (
                f"\n\n**VIDEO PRODUCTION DIRECTIVE — HUMAN-FIRST**:\n"
                f"- NO PRODUCT HERO SHOTS. The focus MUST be on people, their activity, and their happiness.\n"
                f"- WIDE-ANGLE CINEMATIC SHOT. Show the EXPANSIVE environment.\n"
                f"{brand_wall}"
            )

            async def _gen_frame(idx, desc):
                prompt = (
                    f"Photorealistic lifestyle storyboard frame {idx+1} for {product_name} by {company_name}.\n"
                    f"SCENE: {desc}\n"
                    f"{compliance}\n"
                    f"{aspect_ratio}. Return only the image. NO text labels or counters."
                )
                img_bytes = await _generate_gemini_image(prompt, ref_bytes, label=f"frame_{idx}", aspect_ratio=aspect_ratio)
                if img_bytes:
                    ts = int(time.time() * 1000)
                    return await _upload_bytes(img_bytes, "mcp_generated", f"frame_{idx}_{ts}.png", "image/png")
                return None

            results = await asyncio.gather(*[_gen_frame(i, desc) for i, desc in enumerate(scene_descriptions)])
            uris = [u for u in results if u]
            
            return json.dumps({"status": "success", "image_uris": uris})
            
        except Exception as e:
            logger.error(f"Failed to create visual assets: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def create_video_assets(
        motion_prompts: List[str],
        start_frame_uris: List[str],
        clip_duration_seconds: int = 6,
        aspect_ratio: str = "16:9"
    ) -> str:
        """
        Generates high-fidelity video clips using VEO based on motion prompts and start frames.
        Returns a JSON list of generated MP4 GCS URIs.
        """
        try:
            async def _gen_video(idx, motion, start_uri):
                # We just pass the URI to _generate_single_veo_clip, which handles its own resolution
                vid_bytes = await _generate_single_veo_clip(
                    prompt=motion,
                    start_frame_gcs_uri=start_uri,
                    clip_duration=clip_duration_seconds,
                    label=f"mcp_clip_{idx}",
                    aspect_ratio=aspect_ratio
                )
                if vid_bytes:
                    ts = int(time.time() * 1000)
                    return await _upload_bytes(vid_bytes, "mcp_generated", f"clip_{idx}_{ts}.mp4", "video/mp4")
                return None

            results = await asyncio.gather(*[_gen_video(i, p, start_frame_uris[i]) for i, p in enumerate(motion_prompts)])
            uris = [u for u in results if u]
            
            return json.dumps({"status": "success", "video_uris": uris})
            
        except Exception as e:
            logger.error(f"Failed to create video assets: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def create_voiceover(script: str, voice_name: str = "Puck") -> str:
        """
        Generates a realistic voiceover track from a script.
        Returns a JSON object containing the audio GCS URI.
        """
        try:
            audio_bytes = await _generate_voiceover_audio(script, voice_name)
            if audio_bytes:
                ts = int(time.time() * 1000)
                uri = await _upload_bytes(audio_bytes, "mcp_generated", f"vo_{ts}.wav", "audio/wav")
                return json.dumps({"status": "success", "voiceover_uri": uri})
            return json.dumps({"status": "error", "details": "No audio returned."})
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})
            
    @mcp.tool()
    async def create_background_music(lyria_prompt: str, product_name: str) -> str:
        """
        Generates an instrumental background music track using Lyria.
        Returns a JSON object containing the audio GCS URI.
        """
        try:
            audio_bytes = await _generate_lyria_music(lyria_prompt, product_name)
            if audio_bytes:
                ts = int(time.time() * 1000)
                uri = await _upload_bytes(audio_bytes, "mcp_generated", f"music_{ts}.wav", "audio/wav")
                return json.dumps({"status": "success", "music_uri": uri})
            return json.dumps({"status": "error", "details": "No audio returned."})
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})
