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
)
from .utils_gcs import get_public_url, set_output_folder
from .schema import SlidecastStoryboard, SlidecastSlide

from .tools_media import (
    _generate_gemini_image,
    _generate_voiceover_audio,
    _generate_lyria_music,
)
from shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video

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
    """Generates a SlidecastStoryboard (JSON) from a research report."""
    log_message("Generating storyboard from research report...", Severity.INFO)
    
    prompt = (
        f"You are an expert educational video producer.\n"
        f"Based on the following research report, create a compelling storyboard for a short educational video.\n"
        f"The video should have 4 to 8 slides.\n"
        f"For each slide, provide:\n"
        f"1. A detailed image prompt for a photorealistic or high-quality illustration.\n"
        f"2. An engaging voiceover script (20-40 words per slide).\n"
        f"3. A concise text overlay (2-6 words) that highlights the main point.\n\n"
        f"Research Report:\n{research_report}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"title\": \"Video Title\",\n"
        f"  \"slides\": [\n"
        f"    {{\n"
        f"      \"image_prompt\": \"Cinematic shot of...\",\n"
        f"      \"script\": \"Welcome to our deep dive...\",\n"
        f"      \"text_overlay\": \"The Beginning\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"music_prompt\": \"Upbeat educational electronic background music\"\n"
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
    """Generates all media assets and compiles a final educational video based on a storyboard."""
    current_output_folder = set_output_folder(tool_context)
    log_message("Producing slidecast video assets...", Severity.INFO)
    
    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    slides_data = []
    
    # Process slides in parallel for speed
    async def process_slide(slide: SlidecastSlide, idx: int):
        log_message(f"Generating assets for slide {idx+1}...", Severity.INFO)
        # Generate image
        img_bytes = await _generate_gemini_image(slide.image_prompt, [], label=f"slide_{idx+1}_image")
        if not img_bytes:
            raise ValueError(f"Failed to generate image for slide {idx+1}")
            
        # Generate voiceover
        vo_bytes = await _generate_voiceover_audio(slide.script)
        if not vo_bytes:
            raise ValueError(f"Failed to generate voiceover for slide {idx+1}")
            
        return {
            "image_bytes": img_bytes,
            "audio_bytes": vo_bytes,
            "text_overlay": slide.text_overlay or ""
        }

    try:
        slide_tasks = [process_slide(slide, i) for i, slide in enumerate(sb.slides)]
        slides_data = await asyncio.gather(*slide_tasks)
    except Exception as e:
        return {"status": "error", "details": f"Asset generation failed: {e}"}

    # Generate music
    music_prompt = sb.music_prompt or "Cinematic instrumental background music"
    log_message(f"Generating background music: {music_prompt}...", Severity.INFO)
    music_bytes = await _generate_lyria_music(music_prompt, sb.title)

    # Compile video
    log_message("Compiling video...", Severity.INFO)
    video_bytes = compile_slidecast_video(slides_data)
    
    if not video_bytes:
        return {"status": "error", "details": "Failed to compile slidecast video."}

    # Mix music
    if music_bytes:
        log_message("Mixing background music...", Severity.INFO)
        video_bytes = mix_audio_onto_video(video_bytes, None, music_bytes)

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
