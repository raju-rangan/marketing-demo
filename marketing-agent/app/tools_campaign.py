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

import json
from google.adk.tools.tool_context import ToolContext
from .adk_common.dtos.generated_media import GeneratedMedia
from .adk_common.utils import utils_agents, utils_gcs, utils_prompts
from .adk_common.utils.utils_logging import Severity, log_message

from .state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    GENERATED_GCS_URIS_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    CHOSEN_CAMPAIGN_IDEA_STATE_KEY,
    CHOSEN_ASSET_SHEET_ID_STATE_KEY,
    CUSTOMER_PERSONA_STATE_KEY,
    CUSTOMER_PERSONAS,
    GOOGLE_CLOUD_BUCKET_ARTIFACTS,
    AGENT_VERSION,
)
from .campaign_utils import (
    Campaign,
    parse_campaigns_from_xml,
)
from .generate_campaigns import generate_campaigns_xml
from .utils_gcs import set_output_folder

# Internal cache for campaigns
_CACHED_CAMPAIGNS_LIST: list[Campaign] | None = None
_CACHED_IDEAS_STRING: str | None = None

async def setup_product_campaign(
    tool_context: ToolContext,
    company_name: str,
    product_name: str,
    product_description: str,
    target_audience: str,
    logo_uri: str,
    product_image_uri: str,
    num_segments: int = 2,
    reference_guidelines: str = "",
):
    """Sets up the marketing campaign system for a new product. This MUST be called first.
    It generates campaign ideas, audience segments, and ad configurations.

    Args:
        company_name: The brand/company name.
        product_name: The product name.
        product_description: Description of the product.
        target_audience: Description of the target audience.
        logo_uri: GCS URI or URL of the brand logo image.
        product_image_uri: GCS URI or URL of the product image.
        num_segments: Number of audience segments per campaign (1-4, default 2).
        reference_guidelines: Extracted text content from user-provided reference documents.
    """
    global _CACHED_CAMPAIGNS_LIST, _CACHED_IDEAS_STRING
    _CACHED_CAMPAIGNS_LIST = None
    _CACHED_IDEAS_STRING = None

    tool_context.state[PRODUCT_COMPANY_NAME_STATE_KEY] = company_name
    tool_context.state["PRODUCT_NAME"] = product_name
    tool_context.state[PRODUCT_IMAGE_URI_STATE_KEY] = product_image_uri
    tool_context.state[LOGO_IMAGE_URI_STATE_KEY] = logo_uri

    # Display product image inline
    if product_image_uri and not tool_context.state.get("_product_image_displayed"):
        try:
            img_bytes, _ = utils_agents.download_bytes_from_reference(product_image_uri)
            if img_bytes:
                safe_name = product_name.replace(" ", "_")[:30]
                product_media = GeneratedMedia(
                    filename=f"product_{safe_name}.png", mime_type="image/png", media_bytes=img_bytes,
                )
                await utils_agents.save_to_artifact_and_render_asset(
                    asset=product_media, context=tool_context,
                    save_in_gcs=False, save_in_artifacts=True,
                )
                tool_context.state["_product_image_displayed"] = True
        except Exception as e:
            log_message(f"Failed to download product image: {e}", Severity.ERROR)

    tool_context.state[GENERATED_GCS_URIS_STATE_KEY] = []

    if reference_guidelines and reference_guidelines.strip():
        tool_context.state[REFERENCE_GUIDELINES_STATE_KEY] = reference_guidelines.strip()

    try:
        xml_content = generate_campaigns_xml(
            company_name=company_name,
            product_name=product_name,
            product_description=product_description,
            target_audience=target_audience,
            logo_uri=logo_uri,
            product_image_uri=product_image_uri,
            num_segments=num_segments,
            reference_guidelines=reference_guidelines,
        )
    except Exception as e:
        return {"status": "error", "details": f"Failed to generate campaigns: {e}"}

    try:
        campaigns = parse_campaigns_from_xml(xml_content)
        if not campaigns:
            return {"status": "error", "details": "No valid campaigns generated."}
        _CACHED_CAMPAIGNS_LIST = campaigns
        _CACHED_IDEAS_STRING = xml_content

        # Save to GCS for persistence if needed
        return {
            "status": "success",
            "campaign_ideas": [c.name for c in campaigns],
            "details": f"Successfully generated {len(campaigns)} campaign ideas."
        }
    except Exception as e:
        return {"status": "error", "details": f"Failed to parse campaigns: {e}"}

def get_campaign_idea(tool_context: ToolContext, quantity: int):
    """Returns a list of generated campaign ideas (names and taglines)."""
    if not _CACHED_CAMPAIGNS_LIST:
        return {"status": "error", "details": "No campaigns pre-generated. Run setup_product_campaign first."}
    
    ideas = [{"name": c.name, "tagline": c.tagline} for c in _CACHED_CAMPAIGNS_LIST[:quantity]]
    return {"status": "success", "ideas": ideas}

def save_selected_campaign(chosen_idea: str, tool_context: ToolContext):
    """Saves the user's chosen campaign idea to the session state."""
    tool_context.state[CHOSEN_CAMPAIGN_IDEA_STATE_KEY] = chosen_idea
    return {"status": "success", "selected_campaign": chosen_idea}

def get_selected_brief(tool_context: ToolContext, selected_campaign_name: str):
    """Returns the full creative brief for the selected campaign."""
    if not _CACHED_CAMPAIGNS_LIST:
        return {"status": "error", "details": "No campaigns found."}
    
    for c in _CACHED_CAMPAIGNS_LIST:
        if c.name == selected_campaign_name:
            return {"status": "success", "brief": c.__dict__}
    
    return {"status": "error", "details": f"Campaign '{selected_campaign_name}' not found."}

def set_customer_persona(tool_context: ToolContext, persona_number: int):
    """Sets the target customer persona for the campaign."""
    persona = CUSTOMER_PERSONAS.get(persona_number)
    if not persona:
        return {"status": "error", "details": f"Invalid persona number. Choose 1-{len(CUSTOMER_PERSONAS)}."}
    
    tool_context.state[CUSTOMER_PERSONA_STATE_KEY] = persona["description"]
    set_output_folder(tool_context)
    return {"status": "success", "persona": persona["name"], "description": persona["description"]}

def clear_customer_persona(tool_context: ToolContext):
    """Clears the customer persona from the session state."""
    if CUSTOMER_PERSONA_STATE_KEY in tool_context.state:
        tool_context.state[CUSTOMER_PERSONA_STATE_KEY] = None
    return {"status": "success", "details": "Customer persona cleared."}
