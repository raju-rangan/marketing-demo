import asyncio
import json
import time
from typing import List

from google.adk.tools.tool_context import ToolContext
from .adk_common.dtos.generated_media import GeneratedMedia
from .adk_common.utils import utils_agents
from .adk_common.utils.utils_logging import Severity, log_message
from google import genai
from google.genai import types

from .state import (
    GOOGLE_CLOUD_PROJECT,
    PRODUCT_COMPANY_NAME_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
)
from .utils_gcs import get_public_url, set_output_folder
from .schema import SlidecastStoryboard, SlidecastSlide

from .tools_media import (
    _generate_gemini_image,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _get_brand_wall_directive,
)
from shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video, overlay_logo_on_video

# Initialize GenAI Client
client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")

def research_urls_to_report(tool_context: ToolContext, urls: List[str]) -> str:
    """Researches a list of URLs using Gemini Search Grounding and creates a consolidated insight report."""
    log_message(f"Starting research on {len(urls)} URLs...", Severity.INFO)
    
    url_list_str = "\n".join([f"- {url}" for url in urls])
    prompt = (
        f"Research the following URLs and synthesize a comprehensive educational report based on their content.\n"
        f"Extract key insights, statistics, and best practices that would make for an engaging educational video.\n\n"
        f"URLs to research:\n{url_list_str}\n\n"
        f"Structure the report with clear headings, bullet points, and an executive summary."
    )

    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return response.text if response.text else "Failed to generate report from search."
    except Exception as e:
        log_message(f"Research failed: {e}", Severity.ERROR)
        return f"Error during research: {e}"

def generate_slidecast_storyboard(tool_context: ToolContext, research_report: str) -> dict:
    """Generates a SlidecastStoryboard (JSON) from a research report, following brand guidelines."""
    log_message("Generating branded information-rich storyboard...", Severity.INFO)
    
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "JPMC")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    prompt = (
        f"You are an expert educational video producer for {company_name}.\n"
        f"Based on the following research report, create a storyboard for an in-depth educational video.\n"
        f"The video should have 5 to 10 slides.\n\n"
        f"BRAND CONTEXT:\n"
        f"- Company: {company_name}\n"
        f"{brand_wall}\n"
        f"- Reference Guidelines: {brand_guidelines[:1000] if brand_guidelines else 'N/A'}\n\n"
        f"CORE DIRECTIVES:\n"
        f"1. VISUAL SELF-SUFFICIENCY: Every image prompt MUST include instructions for Gemini to render SPECIFIC text, diagrams, or infographics. "
        f"The viewer should understand the slide even without audio.\n"
        f"2. BRAND INTEGRATION: Incorporate {company_name}'s color palette and visual identity into every slide's design (e.g., in panels, charts, and text).\n"
        f"3. DETAILED NARRATION: The voiceover script should be thorough, educational, and match the brand's tone. (50-100 words per slide).\n"
        f"4. INTEGRATED DESIGN: Prompt for professional typography and high-contrast labels to be part of the image itself.\n\n"
        f"Research Report:\n{research_report}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"title\": \"Comprehensive Video Title\",\n"
        f"  \"slides\": [\n"
        f"    {{\n"
        f"      \"image_prompt\": \"A professional branded infographic slide for {company_name}. [Specific layout and data visualizations]...\",\n"
        f"      \"script\": \"[Detailed, educational narration...]\",\n"
        f"      \"text_overlay\": \"\" \n"
        f"    }}\n"
        f"  ],\n"
        f"  \"music_prompt\": \"Sophisticated, cinematic, and educational background music matching {company_name}'s brand vibe\"\n"
        f"}}"
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )
        
        # Verify JSON
        storyboard_data = json.loads(response.text)
        return storyboard_data
    except Exception as e:
        log_message(f"Storyboard generation failed: {e}", Severity.ERROR)
        return {"error": str(e)}

async def produce_slidecast_video(tool_context: ToolContext, storyboard: dict) -> dict:
    """Generates all media assets and compiles a final educational video. Overlays brand logo."""
    current_output_folder = set_output_folder(tool_context)
    log_message("Producing branded slidecast video assets...", Severity.INFO)
    
    logo_bytes = None
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    if logo_uri:
        try:
            res = await utils_agents.load_resource(logo_uri, tool_context)
            if res: logo_bytes = res.media_bytes
        except Exception: pass

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    slides_data = []
    
    # Process slides in parallel for speed
    async def process_slide(slide: SlidecastSlide, idx: int):
        log_message(f"Generating assets for slide {idx+1}...", Severity.INFO)
        # Generate image (which now contains text/infographics)
        img_bytes = await _generate_gemini_image(slide.image_prompt, [], label=f"slide_{idx+1}_image")
        if not img_bytes:
            log_message(f"Image generation failed for slide {idx+1}", Severity.ERROR)
            raise ValueError(f"Failed to generate image for slide {idx+1}")

        # Generate detailed voiceover
        vo_bytes = await _generate_voiceover_audio(slide.script)
        if not vo_bytes:
            log_message(f"Voiceover generation failed for slide {idx+1}", Severity.ERROR)
            raise ValueError(f"Failed to generate voiceover for slide {idx+1}")

        log_message(f"Slide {idx+1} assets ready. Image: {len(img_bytes)} bytes, VO: {len(vo_bytes)} bytes", Severity.INFO)
        return {
            "image_bytes": img_bytes,
            "audio_bytes": vo_bytes,
            "text_overlay": "" 
        }

    try:
        slide_tasks = [process_slide(slide, i) for i, slide in enumerate(sb.slides)]
        slides_data = await asyncio.gather(*slide_tasks)
    except Exception as e:
        log_message(f"Asset generation failed: {e}", Severity.ERROR)
        return {"status": "error", "details": f"Asset generation failed: {e}"}

    # Generate music
    music_prompt = sb.music_prompt or "Cinematic instrumental background music"
    log_message(f"Generating background music: {music_prompt}...", Severity.INFO)
    music_bytes = await _generate_lyria_music(music_prompt, sb.title)
    if music_bytes:
        log_message(f"Music generated: {len(music_bytes)} bytes", Severity.INFO)
    else:
        log_message("Music generation returned None, proceeding without background music.", Severity.WARNING)

    # Compile video
    log_message("Compiling video...", Severity.INFO)

    video_bytes = compile_slidecast_video(slides_data)
    
    if not video_bytes:
        return {"status": "error", "details": "Failed to compile slidecast video."}

    # Mix music
    if music_bytes:
        log_message("Mixing background music...", Severity.INFO)
        video_bytes = mix_audio_onto_video(video_bytes, None, music_bytes)

    # Overlay Logo
    if logo_bytes:
        log_message("Overlaying brand logo...", Severity.INFO)
        video_bytes = overlay_logo_on_video(video_bytes, logo_bytes)

    # Save to artifacts/GCS
    filename = f"slidecast_video_{int(time.time())}.mp4"
    video_media = GeneratedMedia(filename=filename, mime_type="video/mp4", media_bytes=video_bytes)
    
    try:
        # Use utils_agents helper to store and return the url
        saved_media = await utils_agents.save_to_artifact_and_render_asset(
            asset=video_media, 
            context=tool_context, 
            save_in_gcs=True, 
            save_in_artifacts=True, 
            gcs_folder=current_output_folder
        )
        url = get_public_url(saved_media.gcs_uri)
        return {"status": "success", "video_url": url, "details": "Slidecast generated successfully."}
    except Exception as e:
         return {"status": "error", "details": f"Failed to save video: {e}"}
