import json
import logging
from mcp.server.fastmcp import FastMCP
from .schemas import StoryboardManifest, StoryboardAct
from .generators import _generate_storyline

logger = logging.getLogger(__name__)

def add_storyboard_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def generate_campaign_plan(
        company_name: str,
        product_name: str,
        campaign_rationale: str = "A cinematic journey",
        reference_guidelines: str = "",
        customer_persona: str = "",
        duration_seconds: int = 24
    ) -> str:
        """
        Creates a bold, emotional video storyline and multi-act storyboard structure for a general product campaign (Shorts or Ads).
        
        WHEN TO USE:
        Use this for general marketing campaigns and video ads. DO NOT use this for Slidecasts/presentations (use generate_story_arc instead).
        
        ARGS:
        - company_name, product_name: Brand context.
        - campaign_rationale: High-level strategy (e.g., from trend analysis).
        - duration_seconds: Target video length.
        
        RETURNS:
        A JSON string containing the StoryboardManifest.
        """
        try:
            logger.info(f"Generating storyline for {company_name} - {product_name}")
            # Call the stateless helper from tools_media.py
            storyline_data = await _generate_storyline(
                company_name=company_name,
                product_name=product_name,
                rationale=campaign_rationale,
                reference_guidelines=reference_guidelines,
                customer_persona=customer_persona,
                duration_seconds=duration_seconds
            )
            
            # Map raw dict into our strict Pydantic model
            acts = []
            for raw_act in storyline_data.get("acts", []):
                acts.append(StoryboardAct(
                    act_number=raw_act.get("act_number", 1),
                    scene_description=raw_act.get("scene_description", ""),
                    end_scene_description=raw_act.get("end_scene_description"),
                    motion_prompt=raw_act.get("motion_prompt", "Cinematic camera movement"),
                    voiceover=raw_act.get("voiceover", ""),
                    timestamped_visual_actions=raw_act.get("timestamped_visual_actions")
                ))
            
            manifest = StoryboardManifest(
                company_name=company_name,
                product_name=product_name,
                duration_seconds=duration_seconds,
                storyline=storyline_data.get("storyline", ""),
                lyria_prompt=storyline_data.get("lyria_prompt", ""),
                acts=acts
            )
            
            # Return serialized JSON string of the Pydantic model
            return manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to create storyboard: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    # You could also add an `update_storyboard` tool here later that takes an existing
    # StoryboardManifest and modifies specific acts based on feedback.
