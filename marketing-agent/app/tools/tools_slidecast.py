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
    LLM_GEMINI_MODEL_MARKETING_ANALYST,
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

@stream_status("📋 Designing the educational storyboard...")
def generate_slidecast_storyboard(tool_context: ToolContext, urls: List[str] = None, trend_context: str = "", duration_seconds: int = 300, language: str = "English", aspect_ratio: str = "16:9") -> dict:
    """Generates a SlidecastStoryboard (JSON) directly grounded in the provided URLs.
    Dynamically scales slide count and pacing for short-form (Shorts) or long-form videos.
    """
    # Fail-safe: Ensure brand identity is loaded
    if not tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY):
        log_message("Brand guidelines missing. Initializing default brand setup...", Severity.INFO)
        select_brand_preset(tool_context)

    log_message(f"Generating branded storyboard for {duration_seconds} sec video in {language} (Aspect Ratio: {aspect_ratio})...", Severity.INFO)

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    brand_wall = _get_brand_wall_directive(company_name)

    # Style & Word Count for Shorts vs Long-form
    duration_minutes = duration_seconds / 60.0
    total_word_target = max(60, int(duration_minutes * 160)) # minimum 60 words for shorts
    
    if duration_seconds <= 60:
        # Shorts mode
        num_slides = max(3, int(duration_seconds / 7.5)) # 1 slide every ~7.5 seconds for shorts
    else:
        # Long-form mode
        num_slides = max(12, min(25, int(duration_minutes * 5))) # 5 slides per minute as a baseline, capped at 25 slides for very long videos
        
    words_per_slide = max(10, total_word_target // num_slides)
    
    selected_style_name = tool_context.state.get(CHOSEN_SLIDE_STYLE_STATE_KEY)
    if not selected_style_name:
        return {
            "status": "error", 
            "message": "Visual style not set. You MUST present the available styles to the user and call `select_slidecast_style` to lock in their choice BEFORE generating the storyboard."
        }
        
    style_desc = SLIDE_STYLES.get(selected_style_name)

    branding_directive = f"3. BRANDING: Use {company_name}'s color palette for all designs."
    if brand_guidelines:
        branding_directive += f" Follow these strict brand guidelines: {brand_guidelines[:2000]}"

    url_list_str = "\n".join([f"- {url}" for url in urls]) if urls else "No specific URLs provided."

    if aspect_ratio == "9:16":
        # VIRAL SHORTS PROMPT
        prompt = (
            f"You are an expert Social Media Producer for {company_name}, specializing in high-retention viral Shorts (TikTok/Reels format).\n"
            f"Goal: Create a fast-paced, high-energy storyboard for a {duration_seconds}-second vertical video (9:16) in {language}.\n\n"
            f"SOURCE MATERIAL:\n"
            f"Extract the most compelling, counter-intuitive, or highest-value hooks from these URLs:\n"
            f"{url_list_str}\n\n"
            f"TREND CONTEXT (Use to shape the hook):\n"
            f"{trend_context}\n\n"
            f"STRUCTURE REQUIREMENTS (CRITICAL FOR SHORTS):\n"
            f"- SLIDE 1 MUST BE THE HOOK: NO title slides. NO \"Welcome to...\" intros. Start immediately with a high-stakes question, shocking claim, or curiosity gap.\n"
            f"- RETENTION: Every 3-5 seconds (each slide) must introduce a pattern interrupt. Use punchy, fast-paced dialogue.\n"
            f"- THE CTA: The final slide must have an abrupt, direct call to action. Do NOT use formal corporate summaries.\n"
            f"- TOTAL SCENES: {num_slides} distinct visual scenes/cuts.\n"
            f"- TARGET WORD COUNT: ~{total_word_target} words total (extremely fast speaking rate).\n\n"
            f"CORE DIRECTIVES:\n"
            f"1. KINETIC VISUALS: Every image prompt must describe a highly dynamic vertical scene. Think 'creator-style' angles, bold close-ups, or striking visual metaphors. Avoid dense, tiny corporate infographics that won't read on a phone.\n"
            f"2. KINETIC TEXT: Use the 'text_overlay' field to specify 1-3 massive, punchy words that should pop on screen for that slide. ALL TEXT MUST BE IN {language}.\n"
            f"3. NARRATION: Write conversational, punchy scripts in {language}. Ground them in the URLs, but translate them into creator-speak.\n"
            f"4. BRANDING: {branding_directive} Note: Keep logos subtle and out of the middle 60% safe zone.\n"
            f"5. VISUAL STYLE: {style_desc}\n\n"
            f"Output ONLY valid JSON matching this schema:\n"
            f"{{\n"
            f"  \"title\": \"[Viral Hook Title]\",\n"
            f"  \"summary_arc\": [\"Hook\", \"Value Bomb 1\", \"Value Bomb 2\", \"Direct CTA\"],\n"
            f"  \"slides\": [\n"
            f"    {{\n"
            f"      \"slide_title\": \"Hook\",\n"
            f"      \"image_prompt\": \"[Dynamic, close-up vertical scene... No text in prompt.]\",\n"
            f"      \"script\": \"[Fast, shocking opening sentence...]\",\n"
            f"      \"text_overlay\": \"[1-3 massive bold words, e.g., 'STOP DOING THIS']\" \n"
            f"    }}\n"
            f"  ],\n"
            f"  \"music_prompt\": \"High-energy, fast-tempo, modern viral social media beat\"\n"
            f"}}"
        )
    else:
        # LONG-FORM SLIDECAST PROMPT (16:9)
        prompt = (
            f"You are an expert Lead Educational Producer for {company_name}.\n"
            f"Goal: Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast' in {language} (16:9 format).\n\n"
            f"SOURCE MATERIAL:\n"
            f"Research the following URLs to gather the factual content for this presentation:\n"
            f"{url_list_str}\n\n"
            f"TREND CONTEXT:\n"
            f"Use the following market trends to subtly inform the narrative tone and hooks, but DO NOT invent facts:\n"
            f"{trend_context}\n\n"
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
            f"2. NARRATION & GROUNDING: Each voiceover script MUST be a detailed educational segment (~{words_per_slide} words) written in {language}. The narrative MUST be strictly grounded in the content of the provided URLs. Do not include external facts, unverified claims, or information not present in the original research. Do NOT be concise.\n"
            f"3. BRANDING: {branding_directive}\n"
            f"4. VISUAL STYLE: {style_desc} NO style variations across slides. Avoid overly metallic or glossy surfaces unless the prompt specifically requires a technological detail.\n\n"
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
                tools=[types.Tool(google_search=types.GoogleSearch())] if urls else None,
            ),
        )

        # Verify JSON
        storyboard_data = json.loads(response.text)
        storyboard_data["aspect_ratio"] = aspect_ratio
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

def update_storyboard_visual_style(tool_context: ToolContext, storyboard: dict, new_style_name: str) -> dict:
    """Updates the visual style of an entire storyboard by rewriting ONLY the image prompts to match a new style.
    Leaves all narrative scripts perfectly untouched.
    """
    log_message(f"Updating overall storyboard visual style to: {new_style_name}...", Severity.INFO)
    
    try:
        sb = SlidecastStoryboard.model_validate(storyboard)
    except Exception as e:
        return {"status": "error", "details": f"Invalid storyboard format: {e}"}

    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    style_desc = SLIDE_STYLES.get(new_style_name, new_style_name)

    # 1. Update the stored style preference so future renders use it
    tool_context.state[CHOSEN_SLIDE_STYLE_STATE_KEY] = new_style_name

    # 2. Iterate through slides and use LLM to rewrite the image_prompt
    for i, slide in enumerate(sb.slides):
        log_message(f"Rewriting image prompt for slide {i+1} to match new style...", Severity.INFO)
        prompt = (
            f"You are a Senior Art Director for {company_name}.\n"
            f"We are transitioning a slidecast to a new visual style: {new_style_name}.\n"
            f"Style Description: {style_desc}\n\n"
            f"CURRENT IMAGE PROMPT:\n{slide.image_prompt}\n\n"
            f"CURRENT NARRATION SCRIPT (For context only):\n{slide.script}\n\n"
            f"TASK:\n"
            f"Rewrite the CURRENT IMAGE PROMPT so that it perfectly aligns with the new visual style. "
            f"Ensure the new image prompt still describes a scene that makes sense with the narration script, and still includes the {company_name} logo in the bottom right corner.\n\n"
            f"Output ONLY the new raw image prompt string, nothing else. No quotes, no JSON."
        )

        try:
            response = client.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                ),
            )
            
            if response.text:
                slide.image_prompt = response.text.strip()
                # Clear ONLY the visual assets so they are regenerated, keeping audio intact
                slide.image_url = None
                slide.video_url = None
        except Exception as e:
            log_message(f"Failed to update image prompt for slide {i+1}: {e}", Severity.WARNING)

    return {
        "status": "success",
        "message": f"Visual style successfully updated to '{new_style_name}'. Image prompts rewritten. Narrative scripts were kept identical.",
        "storyboard": sb.model_dump()
    }

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
            ar = sb.aspect_ratio
            img_bytes = await _generate_gemini_image(styled_prompt, logo_bytes, label=f"slide_{idx+1}_image", aspect_ratio=ar)

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
            
            # Use Gemini to pick the best animation from the approved menu
            if sb.aspect_ratio == "9:16":
                # SHORTS: Dynamic, high-energy, camera movement allowed
                llm_prompt = (
                    "You are an expert video prompt engineer for viral social media content (Shorts/Reels).\n"
                    "Your task is to generate a specific, highly controlled visual description for a video generation AI based on a provided script or slide.\n\n"
                    "CONSTRAINTS (DO NOT VIOLATE):\n"
                    "CAMERA: Focus on dynamic energy. Add slow cinematic push-ins (zooms), dramatic pans, or expressive character motion. Text preservation is important but secondary to visual impact.\n"
                    "SAFETY: All motion must be professional and educational. Do not generate chaotic, rapid, derogatory, or destructive motion (e.g., no crashes, no explosions). Frame all descriptions positively.\n\n"
                    "YOUR OUTPUT:\n"
                    "Based on the provided slide/script, you will ONLY output the two variables needed for the final video generation. Keep your descriptions highly visual and physical.\n"
                    "Output ONLY valid JSON matching this schema:\n"
                    "{\n"
                    "  \"scene_subject\": \"[Describe the specific static layout]\",\n"
                    "  \"approved_animation\": \"[Describe the dynamic motion, e.g., 'A slow cinematic push-in while the main character animatedly points to the data.']\"\n"
                    "}\n\n"
                    f"Slide Image Description: {slide.image_prompt}\n"
                    f"Slide Script: {slide.script}"
                )
            else:
                # LONG-FORM (16:9): Strict corporate governance, locked camera
                llm_prompt = (
                    "You are an expert video prompt engineer for corporate educational content. Your task is to generate a specific, highly controlled visual description for a video generation AI based on a provided script or slide.\n\n"
                    "CORPORATE GUIDELINES & CONSTRAINTS (DO NOT VIOLATE):\n"
                    "CAMERA: The camera MUST NEVER pan, tilt, zoom, or move.\n"
                    "TEXT: TEXT PRESERVATION IS ABSOLUTE. Do not add, animate, morph, or alter text or core slide layouts.\n"
                    "SAFETY: All motion must be professional and educational. Do not generate chaotic, rapid, derogatory, or destructive motion (e.g., no crashes, no explosions). Frame all descriptions positively (e.g., \"calm and controlled\").\n"
                    "MOTION STYLE: Focus entirely on subtle, localized \"cinemagraph\" motion tied to the narrative.\n\n"
                    "APPROVED ANIMATION LIBRARY:\n"
                    "You must select and adapt the animation style based on the subject matter:\n"
                    "If Charts & Graphs: Animate data lines slowly growing, bars subtly filling, or data points softly glowing from left-to-right or bottom-to-top.\n"
                    "If Diagrams & Workflows: Make connection arrows pulse with light, flowing from one step to the next to show a process.\n"
                    "If Text & Highlights: Add a subtle sweeping metallic sheen or soft illumination behind key bullet points to draw the eye.\n"
                    "If Icons & Spot Illustrations: Give elements gentle, localized motion (e.g., a globe slowly spinning, a gear slowly rotating on its Y-axis, or a gentle hovering loop).\n"
                    "If Characters/People: Animate them with slow, fluid, purposeful actions that directly reflect the script while maintaining a professional demeanor.\n"
                    "If Vehicles: Keep the vehicle locked in its original position, animate the wheels rotating, and add a subtle, slow-moving horizontal background blur to imply forward motion.\n\n"
                    "YOUR OUTPUT:\n"
                    "Based on the provided slide/script, you will ONLY output the two variables needed for the final video generation. Keep your descriptions highly visual and physical.\n"
                    "Output ONLY valid JSON matching this schema:\n"
                    "{\n"
                    "  \"scene_subject\": \"[Describe the specific static layout, e.g., 'A clean, 3D isometric infographic showing a 3-step supply chain workflow on a navy blue background.']\",\n"
                    "  \"approved_animation\": \"[Describe the specific motion using the Approved Library, e.g., 'A soft pulse of luminescent light travels continuously along the connection arrows from the factory node to the store node.']\"\n"
                    "}\n\n"
                    f"Slide Image Description: {slide.image_prompt}\n"
                    f"Slide Script: {slide.script}"
                )
            
            try:
                def _call_llm():
                    return client.models.generate_content(
                        model=LLM_GEMINI_MODEL_MARKETING_ANALYST,
                        contents=llm_prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.7,
                            response_mime_type="application/json"
                        )
                    )
                resp = await asyncio.to_thread(_call_llm)
                llm_response = json.loads(resp.text)
                
                scene_subject = llm_response.get("scene_subject", slide.image_prompt)
                approved_animation = llm_response.get("approved_animation", "A subtle, slow-moving metallic light sweep passes behind the key elements.")
            except Exception as e:
                log_message(f"Failed to generate specific motion prompt for slide {idx+1}: {e}", Severity.WARNING)
                scene_subject = slide.image_prompt
                approved_animation = "A subtle, slow-moving metallic light sweep passes behind the key elements."
            
            if sb.aspect_ratio == "9:16":
                motion_prompt = (
                    f"Dynamic, high-energy cinematic camera movement. "
                    f"{scene_subject}. {approved_animation}. "
                    f"Smooth but bold motion suitable for viral social media. Rich, dramatic lighting and expressive action. No chaotic, rapid, or distracting movement."
                )
            else:
                motion_prompt = (
                    f"Static, locked-off camera shot, deep focus, cinemagraph style. Professional corporate educational presentation. "
                    f"{scene_subject}. {approved_animation}. "
                    f"The core layout, typography, and background composition remain completely frozen in place, preserving absolute text legibility without morphing. Motion is strictly localized, subtle, fluid, and purposeful. The environment is calm, pristine, and highly controlled. No chaotic, rapid, or distracting movement."
                )

            video_bytes = await _generate_single_veo_clip(
                prompt=motion_prompt, 
                start_frame_gcs_uri=slide.image_url, 
                clip_duration=8, 
                end_frame_gcs_uri=slide.image_url, 
                label=f"slide_anim_{idx+1}",
                aspect_ratio=sb.aspect_ratio
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
    video_bytes = compile_slidecast_video(slides_data, aspect_ratio=sb.aspect_ratio)
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

def select_slidecast_style(tool_context: ToolContext, slide_style: str, voiceover_style: str) -> dict:
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
        asset=final_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
    )
    
    return {
        "status": "success",
        "message": f"Nanomation video '{plan.topic}' generated successfully.",
        "plan": plan.model_dump(),
        "video_url": get_public_url(saved_final.gcs_uri)
    }

