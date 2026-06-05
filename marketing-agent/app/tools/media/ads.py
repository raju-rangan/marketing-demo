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
from typing import Any, Dict, Optional
from google.adk.tools.tool_context import ToolContext
from ...adk_common.dtos.generated_media import GeneratedMedia
from ...adk_common.utils import utils_agents, utils_gcs
from ...adk_common.utils.gemini_utils import generate_and_select_best_image
from google.genai import types

from ...state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    CUSTOMER_PERSONA_STATE_KEY,
)
from ...utils.utils_gcs import set_output_folder
from .utils import (
    _VARIATION_STYLES,
    _get_brand_wall_directive,
)

async def _create_display_ad_task(
    tool_context: ToolContext,
    prompt_description: str,
    asset_sheet_bytes: Optional[bytes],
    product_bytes: bytes,
    logo_bytes: Optional[bytes],
    variation_index: int = 0,
    filename_prefix: str = "ad"
) -> Dict[str, Any]:
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    product_name = tool_context.state.get("PRODUCT_NAME", "Product")
    ref_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    persona = tool_context.state.get(CUSTOMER_PERSONA_STATE_KEY, "")

    reference_parts = []
    reference_parts.append(types.Part.from_bytes(data=product_bytes, mime_type="image/png"))
    if asset_sheet_bytes:
        reference_parts.append(types.Part.from_bytes(data=asset_sheet_bytes, mime_type="image/png"))
    if logo_bytes:
        reference_parts.append(types.Part.from_bytes(data=logo_bytes, mime_type="image/png"))

    style_rule = _VARIATION_STYLES[variation_index % len(_VARIATION_STYLES)]
    brand_wall = _get_brand_wall_directive(company_name, guidelines=tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, ""))

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
    logo_uri = tool_context.state.get(LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY)
    if not logo_uri:
        logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)

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

async def generate_text_ad(tool_context: ToolContext, selected_campaign_name: str, segment_name: str):
    return {"status": "success", "headlines": ["Unlock Your Potential"], "descriptions": ["Premium rewards await you."]}
