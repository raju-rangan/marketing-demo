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
from .shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video, overlay_logo_on_video

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
    Enforces a Title Slide for Slide 1 and targets 160 WPM.
    """
    log_message(f"Generating branded storyboard for {duration_minutes} min video...", Severity.INFO)

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Chase")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    # Calculate total word target
    total_word_target = duration_minutes * 160
    num_slides = max(12, min(20, duration_minutes * 3))
    words_per_slide = total_word_target // num_slides

    prompt = (
        f"You are an expert Lead Educational Producer for {company_name}.\n"
        f"Goal: Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast'.\n\n"
        f"STRUCTURE REQUIREMENTS:\n"
        f"- SLIDE 1 MUST BE A TITLE SLIDE: It should feature a bold, cinematic title of the topic and a welcoming, high-level introduction narration.\n"
        f"- TOTAL SLIDES: {num_slides} slides total.\n"
        f"- LOGO INTEGRATION: Every slide MUST have the {company_name} logo in the bottom right corner. Include this in the image_prompt.\n\n"
        f"DURATION & WORD COUNT TARGETS:\n"
        f"- Target Duration: {duration_minutes} minutes.\n"
        f"- Total Word Count: ~{total_word_target} words (speaking rate: 160 WPM).\n"
        f"- Target per slide: ~{words_per_slide} words of detailed narration.\n\n"
        f"CORE DIRECTIVES:\n"
        f"1. VISUAL SELF-SUFFICIENCY: Every image prompt MUST describe a professional infographic with text, diagrams, and data.\n"
        f"2. NARRATION: Each voiceover script MUST be a detailed educational segment (~{words_per_slide} words). Do NOT be concise.\n"
        f"3. BRANDING: Use {company_name}'s color palette (e.g., Chase Blue/White) for all designs.\n"
        f"4. VISUAL STYLE: Every slide MUST follow a 'PREMIUM STUDIO' aesthetic: clean white/grey backgrounds, precise studio lighting, and minimal composition. NO style variations across slides.\n\n"
        f"Research Report:\n{research_report}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"title\": \"Comprehensive Title\",\n"
        f"  \"slides\": [\n"
        f"    {{\n"
        f"      \"image_prompt\": \"[Title Slide layout for {company_name} with the topic title in large typography. Include logo in bottom right.]\",\n"
        f"      \"script\": \"[Introductory narration of approx {words_per_slide} words...]\",\n"
        f"      \"text_overlay\": \"\" \n"
        f"    }},\n"
        f"    {{\n"
        f"      \"image_prompt\": \"[Infographic layout...]\",\n"
        f"      \"script\": \"[Detailed educational narration...]\",\n"
        f"      \"text_overlay\": \"\" \n"
        f"    }}\n"
        f"  ],\n"
        f"  \"music_prompt\": \"Sophisticated, cinematic educational background music\"\n"
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

async def preview_slidecast_assets(tool_context: ToolContext, storyboard: dict) -> dict:
    """Generates actual images (with logo rendered by the model) and voiceover audio for review."""
    current_output_folder = set_output_folder(tool_context)
    log_message("Generating asset previews (including native logo rendering)...", Severity.INFO)

    logo_bytes = []
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    
    # Fallback to the provided Chase logo URL if no logo is in state
    if not logo_uri:
        logo_uri = "gs://cs-poc-edgd4dliruu2xvksuvo4r3g-artifacts/samples/chase_logo.png"
    
    if logo_uri:
        try:
            res = await utils_agents.load_resource(logo_uri, tool_context)
            if res and res.media_bytes:
                logo_bytes = [res.media_bytes]
        except Exception as e:
            log_message(f"Warning: Could not load logo as reference image: {e}", Severity.WARNING)

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    # Process slides in parallel
    async def process_slide(slide: SlidecastSlide, idx: int):
        log_message(f"Rendering preview for slide {idx+1}...", Severity.INFO)
        # 1. Generate Image (passing logo as reference)
        img_bytes = await _generate_gemini_image(slide.image_prompt, logo_bytes, label=f"slide_{idx+1}_image", aspect_ratio="16:9")
        if not img_bytes:
            raise ValueError(f"Failed to generate image for slide {idx+1}")

        # Save image as artifact
        img_media = GeneratedMedia(filename=f"slide_{idx+1}.png", mime_type="image/png", media_bytes=img_bytes)
        saved_img = await utils_agents.save_to_artifact_and_render_asset(
            asset=img_media, context=tool_context, save_in_gcs=True, gcs_folder=current_output_folder
        )
        slide.image_url = get_public_url(saved_img.gcs_uri)

        # 2. Generate Voiceover
        vo_bytes = await _generate_voiceover_audio(slide.script)
        if not vo_bytes:
            raise ValueError(f"Failed to generate voiceover for slide {idx+1}")

        # Save audio as artifact
        aud_media = GeneratedMedia(filename=f"audio_{idx+1}.mp3", mime_type="audio/mpeg", media_bytes=vo_bytes)
        saved_aud = await utils_agents.save_to_artifact_and_render_asset(
            asset=aud_media, context=tool_context, save_in_gcs=True, gcs_folder=current_output_folder
        )
        slide.audio_url = get_public_url(saved_aud.gcs_uri)

        return slide
    try:
        slide_tasks = [process_slide(slide, i) for i, slide in enumerate(sb.slides)]
        sb.slides = await asyncio.gather(*slide_tasks)

        # 3. Generate HTML Approval Page
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Slidecast Approval - {sb.title}</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background-color: #f4f7f9; color: #333; }}
                h1 {{ color: #004a99; border-bottom: 2px solid #004a99; padding-bottom: 10px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; background-color: white; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
                th, td {{ padding: 20px; text-align: left; border-bottom: 1px solid #eee; }}
                th {{ background-color: #004a99; color: white; text-transform: uppercase; letter-spacing: 1px; }}
                tr:hover {{ background-color: #f9f9f9; }}
                .slide-img {{ width: 320px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); transition: transform 0.2s; }}
                .slide-img:hover {{ transform: scale(1.05); }}
                .slide-num {{ font-size: 1.5em; font-weight: bold; color: #004a99; }}
                .talk-track {{ line-height: 1.6; font-size: 1.1em; color: #444; }}
                .audio-link {{ display: block; margin-top: 10px; color: #007bff; text-decoration: none; font-size: 0.9em; }}
                .audio-link:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>Slidecast Approval Page: {sb.title}</h1>
            <p>Please review the visual assets and narration tracks for each slide below. Once reviewed, return to the agent to approve or request changes.</p>
            <table>
                <thead>
                    <tr>
                        <th style="width: 50px;">#</th>
                        <th style="width: 350px;">Visual Asset</th>
                        <th>Talk Track (Narration)</th>
                    </tr>
                </thead>
                <tbody>
        """
        for i, slide in enumerate(sb.slides):
            html_content += f"""
                    <tr>
                        <td class="slide-num">{i+1}</td>
                        <td>
                            <img src="{slide.image_url}" class="slide-img" alt="Slide {i+1}">
                            <a href="{slide.audio_url}" class="audio-link" target="_blank">🔊 Listen to Audio Preview</a>
                        </td>
                        <td class="talk-track">{slide.script}</td>
                    </tr>
            """
        html_content += """
                </tbody>
            </table>
        </body>
        </html>
        """

        # Save HTML as artifact
        html_media = GeneratedMedia(filename="approval_page.html", mime_type="text/html", media_bytes=html_content.encode("utf-8"))
        saved_html = await utils_agents.save_to_artifact_and_render_asset(
            asset=html_media, context=tool_context, save_in_gcs=True, gcs_folder=current_output_folder
        )
        approval_url = get_public_url(saved_html.gcs_uri)

        return {
            "status": "success",
            "message": "Assets and Approval Page generated. Please review the approval page link below before proceeding.",
            "approval_page_url": approval_url,
            "storyboard": sb.model_dump()
        }
    except Exception as e:
        log_message(f"Preview generation failed: {e}", Severity.ERROR)
        return {"status": "error", "details": str(e)}

async def finalize_slidecast_video(tool_context: ToolContext, storyboard: dict) -> dict:
    """Compiles the approved assets into a final educational video with background music and logo."""
    current_output_folder = set_output_folder(tool_context)
    log_message("Finalizing slidecast video production...", Severity.INFO)

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    # Download/Prepare bytes for compilation
    slides_data = []
    for i, slide in enumerate(sb.slides):
        if not slide.image_url or not slide.audio_url:
            return {"status": "error", "details": f"Slide {i+1} is missing generated assets. Run preview first."}

        # Load from GCS/Cache
        img_res = await utils_agents.load_resource(slide.image_url, tool_context)
        aud_res = await utils_agents.load_resource(slide.audio_url, tool_context)

        if not img_res or not aud_res:
             return {"status": "error", "details": f"Failed to retrieve assets for slide {i+1}."}

        slides_data.append({
            "image_bytes": img_res.media_bytes,
            "audio_bytes": aud_res.media_bytes,
            "text_overlay": "" 
        })

    # Music & Logo
    music_prompt = sb.music_prompt or "Cinematic instrumental background music"
    music_bytes = await _generate_lyria_music(music_prompt, sb.title)

    logo_bytes = None
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    
    # Fallback to the provided Chase logo URL
    if not logo_uri:
        logo_uri = "gs://cs-poc-edgd4dliruu2xvksuvo4r3g-artifacts/samples/chase_logo.png"

    if logo_uri:
        try:
            res = await utils_agents.load_resource(logo_uri, tool_context)
            if res: logo_bytes = res.media_bytes
        except Exception: pass

    # Compile
    video_bytes = compile_slidecast_video(slides_data)
    if not video_bytes:
        return {"status": "error", "details": "Failed to compile slidecast video."}

    if music_bytes:
        video_bytes = mix_audio_onto_video(video_bytes, None, music_bytes)

    if logo_bytes:
        video_bytes = overlay_logo_on_video(video_bytes, logo_bytes)

    # Save final video
    filename = f"slidecast_final_{int(time.time())}.mp4"
    video_media = GeneratedMedia(filename=filename, mime_type="video/mp4", media_bytes=video_bytes)

    saved_video = await utils_agents.save_to_artifact_and_render_asset(
        asset=video_media, context=tool_context, save_in_gcs=True, save_in_artifacts=True, gcs_folder=current_output_folder
    )
    url = get_public_url(saved_video.gcs_uri)
    return {"status": "success", "video_url": url, "details": "Slidecast masterclass finalized and ready for viewing."}

