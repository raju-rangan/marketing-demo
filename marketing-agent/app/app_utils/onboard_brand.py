import argparse
import json
import os
import sys
import base64
from google import genai
from google.genai import types

# A simple 1x1 transparent PNG encoded in base64
DUMMY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

def create_dummy_image(filepath):
    """Creates a small dummy PNG file if one doesn't exist."""
    if not os.path.exists(filepath):
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(DUMMY_PNG_B64))

def setup_brand_directories(brand_id):
    """Sets up the necessary directories and dummy assets for a brand."""
    brand_dir = os.path.join("app", "brands", brand_id)
    assets_dir = os.path.join(brand_dir, "assets")
    
    os.makedirs(brand_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)
    
    # Create dummy assets
    logo_path = os.path.join(assets_dir, "logo.png")
    product_path = os.path.join(assets_dir, "product_image.png")
    create_dummy_image(logo_path)
    create_dummy_image(product_path)
    
    print(f"📁 Created asset directory: {assets_dir}")
    print("   ↳ Generated dummy logo.png and product_image.png")
    return brand_dir, assets_dir

def generate_brand_artifacts(brand_name, brand_id, brand_dir, assets_dir, url=None):
    """Researches the brand using Gemini and generates config, presets, and prompt.md."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    if not project_id:
        print("❌ ERROR: GOOGLE_CLOUD_PROJECT environment variable not set.")
        sys.exit(1)

    # Initialize Gemini client
    client = genai.Client(
        vertexai=True,
        project=project_id,
        location="global"
    )
    
    # Define the expected GCS URIs
    gcs_base = f"gs://{{{{GOOGLE_CLOUD_BUCKET_ARTIFACTS}}}}/brands/{brand_id}/assets"
    expected_logo_uri = f"{gcs_base}/logo.png"
    expected_product_uri = f"{gcs_base}/product_image.png"

    # Research brand using Gemini
    prompt = f"""
    You are a marketing expert. I want to onboard a new brand called "{brand_name}" to my marketing agent.
    {f"The brand's website is: {url}" if url else ""}
    
    Please research this brand and provide the following information in JSON format.
    Return a SINGLE JSON object containing two keys: "config" and "preset".
    
    {{
      "config": {{
          "brand_name": "{brand_name}",
          "default_brand_preset": "A reasonable default product or service line for this brand",
          "brand_persona_description": "A detailed description of the marketing manager's persona, their job, needs, and how they sell to leadership.",
          "compliance_guidelines": "Key legal or industry-standard compliance rules specific to this brand's industry.",
          "brand_vault_table": "A markdown table with columns: Brand Name, Logo URI, Product Image URI, Color System, Tone. IMPORTANT: For the URIs, you MUST use EXACTLY these values: Logo URI = `{expected_logo_uri}`, Product Image URI = `{expected_product_uri}`.",
          "exclusion_rules": "Strict brand wall rules (what to avoid, competitors, etc.).",
          "brand_wall_rules": "Specific rules for maintaining brand purity across different sub-brands or portfolios."
      }},
      "preset": {{
          "company_name": "{brand_name}",
          "product_name": "Name of flagship product",
          "product_description": "Concise description",
          "target_audience": "Key demographic",
          "logo_uri": "{expected_logo_uri}",
          "product_image_uri": "{expected_product_uri}",
          "visual_identity": "Detailed visual rules for AI models. Include: Primary/Secondary Colors (with HEX codes), Photography Style (e.g. lifestyle vs studio), and Typography (e.g. Sans-serif).",
          "exclusion_rules": "Brand specific rules (e.g. No competitors, no specific colors)"
      }}
    }}
    
    Use Google Search if a URL is provided.
    """
    
    print("🤖 Consulting Gemini for brand insights...")
    try:
        model_name = os.environ.get("MODEL_NAME", "gemini-3-flash-preview")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                tools=[types.Tool(google_search=types.GoogleSearch())] if url else None
            )
        )
        
        raw_data = json.loads(response.text)
        
        # Handle case where model might return a list of objects
        if isinstance(raw_data, list):
             if len(raw_data) > 0 and isinstance(raw_data[0], dict) and "config" in raw_data[0]:
                 raw_data = raw_data[0]
             elif len(raw_data) == 2:
                 raw_data = {"config": raw_data[0], "preset": raw_data[1]}
             else:
                 raw_data = {"config": raw_data[0] if raw_data else {}}

        # Save config.json
        config_path = os.path.join(brand_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(raw_data.get("config", raw_data), f, indent=2)

        # Save presets.json (as a dictionary of presets)
        presets_path = os.path.join(brand_dir, "presets.json")
        default_preset_name = raw_data.get("config", {}).get("default_brand_preset", "Default Preset")
        presets_data = {
            default_preset_name: raw_data.get("preset", {})
        }
        with open(presets_path, "w") as f:
            json.dump(presets_data, f, indent=2)
            
        config_obj = raw_data.get("config", raw_data)
        generate_brand_prompt(brand_dir, config_obj)
        
        print(f"✅ Brand configuration saved to: {config_path}")
        print(f"✅ Default preset saved to: {presets_path}")
        print(f"\n💡 Next Steps:")
        print(f"1. Replace the dummy images in '{assets_dir}/' with your actual high-res assets.")
        print(f"2. Run the agent with: export ACTIVE_BRAND={brand_id} && make playground")
        print(f"   (This will automatically sync your local assets to GCS before starting).")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to onboard brand: {e}")
        sys.exit(1)

def generate_brand_prompt(brand_dir, config_obj):
    """Generates prompt.md from the template and brand config."""
    # Adjust path assuming this runs from the marketing-agent directory
    template_path = os.path.join("app", "prompt.template.md")
    
    # If the script is run from a different directory (like the test script), try to find it
    if not os.path.exists(template_path):
         # Try looking one level up or down based on typical structures, or use absolute paths if needed
         # For our test script, we might be in the root dir.
         alt_path = os.path.join("marketing-agent", "app", "prompt.template.md")
         if os.path.exists(alt_path):
             template_path = alt_path

    prompt_out_path = os.path.join(brand_dir, "prompt.md")
    if os.path.exists(template_path):
        with open(template_path, "r") as f:
            prompt_text = f.read()
        
        placeholders = [
            "BRAND_NAME", "BRAND_PERSONA_DESCRIPTION", "COMPLIANCE_GUIDELINES",
            "BRAND_VAULT_TABLE", "EXCLUSION_RULES", "BRAND_WALL_RULES", "DEFAULT_BRAND_PRESET"
        ]
        for p in placeholders:
            val = config_obj.get(p.lower(), f"MISSING_{p}")
            prompt_text = prompt_text.replace(f"{{{{{p}}}}}", str(val))
            
        with open(prompt_out_path, "w") as f:
            f.write(prompt_text)
        print(f"✅ Brand prompt saved to: {prompt_out_path}")
    else:
        print(f"⚠️ Could not find {template_path} to generate prompt.md")

def onboard_brand(brand_name, url=None):
    print(f"🚀 Onboarding brand: {brand_name}")
    if url:
        print(f"🔍 Researching brand at: {url}")
    
    brand_id = brand_name.lower().replace(" ", "_")
    brand_dir, assets_dir = setup_brand_directories(brand_id)
    generate_brand_artifacts(brand_name, brand_id, brand_dir, assets_dir, url)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--url", default=None)
    args = parser.parse_args()
    
    onboard_brand(args.name, args.url)

