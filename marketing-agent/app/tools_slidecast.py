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

def generate_slidecast_storyboard(tool_context: ToolContext, research_report: str, duration_minutes: int = 5) -> dict:
    """Generates a long-form SlidecastStoryboard (JSON) from a research report.
    Designed for 5-7 minute educational videos (12-20 slides).
    """
    log_message(f"Generating long-form ({duration_minutes} min) educational storyboard...", Severity.INFO)
    
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "JPMC")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    # Estimate number of slides for the duration. Assuming ~20-30 seconds per slide.
    # 5 mins = 300s. 300 / 25 = 12 slides. 7 mins = 420s. 420 / 25 = 17 slides.
    num_slides = max(12, min(20, duration_minutes * 3))

    prompt = (
        f"You are an expert Lead Educational Producer for {company_name}.\n"
        f"Goal: Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast'.\n\n"
        f"CONTENT STRATEGY:\n"
        f"- Target Duration: {duration_minutes} minutes.\n"
        f"- Total Slides: {num_slides} distinct slides.\n"
        f"- Brand Wall: {brand_wall}\n"
        f"- Reference Guidelines: {brand_guidelines[:1000] if brand_guidelines else 'N/A'}\n\n"
        f"CORE DIRECTIVES:\n"
        f"1. SELF-SUFFICIENT VISUALS: Every image prompt MUST describe a professional infographic with text, diagrams, and data. "
        f"The visual MUST stand on its own.\n"
        f"2. LONG-FORM NARRATION: Each voiceover script MUST be a detailed educational segment (150-200 words). "
        f"Explain concepts in depth. Do NOT be concise. We want the user to fully understand the context.\n"
        f"3. ENGAGING FLOW: Design a logical progression from introduction -> core concepts -> deep dives -> conclusion.\n\n"
        f"Research Report:\n{research_report}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"title\": \"Mastering [Topic]: A Comprehensive Guide\",\n"
        f"  \"slides\": [\n"
        f"    {{\n"
        f"      \"image_prompt\": \"[Infographic layout for {company_name} with specific diagrams and data points]\",\n"
        f"      \"script\": \"[Detailed 150-200 word educational narration...]\",\n"
        f"      \"text_overlay\": \"\" \n"
        f"    }}\n"
        f"  ],\n"
        f"  \"music_prompt\": \"Sophisticated and steady educational background music for {company_name}\"\n"
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
        log_message(f"Long-form storyboard generation failed: {e}", Severity.ERROR)
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
