import asyncio
import json
import time
import tempfile
import os
from typing import List

from google.adk.tools.tool_context import ToolContext
from ..adk_common.dtos.generated_media import GeneratedMedia
from ..adk_common.utils import utils_agents, utils_gcs
from ..adk_common.utils.utils_logging import Severity, log_message, stream_status, log_status
from google import genai
from google.genai import types
from ..state import (
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
from ..utils.utils_gcs import get_public_url, set_output_folder
from ..schema import SlidecastStoryboard, SlidecastSlide, NanomationPlan, NanomationPhase

from .tools_media import (
    _generate_gemini_image,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _get_brand_wall_directive,
)
from .tools_misc import select_brand_preset
from ..shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video, overlay_logo_on_video
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
    pdf.set_text_color(0, 0, 0) # Use brand primary color
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
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, f"Slide {i+1}", ln=True)
        pdf.ln(5)
        
        # Add Image
        temp_img_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                temp_file.write(img_bytes)
                temp_img_path = temp_file.name
            
            pdf.image(temp_img_path, x=15, w=100)
        except Exception as e:
            log_message(f"Error adding image to PDF: {repr(e)}", Severity.ERROR)
            raise
        finally:
            if temp_img_path and os.path.exists(temp_img_path):
                os.remove(temp_img_path)
        
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Talk Track:", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(68, 68, 68)
        pdf.multi_cell(0, 6, slide.script)
        pdf.ln(15)

    return pdf.output()

@stream_status("🔍 Researching and grounding insights from URLs...")
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

@stream_status("📋 Designing the educational storyboard...")
def generate_slidecast_storyboard(tool_context: ToolContext, research_report: str, duration_minutes: int = 5, language: str = "English") -> dict:
    """Generates a long-form SlidecastStoryboard (JSON) from a research report.
    Enforces a Title Slide for Slide 1 and targets 160 WPM.
    """
    # Fail-safe: Ensure brand identity is loaded
    if not tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY):
        log_message("Brand guidelines missing. Initializing default brand setup...", Severity.INFO)
        select_brand_preset(tool_context)

    log_message(f"Generating branded storyboard for {duration_minutes} min video in {language}...", Severity.INFO)

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    # Style & Word Count
    total_word_target = duration_minutes * 160
    num_slides = max(12, min(20, duration_minutes * 3))
    words_per_slide = total_word_target // num_slides
    
    selected_style_name = tool_context.state.get(CHOSEN_SLIDE_STYLE_STATE_KEY, "Flat Vector Explainer")
    style_desc = SLIDE_STYLES.get(selected_style_name, SLIDE_STYLES["Flat Vector Explainer"])

    branding_directive = f"3. BRANDING: Use {company_name}'s color palette for all designs."
    if brand_guidelines:
        branding_directive += f" Follow these strict brand guidelines: {brand_guidelines[:2000]}"

    prompt = (
        f"You are an expert Lead Educational Producer for {company_name}.\n"
        f"Goal: Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast' in {language}.\n\n"
        f"LANGUAGE REQUIREMENT:\n"
        f"- ALL NARRATION SCRIPTS MUST BE WRITTEN IN {language}.\n"
        f"- ALL VISUAL TEXT (titles, labels, infographic text) DESCRIBED IN IMAGE PROMPTS MUST BE WRITTEN IN {language}.\n"
        f"- Use formal, professional {language} appropriate for an executive educational video.\n\n"
        f"STRUCTURE REQUIREMENTS:\n"
        f"- SLIDE 1 MUST BE A TITLE SLIDE: It should feature a bold, cinematic title of the topic in {language} and a welcoming, high-level introduction narration in {language}.\n"
        f"- FINAL SLIDE MUST BE A SUMMARY/CONCLUSION SLIDE: It must summarize the key takeaways in a logical manner and bring the presentation to a smooth, definitive close, avoiding any abrupt endings. If the article has an existing conclusion or summary, use that.\n"
        f"- TOTAL SLIDES: {num_slides} slides total.\n"
        f"- LOGO INTEGRATION: Every slide MUST have the {company_name} logo in the bottom right corner. Include this in the image_prompt.\n\n"
        f"DURATION & WORD COUNT TARGETS:\n"
        f"- Target Duration: {duration_minutes} minutes.\n"
        f"- Total Word Count: ~{total_word_target} words (speaking rate: 160 WPM).\n"
        f"- Target per slide: ~{words_per_slide} words of detailed narration.\n\n"
        f"CORE DIRECTIVES:\n"
        f"1. VISUAL SELF-SUFFICIENCY: Every image prompt MUST describe a professional infographic with text, diagrams, and data. ALL TEXT LABELS MUST BE IN {language}.\n"
        f"2. NARRATION & GROUNDING: Each voiceover script MUST be a detailed educational segment (~{words_per_slide} words) written in {language}. The narrative MUST be strictly grounded in the provided Research Report and original articles. Do not include external facts, unverified claims, or information not present in the original research. Do NOT be concise.\n"
        f"3. BRANDING: {branding_directive}\n"
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

def update_slidecast_slide(tool_context: ToolContext, storyboard: dict, slide_index: int, instructions: str) -> dict:
    """Updates a specific slide in the storyboard based on user instructions, ensuring narrative continuity.
    Clears the image_url and audio_url for the updated slide so they will be regenerated.
    """
    log_message(f"Surgically updating slide {slide_index + 1}...", Severity.INFO)
    
    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    if slide_index < 0 or slide_index >= len(sb.slides):
         return {"status": "error", "details": f"Invalid slide index {slide_index}. Must be between 0 and {len(sb.slides)-1}."}

    target_slide = sb.slides[slide_index]
    
    # Gather context from surrounding slides for continuity
    context_str = ""
    if slide_index > 0:
        prev_slide = sb.slides[slide_index - 1]
        context_str += f"\n[PREVIOUS SLIDE - Slide {slide_index}]:\nTitle: {prev_slide.slide_title}\nScript: {prev_slide.script}\n"
    
    context_str += f"\n[CURRENT SLIDE TO UPDATE - Slide {slide_index + 1}]:\nTitle: {target_slide.slide_title}\nImage Prompt: {target_slide.image_prompt}\nScript: {target_slide.script}\n"
    
    if slide_index < len(sb.slides) - 1:
        next_slide = sb.slides[slide_index + 1]
        context_str += f"\n[NEXT SLIDE - Slide {slide_index + 2}]:\nTitle: {next_slide.slide_title}\nScript: {next_slide.script}\n"

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")

    prompt = (
        f"You are an expert Educational Producer for {company_name}.\n"
        f"The user has requested an update to ONE specific slide (Slide {slide_index + 1}) in a larger Slidecast presentation.\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
        f"CONTEXT (For Continuity):\n{context_str}\n\n"
        f"TASK:\n"
        f"Rewrite ONLY Slide {slide_index + 1}. Ensure the new script flows seamlessly from the previous slide and leads naturally into the next slide. Update the image prompt if the user's instructions affect the visuals.\n\n"
        f"Output ONLY valid JSON matching this schema for the single updated slide:\n"
        f"{{\n"
        f"  \"slide_title\": \"[Concise Slide Title]\",\n"
        f"  \"image_prompt\": \"[Updated image prompt...]\",\n"
        f"  \"script\": \"[Updated detailed educational narration flowing from previous to next...]\",\n"
        f"  \"text_overlay\": \"\" \n"
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
        updated_slide_data = json.loads(response.text)
        
        # Apply updates
        sb.slides[slide_index].slide_title = updated_slide_data.get("slide_title", target_slide.slide_title)
        sb.slides[slide_index].image_prompt = updated_slide_data.get("image_prompt", target_slide.image_prompt)
        sb.slides[slide_index].script = updated_slide_data.get("script", target_slide.script)
        sb.slides[slide_index].text_overlay = updated_slide_data.get("text_overlay", target_slide.text_overlay)
        
        # CRITICAL: Clear URLs so preview/finalize tools know to regenerate these assets
        sb.slides[slide_index].image_url = None
        sb.slides[slide_index].audio_url = None
        sb.slides[slide_index].video_url = None
        
        return {
            "status": "success",
            "message": f"Slide {slide_index + 1} updated successfully for continuity. Assets will be regenerated upon next preview.",
            "storyboard": sb.model_dump()
        }
    except Exception as e:
        log_message(f"Slide update failed: {e}", Severity.ERROR)
        return {"status": "error", "details": str(e)}

@stream_status("🎨 Generating branded slide assets and narration...")
async def preview_slidecast_assets(tool_context: ToolContext, storyboard: dict) -> dict:
    """Generates actual images for review and creates an approval PDF.
    Supports partial regeneration by skipping images that already have a valid image_url.
    """
    current_output_folder = set_output_folder(tool_context)
    log_message("Generating asset previews...", Severity.INFO)

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    # Process slides in parallel
    async def process_slide(slide: SlidecastSlide, idx: int):
        log_message(f"Rendering preview for slide {idx+1}...", Severity.INFO)
        try:
            # Skip image generation if we already have a valid URL for this slide
            if slide.image_url:
                log_message(f"Slide {idx+1} already has an image_url. Skipping image generation.", Severity.INFO)
                img_res = await utils_agents.load_resource(slide.image_url, tool_context)
                if not img_res:
                    raise ValueError(f"Failed to load existing image for slide {idx+1}")
                return slide, img_res.media_bytes

            # 1. Load brand assets
            logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
            ref_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")

            logo_bytes = []
            if logo_uri:
                lres = await utils_agents.load_resource(logo_uri, tool_context)
                if lres:
                    logo_bytes = [lres.media_bytes]

            # 2. Inject guidelines into prompt
            styled_prompt = f"{slide.image_prompt}\n\nREFERENCE BRAND RULES:\n{ref_guidelines[:1000]}"

            # 3. Generate Image with logo reference
            img_bytes = await _generate_gemini_image(styled_prompt, logo_bytes, label=f"slide_{idx+1}_image", aspect_ratio="16:9")

            if not img_bytes:
                log_message(f"Failed to generate image for slide {idx+1}", Severity.ERROR)
                raise ValueError(f"Failed to generate image for slide {idx+1}")

            # Save image as artifact
            img_media = GeneratedMedia(filename=f"slide_{idx+1}.png", mime_type="image/png", media_bytes=img_bytes)
            saved_img = await utils_agents.save_to_artifact_and_render_asset(
                asset=img_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
            )
            slide.image_url = utils_gcs.normalize_to_gs_bucket_uri(saved_img.gcs_uri)

            return slide, img_bytes
        except Exception as e:
            log_message(f"Error during image processing for slide {idx+1}: {repr(e)}", Severity.ERROR)
            raise

    try:
        slide_tasks = [process_slide(slide, i) for i, slide in enumerate(sb.slides)]
        results = await asyncio.gather(*slide_tasks, return_exceptions=True)
        
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                log_message(f"Task for slide {i+1} failed with exception: {repr(r)}", Severity.ERROR)
                raise r
        
        sb.slides = [r[0] for r in results]
        slide_images = [r[1] for r in results]

        log_message("Generating PDF Approval Page...", Severity.INFO)
        # 4. Generate PDF Approval Page
        try:
            pdf_bytes = _generate_approval_pdf(sb.title, sb.slides, slide_images)
        except Exception as e:
            log_message(f"Error during PDF generation: {repr(e)}", Severity.ERROR)
            raise

        try:
            pdf_media = GeneratedMedia(filename="approval_document.pdf", mime_type="application/pdf", media_bytes=pdf_bytes)
            saved_pdf = await utils_agents.save_to_artifact_and_render_asset(
                asset=pdf_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
            )
            pdf_url = get_public_url(saved_pdf.gcs_uri)
        except Exception as e:
            log_message(f"Error saving PDF artifact: {repr(e)}", Severity.ERROR)
            raise

        return {
            "status": "success",
            "message": "Assets and PDF approval document generated successfully. Please review the storyboard below or download the PDF.",
            "approval_pdf_url": pdf_url,
            "storyboard": sb.model_dump()
        }
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        log_message(f"Preview generation failed: {repr(e)}\nTraceback:\n{tb_str}", Severity.ERROR)
        return {"status": "error", "details": str(e)}

@stream_status("🎬 Finalizing the educational slidecast video...")
async def finalize_slidecast_video(tool_context: ToolContext, storyboard: dict, animate_slides: bool = False) -> dict:
    """Compiles the approved assets into a final educational video with background music and logo.
    Supports partial regeneration by skipping audio generation if a valid audio_url is present.
    If animate_slides is True, it will use Veo to animate each slide's keyframe.
    """
    current_output_folder = set_output_folder(tool_context)
    log_message("Finalizing slidecast video production...", Severity.INFO)

    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    # Style selection for voiceover
    selected_voice_name = tool_context.state.get(CHOSEN_VOICEOVER_STYLE_STATE_KEY, "Energetic & Engaging")
    voice_id = VOICEOVER_STYLES.get(selected_voice_name, VOICEOVER_STYLES["Energetic & Engaging"])

    from .tools_media import _generate_single_veo_clip

    # Download images and generate audio in parallel
    async def prepare_slide_data(slide: SlidecastSlide, idx: int):
        if not slide.image_url:
            raise ValueError(f"Slide {idx+1} is missing generated image assets. Run preview first.")
        
        # Load image from GCS
        img_res = await utils_agents.load_resource(slide.image_url, tool_context)
        if not img_res:
             raise ValueError(f"Failed to retrieve image for slide {idx+1}.")
        
        # Check if we already have the audio
        if slide.audio_url:
            log_message(f"Slide {idx+1} already has an audio_url. Skipping voiceover generation.", Severity.INFO)
            aud_res = await utils_agents.load_resource(slide.audio_url, tool_context)
            if not aud_res:
                raise ValueError(f"Failed to load existing audio for slide {idx+1}")
            vo_bytes = aud_res.media_bytes
        else:
            log_message(f"Generating final voiceover for slide {idx+1}...", Severity.INFO)
            vo_bytes = await _generate_voiceover_audio(slide.script, voice_name=voice_id)
            if not vo_bytes:
                 raise ValueError(f"Failed to generate voiceover for slide {idx+1}.")
            
            # Save audio as artifact
            aud_media = GeneratedMedia(filename=f"audio_final_{idx+1}.wav", mime_type="audio/wav", media_bytes=vo_bytes)
            saved_aud = await utils_agents.save_to_artifact_and_render_asset(
                asset=aud_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
            )
            slide.audio_url = utils_gcs.normalize_to_gs_bucket_uri(saved_aud.gcs_uri)

        # Animate the slide if requested
        video_bytes = None
        
        # 1. Check for cached video clip
        if slide.video_url:
            log_message(f"Slide {idx+1} already has a video_url. Skipping Veo generation.", Severity.INFO)
            vid_res = await utils_agents.load_resource(slide.video_url, tool_context)
            if vid_res:
                video_bytes = vid_res.media_bytes

        # 2. Generate animation if missing
        if not video_bytes and animate_slides:
            log_message(f"Animating slide {idx+1} with Veo...", Severity.INFO)
            # STRICTly constrain Veo to prevent the slide layout/text from panning off screen.
            # Focuses on diverse animations, character actions driven by script, and strict text preservation.
            motion_prompt = (
                f"A STATIC, LOCKED-OFF CAMERA SHOT. The camera MUST NOT pan, tilt, zoom, or move in any way. "
                f"The core layout, text, and composition MUST remain completely still and perfectly legible. "
                f"Focus entirely on animating the EDUCATIONAL CONTENT on the screen using subtle, localized motion: "
                f"1. Charts & Graphs: Animate data lines slowly growing, bars subtly filling, or data points softly glowing. "
                f"2. Diagrams & Workflows: Make connection arrows pulse with light, flowing from one step to the next to show a process. "
                f"3. Text & Highlights: Add a subtle sweeping sheen or soft illumination behind key bullet points or focus areas to draw the eye. "
                f"4. Icons & Spot illustrations: Give educational icons gentle, localized cinemagraph-style motion (e.g., a globe slowly spinning, a gear slowly turning). "
                f"5. TEXT PRESERVATION IS ABSOLUTE: DO NOT add, alter, morph, or hallucinate any text. All text MUST remain completely frozen and perfectly readable. "
                f"Keep all motion subtle, professional, and strictly constrained to the data/content elements without altering the slide layout." 
            )
            video_bytes = await _generate_single_veo_clip(
                prompt=motion_prompt, 
                start_frame_gcs_uri=slide.image_url, 
                clip_duration=8, 
                end_frame_gcs_uri=slide.image_url, 
                label=f"slide_anim_{idx+1}"
            )
            
            if video_bytes:
                # Save new video clip as artifact for future reuse
                vid_media = GeneratedMedia(filename=f"slide_anim_{idx+1}.mp4", mime_type="video/mp4", media_bytes=video_bytes)
                saved_vid = await utils_agents.save_to_artifact_and_render_asset(
                    asset=vid_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
                )
                slide.video_url = utils_gcs.normalize_to_gs_bucket_uri(saved_vid.gcs_uri)
            else:
                log_message(f"Failed to animate slide {idx+1}. Falling back to static image.", Severity.WARNING)

        return {
            "image_bytes": img_res.media_bytes,
            "video_bytes": video_bytes,
            "audio_bytes": vo_bytes,
            "text_overlay": "" 
        }

    try:
        slide_tasks = [prepare_slide_data(slide, i) for i, slide in enumerate(sb.slides)]
        slides_data = await asyncio.gather(*slide_tasks)
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        log_message(f"Finalization failed during asset prep: {repr(e)}\nTraceback:\n{tb_str}", Severity.ERROR)
        return {"status": "error", "details": str(e)}

    # Music & Logo
    music_prompt = sb.music_prompt or "Cinematic instrumental background music"
    music_bytes = await _generate_lyria_music(music_prompt, sb.title)

    logo_bytes = None
    logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)
    
    # Fallback to the provided logo URL or leave empty
    if not logo_uri:
        logo_uri = ""


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

    # CRITICAL: We must save the final video as an artifact (binary stream) because the 
    # artifact bucket is private and Signed URLs are failing in production.
    saved_video = await utils_agents.save_to_artifact_and_render_asset(
        asset=video_media, context=tool_context, save_in_gcs=True, save_in_artifacts=True, gcs_folder=current_output_folder
    )
    url = get_public_url(saved_video.gcs_uri)
    return {
        "status": "success", 
        "video_url": url, 
        "storyboard": sb.model_dump(),
        "details": "Slidecast masterclass finalized and ready for viewing."
    }

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
    """Generates a NanomationPlan (JSON) for a specific slide topic using dynamic segments.
    """
    log_message(f"Planning nanomation for: {slide_topic}...", Severity.INFO)
    
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    
    prompt = (
        f"You are a Senior Motion Designer for {company_name}.\n"
        f"Goal: Plan a multi-segment video animation (Nanomation) for the topic: '{slide_topic}'.\n\n"
        f"CONCEPT:\n"
        f"- You must determine the logical number of segments based on the slide's content and voiceover length (typically 2 to 4 segments).\n"
        f"- For each segment (phase), you will provide a starting 'image_prompt', a 'motion_prompt', and a 'duration_seconds'.\n"
        f"- The video will be generated by smoothly interpolating between the image generated for segment N and the image generated for segment N+1.\n"
        f"- Target high consistency: The background and core subjects must remain stable while specific actions progress.\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f"  \"target\": \"[High-level description of the entire animated sequence]\",\n"
        f"  \"progression_type\": \"linear\",\n"
        f"  \"phases\": [\n"
        f"    {{\"description\": \"[Description of segment 1]\", \"image_prompt\": \"[Detailed prompt for Imagen 3]\", \"motion_prompt\": \"[Cinematic motion directive]\", \"duration_seconds\": 4}},\n"
        f"    {{\"description\": \"[Description of segment 2]\", \"image_prompt\": \"[End of seg 1/Start of seg 2]\", \"motion_prompt\": \"[Cinematic motion directive]\", \"duration_seconds\": 4}},\n"
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
    """Executes a NanomationPlan by generating static keyframes and interpolating them using Veo.
    """
    current_output_folder = set_output_folder(tool_context)
    log_message("Executing nanomation sequence...", Severity.INFO)

    try:
        plan = NanomationPlan.model_validate(animation_plan)
    except Exception as e:
        return {"status": "error", "details": f"Invalid plan: {e}"}

    if not plan.phases:
        return {"status": "error", "details": "No phases found in animation plan."}

    # 1. Generate static images (keyframes)
    images_bytes = []
    image_uris = []
    
    for i, phase in enumerate(plan.phases):
        log_message(f"Generating keyframe {i+1}/{len(plan.phases)}: {phase.description}", Severity.INFO)
        
        refs = [images_bytes[-1]] if images_bytes else []
        img_bytes = await _generate_gemini_image(phase.image_prompt, refs, label=f"keyframe_f{i+1}", aspect_ratio="16:9")
        
        if not img_bytes:
            log_message(f"Failed to generate keyframe {i+1}", Severity.ERROR)
            return {"status": "error", "details": f"Failed to generate keyframe {i+1}."}
            
        images_bytes.append(img_bytes)
        
        media = GeneratedMedia(filename=f"keyframe_{int(time.time())}_{i+1}.png", mime_type="image/png", media_bytes=img_bytes)
        saved = await utils_agents.save_to_artifact_and_render_asset(
            asset=media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
        )
        phase.image_url = utils_gcs.normalize_to_gs_bucket_uri(saved.gcs_uri)
        image_uris.append(phase.image_url)

    # 2. Generate Veo clips using interpolation
    veo_tasks = []
    from .tools_media import _generate_single_veo_clip
    for i, phase in enumerate(plan.phases):
        start_uri = image_uris[i]
        end_uri = image_uris[i+1] if (i + 1) < len(image_uris) else None
        
        duration = phase.duration_seconds or 4
        motion = phase.motion_prompt or "Cinematic smooth motion"
        
        veo_tasks.append(_generate_single_veo_clip(motion, start_uri, clip_duration=duration, end_frame_gcs_uri=end_uri, label=f"nanomation_seg_{i+1}"))
    
    log_message(f"Triggering {len(veo_tasks)} Veo generations in parallel...", Severity.INFO)
    veo_results = await asyncio.gather(*veo_tasks)
    
    clips = [res for res in veo_results if res]
    if not clips:
        return {"status": "error", "details": "Veo generation failed for all segments."}
        
    # 3. Stitch the clips together
    log_message(f"Stitching {len(clips)} video segments...", Severity.INFO)
    from ..shared_infra.utils_media import stitch_videos
    stitched_video = stitch_videos(clips) if len(clips) > 1 else clips[0]
    
    if not stitched_video:
        return {"status": "error", "details": "Failed to stitch video clips."}
        
    final_media = GeneratedMedia(filename=f"nanomation_stitched_{int(time.time())}.mp4", mime_type="video/mp4", media_bytes=stitched_video)
    saved_final = await utils_agents.save_to_artifact_and_render_asset(
        asset=final_media, context=tool_context, save_in_gcs=True, save_in_artifacts=True, gcs_folder=current_output_folder
    )
    
    return {
        "status": "success",
        "message": f"Nanomation video '{plan.topic}' generated successfully.",
        "plan": plan.model_dump(),
        "video_url": get_public_url(saved_final.gcs_uri)
    }

