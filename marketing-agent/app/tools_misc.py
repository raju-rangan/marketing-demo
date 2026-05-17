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
import os
from google.adk.tools.tool_context import ToolContext
from .adk_common.utils.utils_logging import Severity, log_message
from .adk_common.utils.utils_agents import SESSION_ARTIFACTS_STATE_KEY
from .state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    PRODUCT_SETUP_DONE_STATE_KEY,
    JPMC_LOGO_URI,
    SAPPHIRE_CARD_URI,
    FREEDOM_CARD_URI,
    PRIVATE_WEALTH_CARD_URI,
    ASSET_REGISTRY_STATE_KEY,
    UPLOAD_COUNTER_STATE_KEY,
)
from .utils_gcs import set_output_folder

def select_brand_preset(tool_context: ToolContext, preset_name: str):
    """Loads official brand guidelines, logos, card mockups, and compliance
    rules automatically for a JPMC brand preset.

    Args:
        preset_name: The JPMC brand line to load.
    """
    presets = {
        "Chase Sapphire Reserve": {
            "company_name": "Chase",
            "product_name": "Chase Sapphire Reserve Card",
            "product_description": "Premium metal credit card offering travel and dining rewards.",
            "target_audience": "Affluent jetsetters, young professionals.",
            "logo_uri": JPMC_LOGO_URI,
            "product_image_uri": SAPPHIRE_CARD_URI,
            "guide_file": "chase_sapphire_marketing_guide.md",
            "exclusion_rules": "STRICT BRAND WALL: Use ONLY 'Chase'. DO NOT mention 'J.P. Morgan', 'JPMorgan', or 'JPMC'."
        },
        "Chase Freedom Unlimited": {
            "company_name": "Chase",
            "product_name": "Chase Freedom Unlimited Card",
            "product_description": "Cashback credit card with zero annual fee.",
            "target_audience": "Everyday value seekers, students, families.",
            "logo_uri": JPMC_LOGO_URI,
            "product_image_uri": FREEDOM_CARD_URI,
            "guide_file": "chase_freedom_marketing_guide.md",
            "exclusion_rules": "STRICT BRAND WALL: Use ONLY 'Chase'. DO NOT mention 'J.P. Morgan', 'JPMorgan', or 'JPMC'."
        },
        "J.P. Morgan Private Wealth": {
            "company_name": "J.P. Morgan",
            "product_name": "J.P. Morgan Private Client Wealth Management",
            "product_description": "Exclusive wealth advisory and estate planning.",
            "target_audience": "Ultra-high-net-worth individuals.",
            "logo_uri": JPMC_LOGO_URI,
            "product_image_uri": PRIVATE_WEALTH_CARD_URI,
            "guide_file": "jp_morgan_private_wealth_marketing_guide.md",
            "exclusion_rules": "STRICT BRAND WALL: Use ONLY 'J.P. Morgan'. DO NOT mention 'Chase'."
        }
    }

    if preset_name not in presets:
        return {"status": "error", "details": f"Invalid brand preset '{preset_name}'."}

    preset = presets[preset_name]
    
    # Read the marketing guide from app/assets/samples
    guide_content = ""
    guide_path = os.path.join(os.path.dirname(__file__), "assets", "samples", preset["guide_file"])
    if os.path.exists(guide_path):
        try:
            with open(guide_path, "r") as f:
                guide_content = f.read()
        except Exception:
            pass

    # Inject exclusion rules at the TOP of guidelines
    final_guidelines = f"{preset['exclusion_rules']}\n\n{guide_content}" if guide_content else preset['exclusion_rules']

    tool_context.state[PRODUCT_COMPANY_NAME_STATE_KEY] = preset["company_name"]
    tool_context.state["PRODUCT_NAME"] = preset["product_name"]
    tool_context.state[PRODUCT_IMAGE_URI_STATE_KEY] = preset["product_image_uri"]
    tool_context.state[LOGO_IMAGE_URI_STATE_KEY] = preset["logo_uri"]
    tool_context.state[REFERENCE_GUIDELINES_STATE_KEY] = final_guidelines

    set_output_folder(tool_context)
    tool_context.state[PRODUCT_SETUP_DONE_STATE_KEY] = True

    return {"status": "success", "preset_loaded": preset_name}

def query_internal_knowledge_base(query: str, brand: str) -> str:
    """Queries the internal JPMC knowledge base for specific brand guidelines."""
    kb_path = os.path.join(os.path.dirname(__file__), "data", "website_kb.json")
    if not os.path.exists(kb_path):
        return "Knowledge base not found."
    
    try:
        with open(kb_path, "r") as f:
            kb = json.load(f)
        
        brand_data = kb.get(brand, [])
        if not brand_data:
            return f"No information found for brand '{brand}'."
        
        # Simple keyword matching
        for chunk in brand_data:
            if query.lower() in chunk["topic"].lower() or query.lower() in chunk["content"].lower():
                return chunk["content"]
        
        return f"No specific information found for '{query}' under brand '{brand}'."
    except Exception as e:
        return f"Error querying knowledge base: {e}"

def process_user_uploads(tool_context: ToolContext):
    """Scans for newly uploaded user images and registers them with high-priority tags."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    artifacts = tool_context.state.get(SESSION_ARTIFACTS_STATE_KEY, {})
    counter = tool_context.state.get(UPLOAD_COUNTER_STATE_KEY, 0)
    
    new_uploads = []
    # Identify images that are in artifacts but not in our registry
    registry_uris = set(registry.values())
    
    for art_id, art_data in artifacts.items():
        uri = art_data.get("asset", {}).get("gcs_uri")
        mime = art_data.get("asset", {}).get("mime_type", "")
        if uri and uri not in registry_uris and "image" in mime.lower():
            # It's a new image upload!
            counter += 1
            tag = f"upload-{counter}"
            registry[tag] = uri
            new_uploads.append(tag)
            log_message(f"Auto-registered user upload: {tag} -> {uri}", Severity.INFO)

    if new_uploads:
        tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
        tool_context.state[UPLOAD_COUNTER_STATE_KEY] = counter
        return {"status": "success", "registered_uploads": new_uploads}
    
    return {"status": "success", "details": "No new uploads found."}

def rename_asset_tag(tool_context: ToolContext, old_tag: str, new_tag: str):
    """Renames an asset tag in the registry for easier reference."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    if old_tag not in registry:
        return {"status": "error", "details": f"Tag '{old_tag}' not found."}
    
    registry[new_tag] = registry.pop(old_tag)
    tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
    return {"status": "success", "old_tag": old_tag, "new_tag": new_tag}

async def deploy_react_website(tool_context: ToolContext, brand_name: str, html_code: str) -> dict:
    """Simulates deploying a React-based landing page for the campaign."""
    return {"status": "success", "url": "https://chase-demo-landing-page.web.app", "details": "Website deployed successfully!"}
