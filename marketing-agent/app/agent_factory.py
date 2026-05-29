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
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.skills import load_skill_from_dir
from google.adk.tools import AgentTool
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.models import Gemini

from .state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    CHOSEN_CAMPAIGN_IDEA_STATE_KEY,
    CHOSEN_ASSET_SHEET_ID_STATE_KEY,
    PRODUCT_SETUP_DONE_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    ASSET_REGISTRY_STATE_KEY,
    DEMO_COMPANY_NAME,
    JPMC_LOGO_URI,
    SAPPHIRE_CARD_URI,
    FREEDOM_CARD_URI,
    PRIVATE_WEALTH_CARD_URI,
)
from .utils.utils_gcs import get_public_url

# Import tools
from .tools.tools_campaign import (
    setup_product_campaign,
    get_campaign_idea,
    save_selected_campaign,
    get_selected_brief,
    set_customer_persona,
    clear_customer_persona,
)
from .tools.tools_media import (
    generate_text_ad,
    generate_display_ad,
    generate_campaign_storyboard,
    generate_video_from_storyboard,
    create_image_composite,
)
from .tools.tools_misc import (
    select_brand_preset,
    query_internal_knowledge_base,
    process_user_uploads,
    rename_asset_tag,
    deploy_react_website,
    run_production_test,
)

from .tools.tools_slidecast import (
    research_urls_to_report,
    generate_slidecast_storyboard,
    preview_slidecast_assets,
    finalize_slidecast_video,
    select_slidecast_style,
    generate_slide_animation_plan,
    execute_slide_animation,
)

# Import sub-agents
from .sub_agents.trend_spotter import TrendSpotter

# ============================================================
# Dynamic Instruction Provider
# ============================================================

def _dynamic_instruction_provider(context: ReadonlyContext) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
    with open(prompt_path, "r") as f:
        prompt_template = f.read()

    company_name = context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, DEMO_COMPANY_NAME)
    selected_campaign = context.state.get(CHOSEN_CAMPAIGN_IDEA_STATE_KEY, "Not selected yet")
    selected_asset_sheet = context.state.get(CHOSEN_ASSET_SHEET_ID_STATE_KEY, "Not selected yet")
    product_setup_done = context.state.get(PRODUCT_SETUP_DONE_STATE_KEY, False)

    reference_guidelines = context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    has_guidelines = "Yes — guidelines loaded and active" if reference_guidelines else "No reference documents provided"

    # Asset Registry Summary
    registry = context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    registry_summary = "\n".join([f"- {tag}: {os.path.basename(uri)}" for tag, uri in registry.items()]) if registry else "Empty"

    prompt = prompt_template.replace("{{AGENT_NAME}}", "JPMCAgent")
    prompt = prompt.replace("{{DEMO_COMPANY_NAME}}", str(company_name))
    prompt = prompt.replace("{{SELECTED_CAMPAIGN_NAME}}", str(selected_campaign))
    prompt = prompt.replace("{{SELECTED_ASSET_SHEET_URI}}", str(selected_asset_sheet))
    prompt = prompt.replace("{{PRODUCT_SETUP_DONE}}", str(product_setup_done))
    prompt = prompt.replace("{{REFERENCE_GUIDELINES_STATUS}}", has_guidelines)
    prompt = prompt.replace("{{ASSET_REGISTRY_SUMMARY}}", registry_summary)
    
    # Inject JPMC brand assets
    prompt = prompt.replace("{{JPMC_LOGO_URI}}", JPMC_LOGO_URI if JPMC_LOGO_URI else "")
    prompt = prompt.replace("{{SAPPHIRE_CARD_URI}}", SAPPHIRE_CARD_URI if SAPPHIRE_CARD_URI else "")
    prompt = prompt.replace("{{FREEDOM_CARD_URI}}", FREEDOM_CARD_URI if FREEDOM_CARD_URI else "")
    prompt = prompt.replace("{{PRIVATE_WEALTH_CARD_URI}}", PRIVATE_WEALTH_CARD_URI if PRIVATE_WEALTH_CARD_URI else "")
    
    return prompt

# ============================================================
# ADK Skills
# ============================================================

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

marketing_skills = SkillToolset(
    skills=[
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "ad-copywriting")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "video-storytelling")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "visual-direction")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "brand-strategy")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "trend-analysis")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "platform-specs")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "financial-marketing")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "website-design")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "slide-design")),
    ],
)

# ============================================================
# Root Agent Definition
# ============================================================

trend_spotter_agent = TrendSpotter()

root_agent = Agent(
    name="marketing_agent",
    model=Gemini(model="gemini-3-flash-preview"),
    instruction=_dynamic_instruction_provider,
    description="Combined JPMC Marketing Campaign Agent. Handles ideation, creative direction, and media generation.",
    tools=[
        marketing_skills,
        setup_product_campaign,
        get_campaign_idea,
        save_selected_campaign,
        get_selected_brief,
        set_customer_persona,
        clear_customer_persona,
        generate_text_ad,
        generate_display_ad,
        generate_campaign_storyboard,
        generate_video_from_storyboard,
        select_brand_preset,
        query_internal_knowledge_base,
        process_user_uploads,
        rename_asset_tag,
        deploy_react_website,
        research_urls_to_report,
        generate_slidecast_storyboard,
        preview_slidecast_assets,
        finalize_slidecast_video,
        select_slidecast_style,
        generate_slide_animation_plan,
        execute_slide_animation,
        create_image_composite,
        run_production_test,
        AgentTool(agent=trend_spotter_agent.agent),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
