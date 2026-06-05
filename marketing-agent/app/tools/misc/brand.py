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
from ...adk_common.utils.utils_logging import Severity, log_message
from ...state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    PRODUCT_IMAGE_URI_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY,
    LOGO_VERTICAL_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    PRODUCT_SETUP_DONE_STATE_KEY,
)
from ...utils.utils_gcs import set_output_folder

def select_brand_preset(tool_context: ToolContext, preset_name: str = None):
    """Loads brand guidelines, logos, and compliance rules automatically for a preset.

    Args:
        preset_name: Optional. The brand line/product to load. If omitted, loads the default from config.json.
    """
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    brand_dir = os.path.join(os.path.dirname(__file__), "..", "..", "brands", active_brand)
    
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

    if not preset_name:
        preset_name = default_preset
        if not preset_name:
             return {"status": "error", "details": "No preset name provided and no default found in config."}

    presets_path = os.path.join(brand_dir, "presets.json")
    presets = {}
    if os.path.exists(presets_path):
        try:
            with open(presets_path, "r") as f:
                presets = json.load(f)
        except Exception as e:
            log_message(f"Failed to load presets for {active_brand}: {e}", Severity.ERROR)

    if preset_name not in presets:
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
    
    import re
    def resolve_placeholders(text: str) -> str:
        if not text: return ""
        return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: os.environ.get(m.group(1), m.group(0)), text)

    local_logo_path = os.path.join(brand_dir, "assets", "logo.png")
    local_logo_horiz_path = os.path.join(brand_dir, "assets", "logo_horizontal.png")
    local_logo_vert_path = os.path.join(brand_dir, "assets", "logo_vertical.png")
    local_product_path = os.path.join(brand_dir, "assets", "product_image.png")

    logo_horiz_uri = ""
    logo_vert_uri = ""
    logo_uri = ""

    if os.path.exists(local_logo_horiz_path):
        logo_horiz_uri = local_logo_horiz_path
        log_message(f"Using local horizontal brand logo: {logo_horiz_uri}", Severity.INFO)
    else:
        logo_horiz_uri = resolve_placeholders(preset.get("logo_horizontal_uri", ""))

    if os.path.exists(local_logo_vert_path):
        logo_vert_uri = local_logo_vert_path
        log_message(f"Using local vertical brand logo: {logo_vert_uri}", Severity.INFO)
    else:
        logo_vert_uri = resolve_placeholders(preset.get("logo_vertical_uri", ""))

    if os.path.exists(local_logo_path):
        logo_uri = local_logo_path
        log_message(f"Using local brand logo: {logo_uri}", Severity.INFO)
    else:
        logo_uri = resolve_placeholders(preset.get("logo_uri", ""))

    if not logo_horiz_uri:
        logo_horiz_uri = logo_uri
    if not logo_vert_uri:
        logo_vert_uri = logo_uri
    if not logo_uri:
        logo_uri = logo_horiz_uri or logo_vert_uri

    if os.path.exists(local_product_path):
        product_image_uri = local_product_path
        log_message(f"Using local product image: {product_image_uri}", Severity.INFO)
    else:
        product_image_uri = resolve_placeholders(preset.get("product_image_uri", ""))
    
    visual_identity = resolve_placeholders(preset.get("visual_identity", "No specific visual identity rules."))
    exclusion_rules = resolve_placeholders(preset.get("exclusion_rules", ""))
    
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
    tool_context.state[LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY] = logo_horiz_uri
    tool_context.state[LOGO_VERTICAL_IMAGE_URI_STATE_KEY] = logo_vert_uri
    tool_context.state[REFERENCE_GUIDELINES_STATE_KEY] = final_guidelines

    set_output_folder(tool_context)
    tool_context.state[PRODUCT_SETUP_DONE_STATE_KEY] = True

    return {"status": "success", "preset_loaded": preset_name}

def query_internal_knowledge_base(query: str, brand: str) -> str:
    """Queries the internal brand knowledge base for specific brand guidelines."""
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    brand_dir = os.path.join(os.path.dirname(__file__), "..", "..", "brands", active_brand)
    
    kb_path = os.path.join(brand_dir, "data", "kb.json")
    if not os.path.exists(kb_path):
        return f"Knowledge base not found for brand '{active_brand}'."
    
    try:
        with open(kb_path, "r") as f:
            kb = json.load(f)
        
        brand_data = kb.get(brand, [])
        if not brand_data:
             first_key = next(iter(kb.keys())) if kb else None
             if first_key:
                 brand_data = kb.get(first_key, [])
        
        if not brand_data:
            return f"No information found for '{brand}' in '{active_brand}' knowledge base."
        
        for chunk in brand_data:
            if query.lower() in chunk["topic"].lower() or query.lower() in chunk["content"].lower():
                return chunk["content"]
        
        return f"No specific information found for '{query}' under brand '{brand}'."
    except Exception as e:
        return f"Error querying knowledge base: {e}"
