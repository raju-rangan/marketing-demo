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

import time
from google.adk.tools.tool_context import ToolContext
from ...adk_common.dtos.generated_media import GeneratedMedia
from ...adk_common.utils import utils_agents, utils_gcs
from ...adk_common.utils.utils_logging import Severity, log_message
from ...shared_infra.utils_media import stitch_images
from ...utils.utils_gcs import set_output_folder

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
