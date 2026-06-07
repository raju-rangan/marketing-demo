import json
import logging
import asyncio
import time
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from .schemas import RenderJob
from .assets import _download_uri, _upload_bytes
from ..shared_infra.utils_media import (
    stitch_videos,
    mix_audio_onto_video,
    overlay_logo_on_video,
    add_text_overlays,
    add_end_card_overlay,
)

logger = logging.getLogger(__name__)

def add_production_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def generate_video_from_storyboard(render_job_json: str) -> str:
        """
        Executes a final render job, assembling video clips, voiceover, and music.
        Takes a JSON string matching the RenderJob schema.
        Returns a JSON object with the final stitched MP4 GCS URI.
        """
        try:
            # 1. Parse the strictly typed RenderJob payload
            job = RenderJ/ob.model_validate_json(render_job_json)
            
            logger.info(f"Starting production for {job.company_name} - {len(job.video_clip_uris)} clips.")
            
            # 2. Download all assets in parallel
            download_tasks = [
                *[_download_uri(uri) for uri in job.video_clip_uris],
                _download_uri(job.voiceover_uri) if job.voiceover_uri else asyncio.sleep(0),
                _download_uri(job.music_uri) if job.music_uri else asyncio.sleep(0),
                _download_uri(job.logo_uri) if job.logo_uri else asyncio.sleep(0)
            ]
            
            results = await asyncio.gather(*download_tasks)
            
            # Extract results based on order
            clip_count = len(job.video_clip_uris)
            clips_bytes = results[:clip_count]
            vo_bytes = results[clip_count] if job.voiceover_uri else None
            music_bytes = results[clip_count + 1] if job.music_uri else None
            logo_bytes = results[clip_count + 2] if job.logo_uri else None
            
            # Validate clips
            valid_clips = [c for c in clips_bytes if c]
            if not valid_clips:
                return json.dumps({"status": "error", "details": "No valid video clips downloaded."})
                
            # 3. Post-production (FFmpeg operations)
            logger.info("Stitching clips...")
            stitched = stitch_videos(valid_clips) if len(valid_clips) > 1 else valid_clips[0]
            
            logger.info("Mixing audio...")
            final_video = mix_audio_onto_video(stitched, vo_bytes, music_bytes)
            
            if logo_bytes:
                logger.info("Adding logo...")
                final_video = overlay_logo_on_video(final_video, logo_bytes)
                
            logger.info("Adding text overlays and end card...")
            # Calculate clip duration assuming equal length acts
            clip_sec = max(1, job.duration_seconds // max(1, len(job.acts)))
            acts_dicts = [act.model_dump() for act in job.acts]
            
            final_video = add_text_overlays(
                final_video, 
                job.company_name, 
                job.tagline, 
                job.duration_seconds, 
                product_name=job.product_name, 
                acts=acts_dicts, 
                clip_sec=clip_sec
            )
            final_video = add_end_card_overlay(final_video, job.company_name, job.tagline)
            
            # 4. Upload final asset
            ts = int(time.time() * 1000)
            filename = f"mcp_video_ad_final_{ts}.mp4"
            final_uri = await _upload_bytes(final_video, "mcp_generated", filename, "video/mp4")
            
            return json.dumps({
                "status": "success", 
                "video_uri": final_uri,
                "message": "Video production completed successfully."
            })
            
        except Exception as e:
            logger.error(f"Failed to produce video asset: {e}")
            return json.dumps({"status": "error", "details": str(e)})
