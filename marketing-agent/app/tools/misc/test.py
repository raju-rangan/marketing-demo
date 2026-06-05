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

import os
from google.adk.tools.tool_context import ToolContext
from ...adk_common.utils.utils_logging import Severity, log_message, stream_status
from .brand import select_brand_preset

@stream_status("🚀 Launching the full production test pipeline...")
async def run_production_test(tool_context: ToolContext, url: str = "https://www.google.com", asset_uri: str = None) -> dict:
    """EASTER EGG: A special shortcut to test the full production pipeline OR generate a signed URL for a specific asset.
    
    Args:
        url: The URL to research and use as a basis for image generation (for full test).
        asset_uri: Optional. If provided, just generates a signed URL for this specific asset (e.g., gs://... or /samples/...).
    """
    from ...utils.utils_gcs import get_public_url
    
    if asset_uri:
        log_message(f"Generating signed URL for asset: {asset_uri}", Severity.INFO)
        signed_url = get_public_url(asset_uri)
        return {
            "status": "success",
            "message": f"Signed URL generated for {asset_uri}",
            "signed_url": signed_url
        }

    from ..slidecast import (
        generate_slidecast_storyboard, 
        preview_slidecast_assets, 
        finalize_slidecast_video, 
        select_slidecast_style
    )
    from ..media import create_image_composite
    
    log_message(f"Running full production test for {url}...", Severity.INFO)
    
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    preset_name = "Google Search & AI Services" 
    select_brand_preset(tool_context, preset_name)
    select_slidecast_style(tool_context, "Modern 3D Isometric", "Professional & Trustworthy")
    
    storyboard = generate_slidecast_storyboard(tool_context, urls=[url], duration_seconds=60)
    if "error" in storyboard:
        return {"status": "error", "details": f"Storyboard generation failed: {storyboard['error']}"}

    preview_result = await preview_slidecast_assets(tool_context, storyboard)
    if preview_result.get("status") == "error":
        return preview_result

    video_result = await finalize_slidecast_video(tool_context, preview_result["storyboard"])
    
    slides = preview_result["storyboard"].get("slides", [])
    image_urls = [s["image_url"] for s in slides[:2] if s.get("image_url")]
    composite_url = None
    if image_urls:
        composite_result = await create_image_composite(tool_context, image_urls)
        composite_url = composite_result.get("composite_url")
    
    return {
        "status": "success",
        "message": "Full Production Pipeline Validation Complete!",
        "video_url": video_result.get("video_url"),
        "composite_url": composite_url,
        "details": f"Validated: Research, Storyboard ({len(slides)} slides), Audio (Gemini TTS), Video (FFmpeg), and Composite (Image Stitching)."
    }
