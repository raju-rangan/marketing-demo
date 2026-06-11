import json
import logging
import asyncio
import time
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from app.mcp_server.schemas import RenderJob, SlidecastManifest
from app.mcp_server.assets import _download_uri, _upload_bytes
from app.utils.media import (
    stitch_videos,
    mix_audio_onto_video,
    overlay_logo_on_video,
    add_text_overlays,
    add_end_card_overlay,
    compile_slidecast_video
)
from app.adk_common.utils.utils_logging import log_message, Severity

logger = logging.getLogger(__name__)

def add_production_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def stitch_raw_assets(job: RenderJob) -> str:
        """
        Utility primitive: Stitches arbitrary media assets (clips, voiceover, music) from a list of URIs into a final video.
        
        WHEN TO USE:
        Use this ONLY for generic video ad production (e.g., Shorts or custom RenderJobs). DO NOT use this for Slidecast/presentation rendering.
        
        ARGS:
        - job: A strictly typed RenderJob Pydantic object containing the individual URIs to stitch.
        
        RETURNS:
        A JSON object with the final stitched MP4 GCS URI.
        """
        try:
            logger.info(f"Starting production for {job.company_name} - {len(job.video_clip_uris)} clips.")
            
            # ... (rest of function)
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
            logger.info("Calling add_end_card_overlay...")
            final_video = add_end_card_overlay(final_video, job.company_name, job.tagline)
            logger.info("Finished add_end_card_overlay.")
            
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

    @mcp.tool()
    async def render_slidecast(manifest: SlidecastManifest) -> str:
        """
        Gate 3 Finalization: Compiles a completed SlidecastManifest into a final video.
        
        WHEN TO USE:
        Call this as the absolute final step (Gate 3) of the Slidecast workflow, ONLY AFTER all required audio and image/video segments have been rendered.
        
        ARGS:
        - manifest: The fully populated SlidecastManifest containing all the generated image/video/audio URIs.
        
        RETURNS:
        A JSON object with the final stitched MP4 GCS URI. Present this final link to the user.
        """
        try:
            logger.info(f"Starting slidecast production: {manifest.title} - {len(manifest.slides)} slides.")
            
            # 2. Download all assets (images, video, audio per slide)
            download_tasks = []
            for s in manifest.slides:
                if s.start_image_url: download_tasks.append(_download_uri(s.start_image_url))
                if s.end_image_url: download_tasks.append(_download_uri(s.end_image_url))
                if s.video_url: download_tasks.append(_download_uri(s.video_url))
                if s.audio_url: download_tasks.append(_download_uri(s.audio_url))
            
            results = await asyncio.gather(*download_tasks)
            
            # 3. Construct Slide Data
            results_iter = iter(results)
            slide_data = []
            for s in manifest.slides:
                img_bytes = next(results_iter) if s.start_image_url else b""
                end_img_bytes = next(results_iter) if s.end_image_url else None
                vid_bytes = next(results_iter) if s.video_url else None
                aud_bytes = next(results_iter) if s.audio_url else b""
                
                slide_data.append({
                    "image_bytes": img_bytes,
                    "end_image_bytes": end_img_bytes,
                    "video_bytes": vid_bytes,
                    "audio_bytes": aud_bytes,
                    "text_overlay": s.title
                })
            
            # 4. Compile
            final_video = compile_slidecast_video(slide_data, aspect_ratio=manifest.aspect_ratio)
            
            if not final_video:
                return json.dumps({"status": "error", "details": "Slidecast rendering failed."})

            # Overlay Logo if available
            from .generators.misc import load_brand_context
            brand_context = await load_brand_context()
            if brand_context and brand_context.logo_uri:
                logo_bytes = await _download_uri(brand_context.logo_uri)
                if logo_bytes:
                    logger.info("Adding brand logo overlay to slidecast...")
                    final_video = overlay_logo_on_video(final_video, logo_bytes)

            # 5. Upload
            ts = int(time.time() * 1000)
            filename = f"mcp_slidecast_{ts}.mp4"
            final_uri = await _upload_bytes(final_video, "mcp_generated", filename, "video/mp4")
            
            return json.dumps({
                "status": "success", 
                "video_uri": final_uri,
                "message": "Slidecast production completed successfully."
            })
            
        except Exception as e:
            logger.error(f"Failed to produce slidecast asset: {e}")
            return json.dumps({"status": "error", "details": str(e)})
