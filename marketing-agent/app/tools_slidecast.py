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
    GOOGLE_CLOUD_BUCKET_ARTIFACTS,
    PRODUCT_COMPANY_NAME_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    LOGO_IMAGE_URI_STATE_KEY,
    SLIDE_STYLES,
    VOICEOVER_STYLES,
    CHOSEN_SLIDE_STYLE_STATE_KEY,
    CHOSEN_VOICEOVER_STYLE_STATE_KEY,
)
from .utils_gcs import get_public_url, set_output_folder
from .schema import SlidecastStoryboard, SlidecastSlide, NanomationPlan, NanomationPhase

from .tools_media import (
    _generate_gemini_image,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _get_brand_wall_directive,
)
from .shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video, overlay_logo_on_video
from fpdf import FPDF
import io

# Initialize GenAI Client
client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")

def _generate_approval_pdf(title: str, slides: List[SlidecastSlide], slide_images: List[bytes]) -> bytes:
    """Generates a professional PDF for asset approval."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Add Title Page
    pdf.add_page()
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(0, 74, 153) # Chase Blue
    pdf.cell(0, 40, "Slidecast Approval Document", ln=True, align="C")
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 20, title, ln=True, align="C")
    pdf.ln(20)
    
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(51, 51, 51)
    pdf.multi_cell(0, 10, "Please review the visual assets and narration tracks for each slide below. This document serves as the formal storyboard for your educational video.")
    pdf.ln(10)

    # Add Slides
    for i, (slide, img_bytes) in enumerate(zip(slides, slide_images)):
        if i % 2 == 0 and i > 0:
            pdf.add_page()
        
        pdf.set_font("helvetica", "B", 14)
        pdf.set_text_color(0, 74, 153)
        pdf.cell(0, 10, f"Slide {i+1}", ln=True)
        pdf.ln(5)
        
        # Add Image
        with io.BytesIO(img_bytes) as img_io:
            # We use a temporary filename or just pass the stream if supported by fpdf2
            pdf.image(img_io, x=15, w=100)
        
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Talk Track:", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(68, 68, 68)
        pdf.multi_cell(0, 6, slide.script)
        pdf.ln(15)

    return pdf.output()

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

def generate_slidecast_storyboard(tool_context: ToolContext, research_report: str, duration_minutes: int = 5, language: str = "English") -> dict:
    """Generates a long-form SlidecastStoryboard (JSON) from a research report.
    Enforces a Title Slide for Slide 1 and targets 160 WPM.
    """
    log_message(f"Generating branded storyboard for {duration_minutes} min video in {language}...", Severity.INFO)

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Chase")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    # Style & Word Count
    total_word_target = duration_minutes * 160
    num_slides = max(12, min(20, duration_minutes * 3))
    words_per_slide = total_word_target // num_slides
    
    selected_style_name = tool_context.state.get(CHOSEN_SLIDE_STYLE_STATE_KEY, "Flat Vector Explainer")
    style_desc = SLIDE_STYLES.get(selected_style_name, SLIDE_STYLES["Flat Vector Explainer"])

    prompt = (
        f"You are an expert Lead Educational Producer for {company_name}.\n"
        f"Goal: Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast' in {language}.\n\n"
        f"LANGUAGE REQUIREMENT:\n"
        f"- ALL NARRATION SCRIPTS MUST BE WRITTEN IN {language}.\n"
        f"- ALL VISUAL TEXT (titles, labels, infographic text) DESCRIBED IN IMAGE PROMPTS MUST BE WRITTEN IN {language}.\n"
        f"- Use formal, professional {language} appropriate for an executive educational video.\n\n"
        f"STRUCTURE REQUIREMENTS:\n"
        f"- SLIDE 1 MUST BE A TITLE SLIDE: It should feature a bold, cinematic title of the topic in {language} and a welcoming, high-level introduction narration in {language}.\n"
        f"- TOTAL SLIDES: {num_slides} slides total.\n"
        f"- LOGO INTEGRATION: Every slide MUST have the {company_name} logo in the bottom right corner. Include this in the image_prompt.\n\n"
        f"DURATION & WORD COUNT TARGETS:\n"
        f"- Target Duration: {duration_minutes} minutes.\n"
        f"- Total Word Count: ~{total_word_target} words (speaking rate: 160 WPM).\n"
        f"- Target per slide: ~{words_per_slide} words of detailed narration.\n\n"
        f"CORE DIRECTIVES:\n"
        f"1. VISUAL SELF-SUFFICIENCY: Every image prompt MUST describe a professional infographic with text, diagrams, and data. ALL TEXT LABELS MUST BE IN {language}.\n"
        f"2. NARRATION: Each voiceover script MUST be a detailed educational segment (~{words_per_slide} words) written in {language}. Do NOT be concise.\n"
        f"3. BRANDING: Use {company_name}'s color palette (e.g., Chase Blue/White) for all designs.\n"
        f"4. VISUAL STYLE: {style_desc} NO style variations across slides. Avoid overly metallic or glossy surfaces unless the prompt specifically requires a technological detail.\n\n"
        f"Research Report:\n{research_report}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"title\": \"Comprehensive Title in {language}\",\n"
        f"  \"summary_arc\": [\"[High-level phase 1]\", \"[High-level phase 2]\", ...],\n"
        f"  \"slides\": [\n"
        f"    {{\n"
        f"      \"slide_title\": \"[Concise Slide Title]\",\n"
        f"      \"image_prompt\": \"[Title Slide layout for {company_name} with the topic title in large typography in {language}. Include logo in bottom right. ALL text on the slide MUST be in {language}.]\",\n"
        f"      \"script\": \"[Introductory narration in {language} of approx {words_per_slide} words...]\",\n"
        f"      \"text_overlay\": \"\" \n"
        f"    }},\n"
        f"    {{\n"
        f"      \"slide_title\": \"[Concise Slide Title]\",\n"
        f"      \"image_prompt\": \"[Infographic layout with data and labels in {language}. Include logo in bottom right...]\",\n"
        f"      \"script\": \"[Detailed educational narration in {language}...]\",\n"
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
    """Generates actual images and voiceover audio for review."""
    current_output_folder = set_output_folder(tool_context)
    log_message("Generating asset previews...", Severity.INFO)

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    # Style selection
    selected_voice_name = tool_context.state.get(CHOSEN_VOICEOVER_STYLE_STATE_KEY, "Energetic & Engaging")
    voice_id = VOICEOVER_STYLES.get(selected_voice_name, VOICEOVER_STYLES["Energetic & Engaging"])

    # Process slides in parallel
    async def process_slide(slide: SlidecastSlide, idx: int):
        log_message(f"Rendering preview for slide {idx+1}...", Severity.INFO)
        # 1. Generate Image (logo-free)
        img_bytes = await _generate_gemini_image(slide.image_prompt, [], label=f"slide_{idx+1}_image", aspect_ratio="16:9")
        if not img_bytes:
            raise ValueError(f"Failed to generate image for slide {idx+1}")

        # Save image as artifact
        img_media = GeneratedMedia(filename=f"slide_{idx+1}.png", mime_type="image/png", media_bytes=img_bytes)
        saved_img = await utils_agents.save_to_artifact_and_render_asset(
            asset=img_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        slide.image_url = get_public_url(saved_img.gcs_uri)

        # 2. Generate Voiceover
        vo_bytes = await _generate_voiceover_audio(slide.script, voice_name=voice_id)
        if not vo_bytes:
            raise ValueError(f"Failed to generate voiceover for slide {idx+1}")

        # Save audio as artifact
        aud_media = GeneratedMedia(filename=f"audio_{idx+1}.mp3", mime_type="audio/mpeg", media_bytes=vo_bytes)
        saved_aud = await utils_agents.save_to_artifact_and_render_asset(
            asset=aud_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        slide.audio_url = get_public_url(saved_aud.gcs_uri)

        return slide, img_bytes

    try:
        slide_tasks = [process_slide(slide, i) for i, slide in enumerate(sb.slides)]
        results = await asyncio.gather(*slide_tasks)
        
        sb.slides = [r[0] for r in results]
        slide_images = [r[1] for r in results]

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

        # Save HTML as artifact (GCS ONLY - Avoid large byte attachments in response)
        html_media = GeneratedMedia(filename="approval_page.html", mime_type="text/html", media_bytes=html_content.encode("utf-8"))
        saved_html = await utils_agents.save_to_artifact_and_render_asset(
            asset=html_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        approval_url = get_public_url(saved_html.gcs_uri)

        # 4. Generate PDF Approval Page (GCS ONLY - Avoid large byte attachments in response)
        pdf_bytes = _generate_approval_pdf(sb.title, sb.slides, slide_images)
        pdf_media = GeneratedMedia(filename="approval_document.pdf", mime_type="application/pdf", media_bytes=pdf_bytes)
        saved_pdf = await utils_agents.save_to_artifact_and_render_asset(
            asset=pdf_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        pdf_url = get_public_url(saved_pdf.gcs_uri)

        return {
            "status": "success",
            "message": "Assets generated. Please review the HTML approval page or download the PDF document below.",
            "approval_page_url": approval_url,
            "approval_pdf_url": pdf_url,
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
        logo_uri = f"gs://{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/samples/chase_logo.png"

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
        asset=video_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
    )
    url = get_public_url(saved_video.gcs_uri)
    return {"status": "success", "video_url": url, "details": "Slidecast masterclass finalized and ready for viewing."}

def select_slidecast_style(tool_context: ToolContext, slide_style: str = "Clean Corporate", voiceover_style: str = "Energetic & Engaging") -> dict:
    """Sets the visual and vocal style for the upcoming Slidecast.
    
    Args:
        slide_style: The visual aesthetic (e.g., 'Clean Corporate', 'Modern Minimalist', 'Financial Executive', 'Tech Forward').
        voiceover_style: The persona of the narrator (e.g., 'Energetic & Engaging', 'Professional & Trustworthy', 'Calm & Sophisticated', 'Authoritative & Wise').
    """
    if slide_style not in SLIDE_STYLES:
        return {"status": "error", "message": f"Invalid slide style. Choose from: {list(SLIDE_STYLES.keys())}"}
    if voiceover_style not in VOICEOVER_STYLES:
        return {"status": "error", "message": f"Invalid voiceover style. Choose from: {list(VOICEOVER_STYLES.keys())}"}

    tool_context.state[CHOSEN_SLIDE_STYLE_STATE_KEY] = slide_style
    tool_context.state[CHOSEN_VOICEOVER_STYLE_STATE_KEY] = voiceover_style
    
    log_message(f"Slidecast style locked: {slide_style} / {voiceover_style}", Severity.INFO)
    return {
        "status": "success", 
        "message": f"Style confirmed. I will now use the '{slide_style}' visual aesthetic and the '{voiceover_style}' voice for your Slidecast.",
        "slide_style": slide_style,
        "voiceover_style": voiceover_style
    }

def generate_slide_animation_plan(tool_context: ToolContext, slide_topic: str, duration_seconds: int = 5) -> dict:
    """Generates a NanomationPlan (JSON) for a specific slide topic to create a 5-step progressive animation.
    Based on the 'Nano Banana' (Imagen 3) concept of precise, consistent sequential image generation.
    """
    log_message(f"Planning nanomation for: {slide_topic}...", Severity.INFO)
    
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Chase")
    
    prompt = (
        f"You are a Senior Motion Designer for {company_name}.\n"
        f"Goal: Plan a 5-frame 'Nanomation' (consistent progressive animation) for the topic: '{slide_topic}'.\n\n"
        f"CONCEPT (Nano Banana):\n"
        f"- We will generate a sequence of 5 images showing a clear progression.\n"
        f"- Each frame must build on the previous one with localized, precise changes.\n"
        f"- Target high consistency: The background and core subjects must remain stable while specific actions progress.\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"target\": \"[High-level description of the entire animated sequence]\",\n"
        f"  \"progression_type\": \"linear\",\n"
        f"  \"phases\": [\n"
        f"    {{\"description\": \"[Description of frame 1]\", \"image_prompt\": \"[Detailed prompt for Imagen 3]\"}},\n"
        f"    {{\"description\": \"[Description of frame 2]\", \"image_prompt\": \"[Localized change from frame 1]\"}},\n"
        f"    ...\n"
        f"  ],\n"
        f"  \"topic\": \"{slide_topic}\"\n"
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
        return json.loads(response.text)
    except Exception as e:
        log_message(f"Nanomation planning failed: {e}", Severity.ERROR)
        return {"error": str(e)}

async def execute_slide_animation(tool_context: ToolContext, animation_plan: dict) -> dict:
    """Executes a NanomationPlan by generating 5 consistent frames using a sequential feedback loop.
    Each frame uses the previous frame as a reference to ensure 'surgical precision' consistency (Nano Banana).
    """
    current_output_folder = set_output_folder(tool_context)
    log_message("Executing nanomation sequence...", Severity.INFO)

    try:
        plan = NanomationPlan.model_validate(animation_plan)
    except Exception as e:
        return {"status": "error", "details": f"Invalid plan: {e}"}

    frames_bytes = []
    image_urls = []
    
    # Sequential Generation for Consistency (Nano Banana style)
    # Each frame (after the first) uses the previous frame as a reference.
    for i, phase in enumerate(plan.phases):
        log_message(f"Generating frame {i+1}/5: {phase.description}", Severity.INFO)
        
        # Use previous frame as reference for surgical consistency
        refs = [frames_bytes[-1]] if frames_bytes else []
        
        # Call the existing image generation tool
        img_bytes = await _generate_gemini_image(phase.image_prompt, refs, label=f"nanomation_f{i+1}", aspect_ratio="16:9")
        
        if not img_bytes:
            log_message(f"Failed to generate frame {i+1}", Severity.ERROR)
            break
        
        frames_bytes.append(img_bytes)
        
        # Save frame to registry/artifacts
        media = GeneratedMedia(filename=f"nanomation_{int(time.time())}_{i+1}.png", mime_type="image/png", media_bytes=img_bytes)
        saved = await utils_agents.save_to_artifact_and_render_asset(
            asset=media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        phase.image_url = get_public_url(saved.gcs_uri)
        image_urls.append(phase.image_url)

    if not image_urls:
        return {"status": "error", "details": "No frames generated successfully."}

    return {
        "status": "success",
        "message": f"Nanomation sequence '{plan.topic}' generated successfully. Review the {len(image_urls)} frames below.",
        "plan": plan.model_dump(),
        "image_urls": image_urls
    }

