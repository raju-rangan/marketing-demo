import json
import logging
import os
import re
from typing import List

from ...state import LLM_GEMINI_MODEL_MARKETING_ANALYST
from .core import _retry_generate_content
from ..schemas import BrandContext
from google.genai import types

logger = logging.getLogger(__name__)

async def get_market_trends(product_category: str, company_name: str) -> str:
    """Searches for current market trends related to a product category."""
    prompt = (
        f"You are a HIGH-LEVEL STRATEGIC ANALYST. Perform a trend analysis for {product_category}.\n"
        f"Identify 3 emerging macro-trends that {company_name} can capitalize on in a video campaign.\n"
        f"Focus on consumer sentiment, technological shifts, and lifestyle changes.\n"
        f"Return a structured summary with 'Trend', 'Insight', and 'Campaign Opportunity'."
    )
    
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=1.0
    )
    
    response = await _retry_generate_content(
        model=LLM_GEMINI_MODEL_MARKETING_ANALYST,
        contents=prompt,
        config=config,
        label="trend-search"
    )
    
    return response.text if response else "No trends found."

async def query_kb(query: str, brand_name: str) -> str:
    """Queries the internal knowledge base for brand-specific guidelines or documents."""
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    # Determine the directory relative to this file
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    kb_path = os.path.join(base_dir, "brands", active_brand, "data", "kb.json")
    
    if not os.path.exists(kb_path):
        return f"Knowledge base not found for brand '{active_brand}'."
    
    try:
        with open(kb_path, "r") as f:
            kb = json.load(f)
        
        brand_data = kb.get(brand_name, [])
        if not brand_data and kb:
             brand_data = kb.get(next(iter(kb.keys())), [])
        
        if not brand_data:
            return f"No information found for '{brand_name}' in knowledge base."
        
        for chunk in brand_data:
            if query.lower() in chunk["topic"].lower() or query.lower() in chunk["content"].lower():
                return chunk["content"]
        
        return f"No specific information found for '{query}' under brand '{brand_name}'."
    except Exception as e:
        return f"Error querying knowledge base: {e}"

async def load_brand_context(preset_name: str = None) -> BrandContext:
    """Stateless loader for brand presets."""
    from ...adk_common.utils import utils_gcs
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    brand_dir = os.path.join(base_dir, "brands", active_brand)
    
    # 1. Load config
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

    preset_name = preset_name or default_preset
    
    # 2. Load presets
    presets_path = os.path.join(brand_dir, "presets.json")
    presets = {}
    if os.path.exists(presets_path):
        try:
            with open(presets_path, "r") as f:
                presets = json.load(f)
        except Exception: pass

    if not preset_name or preset_name not in presets:
        if presets: preset_name = list(presets.keys())[0]
        else: raise ValueError(f"No presets found for brand {active_brand}")

    preset = presets[preset_name]
    
    def resolve_placeholders(text: str) -> str:
        if not text: return ""
        return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: os.environ.get(m.group(1), m.group(0)), text)

    # Assets
    raw_logo_uri = resolve_placeholders(preset.get("logo_uri", ""))
    logo_uri = utils_gcs.get_public_url(raw_logo_uri) if raw_logo_uri else None
    
    visual_identity = resolve_placeholders(preset.get("visual_identity", ""))
    
    # Append dynamically extracted style prompt if it exists
    style_prompt_path = os.path.join(brand_dir, "assets", "style_prompt.txt")
    if os.path.exists(style_prompt_path):
        with open(style_prompt_path, "r") as f:
            visual_identity += f"\n\n### AUTOMATICALLY EXTRACTED STYLE DIRECTIVE\n{f.read()}"

    exclusion_rules = resolve_placeholders(preset.get("exclusion_rules", ""))
    
    final_guidelines = (
        f"### GLOBAL BRAND VAULT\n{resolve_placeholders(brand_vault_info)}\n\n"
        f"### PRODUCT VISUAL IDENTITY\n{visual_identity}\n\n"
        f"### BRAND WALL & EXCLUSIONS\n{exclusion_rules}"
    )

    bucket_name = os.environ.get("GOOGLE_CLOUD_BUCKET_ARTIFACTS")
    style_ref_uri = None
    if bucket_name:
        style_ref_uri = f"gs://{bucket_name}/brands/{active_brand}/assets/reference_image.png"

    return BrandContext(
        company_name=preset.get("company_name", active_brand.upper()),
        reference_guidelines=final_guidelines,
        logo_uri=logo_uri,
        customer_persona=preset.get("customer_persona", ""),
        style_reference_image_uri=style_ref_uri
    )

async def register_assets_stateless(existing_uris: List[str], new_uris: List[str]) -> dict:
    """Stateless logic for registering new asset uploads."""
    from ...adk_common.utils import utils_gcs
    registry_uris = set(existing_uris)
    new_registrations = []
    
    # We simulate the counter by checking existing size
    counter = len(existing_uris)
    
    for uri in new_uris:
        if uri not in registry_uris:
            counter += 1
            tag = f"upload-{counter}"
            # Ensure every registered link is accessible via a signed URL
            public_uri = utils_gcs.get_public_url(uri)
            new_registrations.append({"tag": tag, "uri": public_uri})
            
    return {"status": "success", "new_registrations": new_registrations}

async def generate_campaign_briefs(
    company_name: str,
    product_name: str,
    product_description: str,
    target_audience: str,
    num_campaigns: int = 3
) -> str:
    """Generates creative campaign ideas and audience segments."""
    from .core import _retry_generate_content
    from ...state import STORYLINE_MODEL
    
    prompt = (
        f"You are a CREATIVE STRATEGIST for {company_name}.\n"
        f"Generate {num_campaigns} distinct video campaign ideas for {product_name}.\n"
        f"Product: {product_description}\n"
        f"Audience: {target_audience}\n"
        f"Return a structured strategy with Campaign Name, Concept, and Segments."
    )
    
    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=1.0),
        label="campaign-gen"
    )
    
    return response.text if response else "No campaign ideas generated."



