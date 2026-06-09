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
        Utility Primitive: Generates a sequence of keyframe images based on scene descriptions.
        
        WHEN TO USE:
        Use ONLY for ad-hoc or generic storyboard asset creation outside of a structured Slidecast. Do NOT use this tool if you are producing a Slidecast (use render_images instead).
        
        ARGS:
        - company_name, product_name: Brand context.
        - scene_descriptions: List of text prompts describing each frame.
        - reference_image_uris: Optional list of base images.
        - aspect_ratio: Usually "16:9" or "9:16".
        
        RETURNS:
        A JSON string containing a list of the generated image GCS URIs.
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
        end_frame_uris: Optional[List[str]] = None,
        clip_duration_seconds: int = 8,
        aspect_ratio: str = "16:9"
    ) -> str:
        """
        Utility Primitive: Generates high-fidelity video clips using Veo based on motion prompts and frame pairs.
        
        WHEN TO USE:
        Use ONLY for ad-hoc video segment generation outside of a structured Slidecast. Do NOT use this tool if you are producing a Slidecast (use generate_video_segments instead).
        
        ARGS:
        - motion_prompts: List of text prompts describing the movement.
        - start_frame_uris: The starting image for each clip.
        - end_frame_uris: The ending image for each clip.
        
        RETURNS:
        A JSON string containing a list of the generated MP4 GCS URIs.
        """
        try:
            # Map duration to nearest supported: 4, 6, 8
            supported = [4, 6, 8]
            effective_duration = min(supported, key=lambda x: abs(x - clip_duration_seconds))
            
            async def _gen_video(idx, motion, start_uri, end_uri):
                # Use provided end_uri or fallback to start_uri for stability
                target_end_uri = end_uri if end_uri else start_uri
                vid_bytes = await _generate_single_veo_clip(
                    prompt=motion,
                    start_frame_gcs_uri=start_uri,
                    end_frame_gcs_uri=target_end_uri,
                    clip_duration=effective_duration,
                    label=f"mcp_clip_{idx}",
                    aspect_ratio=aspect_ratio
                )
                if vid_bytes:
                    ts = int(time.time() * 1000)
                    return await _upload_bytes(vid_bytes, "mcp_generated", f"clip_{idx}_{ts}.mp4", "video/mp4")
                return None

            # Prepare end_frame_uris list with Nones if shorter than start_frame_uris
            end_uris = end_frame_uris if end_frame_uris else [None] * len(start_frame_uris)
            
            results = await asyncio.gather(*[_gen_video(i, p, start_frame_uris[i], end_uris[i]) for i, p in enumerate(motion_prompts)])
            uris = [u for u in results if u]
            
            return json.dumps({"status": "success", "video_uris": uris})
            
        except Exception as e:
            logger.error(f"Failed to create video assets: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def create_voiceover(script: str, voice_name: str = "Puck") -> str:
        """
        Utility Primitive: Generates a realistic voiceover audio track from a script using Google TTS.
        
        WHEN TO USE:
        Use ONLY for ad-hoc voiceover generation. Do NOT use this tool if you are producing a Slidecast (use render_audio instead).
        
        ARGS:
        - script (str): The text to be spoken.
        - voice_name (str): The Google TTS voice identifier.
        
        RETURNS:
        A JSON string containing the generated audio WAV GCS URI.
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
        Utility Primitive: Generates an instrumental background music track using Google Lyria.
        
        WHEN TO USE:
        Use this anytime you need a custom, royalty-free background track based on a mood or style description.
        
        ARGS:
        - lyria_prompt (str): Description of the music (e.g., "Upbeat corporate acoustic guitar").
        
        RETURNS:
        A JSON string containing the generated audio WAV GCS URI.
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
