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
import sys
import json
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.skills import load_skill_from_dir
from google.adk.tools import AgentTool
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.models import Gemini

from app.state import (
    PRODUCT_COMPANY_NAME_STATE_KEY,
    CHOSEN_CAMPAIGN_IDEA_STATE_KEY,
    CHOSEN_ASSET_SHEET_ID_STATE_KEY,
    PRODUCT_SETUP_DONE_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    ASSET_REGISTRY_STATE_KEY,
    DEMO_COMPANY_NAME,
    ROOT_AGENT_MODEL,
)
from app.adk_common.utils.utils_gcs import get_public_url

# ============================================================
# Dynamic Instruction Provider
# ============================================================

def _dynamic_instruction_provider(context: ReadonlyContext) -> str:
    # 1. Determine active brand
    active_brand = os.environ.get("ACTIVE_BRAND", "goog")
    brand_dir = os.path.join(os.path.dirname(__file__), "brands", active_brand)

    # 2. Load the brand's specific prompt.md
    prompt_path = os.path.join(brand_dir, "prompt.md")
    
    # Fallback to the goog prompt if the active brand's prompt is missing
    if not os.path.exists(prompt_path):
        prompt_path = os.path.join(os.path.dirname(__file__), "brands", "goog", "prompt.md")
    
    try:
        with open(prompt_path, "r") as f:
            prompt = f.read()
    except FileNotFoundError:
        # Failsafe if goog/prompt.md isn't generated yet (e.g. during tests)
        prompt = "You are the Marketing Agent. (prompt.md missing)"

    # 3. Fill dynamic session state variables (These change during the conversation)
    company_name = context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, DEMO_COMPANY_NAME)
    selected_campaign = context.state.get(CHOSEN_CAMPAIGN_IDEA_STATE_KEY, "Not selected yet")
    selected_asset_sheet = context.state.get(CHOSEN_ASSET_SHEET_ID_STATE_KEY, "Not selected yet")
    product_setup_done = context.state.get(PRODUCT_SETUP_DONE_STATE_KEY, False)

    reference_guidelines = context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    has_guidelines = "Yes — guidelines loaded and active" if reference_guidelines else "No reference documents provided"

    # Asset Registry Summary
    registry = context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    registry_summary = "\n".join([f"- {tag}: {os.path.basename(uri)}" for tag, uri in registry.items()]) if registry else "Empty"

    # Note: The template variables below still exist in the generated prompt files
    # to allow the agent to reflect the current state back to the user.
    prompt = prompt.replace("{{DEMO_COMPANY_NAME}}", str(company_name))
    prompt = prompt.replace("{{SELECTED_CAMPAIGN_NAME}}", str(selected_campaign))
    prompt = prompt.replace("{{SELECTED_ASSET_SHEET_URI}}", str(selected_asset_sheet))
    prompt = prompt.replace("{{PRODUCT_SETUP_DONE}}", str(product_setup_done))
    prompt = prompt.replace("{{REFERENCE_GUIDELINES_STATUS}}", has_guidelines)
    prompt = prompt.replace("{{ASSET_REGISTRY_SUMMARY}}", registry_summary)
        
    # 4. Generic Environment Variable Resolver
    # Replaces any remaining {{ENV_VAR}} with its value from os.environ
    import re
    def replace_env_var(match):
        env_var_name = match.group(1)
        return os.environ.get(env_var_name, f"MISSING_ENV_{env_var_name}")
    
    prompt = re.sub(r"\{\{([A-Z0-9_]+)\}\}", replace_env_var, prompt)
    
    return prompt

# ============================================================
# ADK Skills
# ============================================================

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

marketing_skills = SkillToolset(
    skills=[
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "slidecast-production")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "shorts-production")),
        # load_skill_from_dir(os.path.join(_SKILLS_DIR, "nanomation")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "trend-analysis")),
        load_skill_from_dir(os.path.join(_SKILLS_DIR, "autopilot-pitch")),
    ],
)

# ============================================================
# Root Agent Definition
# ============================================================

# Define the MCP Toolset connection
video_production_mcp = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=['-m', 'app.mcp_server.server'],
            env={**os.environ} # Pass all current environment variables
        ),
        timeout=1200.0  # 20 minutes to support longer VEO generation
    )
)

root_agent = Agent(
    name="marketing_agent",
    model=Gemini(model=ROOT_AGENT_MODEL),
    instruction=_dynamic_instruction_provider,
    description="Video-Focused Marketing Agent. Handles long-form Slidecasts and short-form video generation.",
    tools=[
        video_production_mcp,
        marketing_skills,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
