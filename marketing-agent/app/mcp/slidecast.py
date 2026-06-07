import json
import logging
from typing import List, Optional
from mcp.server.fastmcp import FastMCP
from .schemas import SlidecastManifest, BrandContext, NanomationPlan
from .generators.slidecast import generate_slidecast_manifest, update_slide_blueprint, plan_slide_animation, preview_slidecast_assets
from ..state import SLIDE_STYLES, VOICEOVER_STYLES, CHOSEN_SLIDE_STYLE_STATE_KEY, CHOSEN_VOICEOVER_STYLE_STATE_KEY, ANIMATE_SLIDECAST_STATE_KEY

logger = logging.getLogger(__name__)

def add_slidecast_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def select_slidecast_style(slide_style: str, voiceover_style: str, animate: bool = False) -> str:
        """
        Sets the visual and vocal style for the upcoming Slidecast.
        
        Args:
            slide_style: The visual aesthetic (e.g. 'Flat Vector Explainer', 'Documentary Realism'). 
            voiceover_style: The persona of the narrator (e.g. 'Energetic & Engaging', 'Professional & Trustworthy').
            animate: Whether to animate the slides using AI video generation (Veo). Default is False.
        """
        if slide_style not in SLIDE_STYLES:
            return json.dumps({"status": "error", "message": f"Invalid slide style. Choose from: {list(SLIDE_STYLES.keys())}"})
        if voiceover_style not in VOICEOVER_STYLES:
            return json.dumps({"status": "error", "message": f"Invalid voiceover style. Choose from: {list(VOICEOVER_STYLES.keys())}"})

        # In MCP stateless mode, we return the success message. 
        # The agent is responsible for remembering these choices or passing them to subsequent tools.
        animate_msg = "with AI video animations" if animate else "using static slides"
        return json.dumps({
            "status": "success", 
            "message": f"Style locked: {slide_style} / {voiceover_style} ({animate_msg})",
            "slide_style": slide_style,
            "voiceover_style": voiceover_style,
            "animate": animate
        })

    @mcp.tool()
    async def generate_animation_plan(slide_topic: str, company_name: str) -> str:
        """
        Creates a detailed multi-segment animation plan (Nanomation) for a specific slide topic.
        Returns a NanomationPlan JSON.
        """
        try:
            plan = await plan_slide_animation(slide_topic, company_name)
            return plan.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_slidecast_storyboard(
        company_name: str,
        urls: List[str] = None,
        reference_guidelines: str = "",
        customer_persona: str = "",
        duration_seconds: int = 300,
        language: str = "English",
        aspect_ratio: str = "16:9",
        trend_context: str = "",
        slide_style: str = "Documentary Realism"
    ) -> str:
        """
        Generates a comprehensive multi-slide presentation blueprint (Slidecast) grounded in source URLs.
        Dynamically scales slide count and pacing for short-form or long-form videos.
        Returns a SlidecastManifest JSON.
        """
        try:
            brand = BrandContext(
                company_name=company_name,
                reference_guidelines=reference_guidelines,
                customer_persona=customer_persona
            )
            
            manifest = await generate_slidecast_manifest(
                brand=brand,
                urls=urls,
                trend_context=trend_context,
                duration_seconds=duration_seconds,
                language=language,
                aspect_ratio=aspect_ratio,
                slide_style=slide_style
            )
            
            return manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to create slidecast: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def preview_slidecast_assets(manifest_json: str, reference_guidelines: str = "") -> str:
        """
        Generates the actual visual and audio assets for a slidecast manifest and compiles them into an Approval PDF.
        Returns the PDF link as the primary result.
        """
        try:
            manifest = SlidecastManifest.model_validate_json(manifest_json)
            brand = BrandContext(
                company_name=manifest.company_name,
                reference_guidelines=reference_guidelines
            )
            
            result = await preview_slidecast_assets(manifest, brand)
            
            # We return a formatted string that emphasizes the PDF and hides the individual image links from auto-rendering
            return json.dumps({
                "status": "success",
                "message": "Asset generation complete. Please review the consolidated Approval PDF below.",
                "approval_pdf_url": result["pdf_url"],
                "updated_manifest_json": json.dumps(result["manifest"]) # Stringified to prevent ADK from rendering sub-images
            }, indent=2)
            
        except Exception as e:
            logger.error(f"Failed to preview assets: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def update_storyboard_visual_style(manifest_json: str, new_style_name: str, reference_guidelines: str = "") -> str:
        """
        Rewrites all image prompts in a storyboard to match a new visual style.
        Returns the updated manifest JSON.
        """
        try:
            manifest = SlidecastManifest.model_validate_json(manifest_json)
            brand = BrandContext(
                company_name=manifest.company_name,
                reference_guidelines=reference_guidelines
            )
            
            updated_manifest = await update_storyboard_visual_style(manifest, new_style_name, brand)
            return updated_manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to update visual style: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def update_slidecast_slide(
        manifest_json: str,
        slide_index: int,
        instructions: str,
        reference_guidelines: str = ""
    ) -> str:
        """
        Updates a specific slide in an existing slidecast manifest.
        Takes the current manifest JSON and returns the modified version.
        """
        try:
            manifest = SlidecastManifest.model_validate_json(manifest_json)
            brand = BrandContext(
                company_name=manifest.company_name,
                reference_guidelines=reference_guidelines
            )
            
            updated_manifest = await update_slide_blueprint(
                manifest=manifest,
                slide_index=slide_index,
                instructions=instructions,
                brand=brand
            )
            
            return updated_manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to update slidecast: {e}")
            return json.dumps({"status": "error", "details": str(e)})
