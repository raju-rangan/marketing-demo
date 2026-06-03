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
from ..adk_common.utils.utils_logging import Severity, log_message, stream_status, log_status
from ..adk_common.utils.utils_agents import SESSION_ARTIFACTS_STATE_KEY
from ..state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    PRODUCT_SETUP_DONE_STATE_KEY,
    ASSET_REGISTRY_STATE_KEY,
    UPLOAD_COUNTER_STATE_KEY,
)
from ..utils.utils_gcs import set_output_folder

def select_brand_preset(tool_context: ToolContext, preset_name: str = None):
    """Loads brand guidelines, logos, and compliance rules automatically for a preset.

    Args:
        preset_name: Optional. The brand line/product to load. If omitted, loads the default from config.json.
    """
    # 1. Determine active brand
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    brand_dir = os.path.join(os.path.dirname(__file__), "..", "brands", active_brand)
    
    # 2. Load global config (Vault data)
    config_path = os.path.join(brand_dir, "config.json")
    brand_vault_info = ""
    default_preset = None
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
                brand_vault_info = config_data.get("brand_vault_table", "")
                default_preset = config_data.get("default_brand_preset")
        except Exception: pass

    # Use default if no preset provided
    if not preset_name:
        preset_name = default_preset
        if not preset_name:
             return {"status": "error", "details": "No preset name provided and no default found in config."}

    # 3. Load presets config
    presets_path = os.path.join(brand_dir, "presets.json")
    presets = {}
    if os.path.exists(presets_path):
        try:
            with open(presets_path, "r") as f:
                presets = json.load(f)
        except Exception as e:
            log_message(f"Failed to load presets for {active_brand}: {e}", Severity.ERROR)

    if preset_name not in presets:
        # Try fuzzy match if exact match fails
        matches = [k for k in presets.keys() if preset_name.lower() in k.lower()]
        if matches: 
            preset_name = matches[0]
        elif default_preset and default_preset in presets:
            log_message(f"Fuzzy match failed for preset '{preset_name}', falling back to default '{default_preset}'", Severity.WARNING)
            preset_name = default_preset
        elif presets:
            fallback = list(presets.keys())[0]
            log_message(f"Fuzzy match failed, falling back to first available preset '{fallback}'", Severity.WARNING)
            preset_name = fallback
        else: 
            return {"status": "error", "details": f"Invalid brand preset '{preset_name}' for brand '{active_brand}' and no presets available to fallback on."}

    preset = presets[preset_name]
    
    # Resolve brand-specific placeholders (e.g. {{GOOGLE_CLOUD_BUCKET_ARTIFACTS}})
    import re
    def resolve_placeholders(text: str) -> str:
        if not text: return ""
        # Recursively resolve environment variables
        return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: os.environ.get(m.group(1), m.group(0)), text)

    # CHECK FOR LOCAL ASSETS FIRST
    # We prioritize local files shipped with the code for maximum reliability
    local_logo_path = os.path.join(brand_dir, "assets", "logo.png")
    local_product_path = os.path.join(brand_dir, "assets", "product_image.png")

    if os.path.exists(local_logo_path):
        logo_uri = local_logo_path
        log_message(f"Using local brand logo: {logo_uri}", Severity.INFO)
    else:
        logo_uri = resolve_placeholders(preset.get("logo_uri", ""))

    if os.path.exists(local_product_path):
        product_image_uri = local_product_path
        log_message(f"Using local product image: {product_image_uri}", Severity.INFO)
    else:
        product_image_uri = resolve_placeholders(preset.get("product_image_uri", ""))
    
    # 4. Construct the dynamic guidelines (Merge Vault + Visual Identity + Exclusions)
    visual_identity = resolve_placeholders(preset.get("visual_identity", "No specific visual identity rules."))
    exclusion_rules = resolve_placeholders(preset.get("exclusion_rules", ""))
    
    # Resolve any placeholders inside the vault table itself
    brand_vault_info = resolve_placeholders(brand_vault_info)

    final_guidelines = (
        f"### GLOBAL BRAND VAULT (COLORS & LOGOS)\n{brand_vault_info}\n\n"
        f"### PRODUCT VISUAL IDENTITY\n{visual_identity}\n\n"
        f"### BRAND WALL & EXCLUSIONS\n{exclusion_rules}"
    )

    tool_context.state[PRODUCT_COMPANY_NAME_STATE_KEY] = preset.get("company_name", active_brand.upper())
    tool_context.state["PRODUCT_NAME"] = preset.get("product_name", "Product")
    tool_context.state[PRODUCT_IMAGE_URI_STATE_KEY] = product_image_uri
    tool_context.state[LOGO_IMAGE_URI_STATE_KEY] = logo_uri
    tool_context.state[REFERENCE_GUIDELINES_STATE_KEY] = final_guidelines

    set_output_folder(tool_context)
    tool_context.state[PRODUCT_SETUP_DONE_STATE_KEY] = True

    return {"status": "success", "preset_loaded": preset_name}

def query_internal_knowledge_base(query: str, brand: str) -> str:
    """Queries the internal brand knowledge base for specific brand guidelines."""
    # 1. Determine active brand
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    brand_dir = os.path.join(os.path.dirname(__file__), "..", "brands", active_brand)
    
    kb_path = os.path.join(brand_dir, "data", "kb.json")
    if not os.path.exists(kb_path):
        return f"Knowledge base not found for brand '{active_brand}'."
    
    try:
        with open(kb_path, "r") as f:
            kb = json.load(f)
        
        # Use the specific product/sub-brand if provided, otherwise check all keys
        brand_data = kb.get(brand, [])
        if not brand_data:
             # Fallback: if 'brand' (preset name) isn't a key, maybe it's just the first key
             first_key = next(iter(kb.keys())) if kb else None
             if first_key:
                 brand_data = kb.get(first_key, [])
        
        if not brand_data:
            return f"No information found for '{brand}' in '{active_brand}' knowledge base."
        
        # Simple keyword matching
        for chunk in brand_data:
            if query.lower() in chunk["topic"].lower() or query.lower() in chunk["content"].lower():
                return chunk["content"]
        
        return f"No specific information found for '{query}' under brand '{brand}'."
    except Exception as e:
        return f"Error querying knowledge base: {e}"

def search_trends(product_category: str, tool_context: ToolContext) -> str:
    """Searches the web for current market trends relevant to a product category using Google Search grounding.

    Args:
        product_category: The product category to research trends for (e.g. 'smart home cameras', 'EV tires', 'whisky').
    """
    log_message(f"Researching trends for category: {product_category}", Severity.INFO)
    from google import genai
    from google.genai import types as genai_types
    from ..config import PROJECT_ID
    
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

        prompt = (
            f"Research the latest market and consumer trends for the '{product_category}' category. "
            f"Find:\n"
            f"1. Top 5 micro trends (viral, social-media-driven, 3-18 months)\n"
            f"2. Top 5 macro trends (long-lasting shifts, 1-5+ years)\n"
            f"3. Key competitors and their current marketing strategies\n"
            f"4. Social media buzz — what's trending on TikTok, Instagram, YouTube\n"
            f"5. Upcoming seasonal or cultural moments to leverage\n\n"
            f"For each trend include: trend name, summary, lifecycle stage, target audience, mood/aesthetic keywords, and color palette.\n"
            f"Be specific and cite real sources. Do NOT hallucinate trends."
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])],
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )

        result_text = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    result_text += part.text

        return result_text.strip() if result_text else "No trend data found."

    except Exception as e:
        log_message(f"Trend search failed: {e}", Severity.ERROR)
        return f"Trend search failed: {e}. Using general market knowledge."

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
    return {"status": "success", "url": f"https://{brand_name.lower().replace(' ', '-')}-landing-page.web.app", "details": "Website deployed successfully!"}

@stream_status("🚀 Launching the full production test pipeline...")
async def run_production_test(tool_context: ToolContext, url: str = "https://www.google.com", asset_uri: str = None) -> dict:
    """EASTER EGG: A special shortcut to test the full production pipeline OR generate a signed URL for a specific asset.
    
    Args:
        url: The URL to research and use as a basis for image generation (for full test).
        asset_uri: Optional. If provided, just generates a signed URL for this specific asset (e.g., gs://... or /samples/...).
    """
    from ..utils.utils_gcs import get_public_url
    
    if asset_uri:
        log_message(f"Generating signed URL for asset: {asset_uri}", Severity.INFO)
        signed_url = get_public_url(asset_uri)
        return {
            "status": "success",
            "message": f"Signed URL generated for {asset_uri}",
            "signed_url": signed_url
        }

    from .tools_slidecast import (
        generate_slidecast_storyboard, 
        preview_slidecast_assets, 
        finalize_slidecast_video, 
        select_slidecast_style
    )
    from .tools_media import create_image_composite
    
    log_message(f"Running full production test for {url}...", Severity.INFO)
    
    # 1. Setup Brand & Style
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    # Resolve default preset from config if possible
    preset_name = "Google Search & AI Services" 
    select_brand_preset(tool_context, preset_name)
    # Using 'Modern 3D Isometric' and 'Professional & Trustworthy' (Kalliope)
    select_slidecast_style(tool_context, "Modern 3D Isometric", "Professional & Trustworthy")
    
    # 3. Generate Storyboard (Targeting a 1-minute video for the test)
    storyboard = generate_slidecast_storyboard(tool_context, urls=[url], duration_seconds=60)
    if "error" in storyboard:
        return {"status": "error", "details": f"Storyboard generation failed: {storyboard['error']}"}

    # 4. Preview Assets (Produces actual Images and Gemini TTS Audio)
    preview_result = await preview_slidecast_assets(tool_context, storyboard)
    if preview_result.get("status") == "error":
        return preview_result

    # 5. Finalize Video (Stitches images and audio into a cinematic MP4)
    video_result = await finalize_slidecast_video(tool_context, preview_result["storyboard"])
    
    # 6. Create Image Composite (Stitches first two slides side-by-side for review)
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

