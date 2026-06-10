import asyncio
import json
import logging
import tempfile
import os
import time
from typing import List, Optional
from fpdf import FPDF

from google.genai import types

from app.adk_common.utils.utils_logging import Severity, log_message
from app.state import STORYLINE_MODEL, SLIDE_STYLES, VOICEOVER_STYLES, LOGO_IMAGE_URI_STATE_KEY, LLM_GEMINI_MODEL_MARKETING_ANALYST
from app.mcp_server.generators.core import _retry_generate_content, _download_uri, _upload_bytes, client
from app.mcp_server.generators.image import _generate_gemini_image
from app.mcp_server.generators.audio import _generate_voiceover_audio
from app.mcp_server.generators.video import _generate_single_veo_clip
from app.mcp_server.schemas import SlidecastManifest, SlidecastSlide, BrandContext, NanomationPlan, NanomationPhase

logger = logging.getLogger(__name__)

# ============================================================
# Private Helpers (Lost Nuances Restoration)
# ============================================================

def _generate_approval_pdf(title: str, slides: List[SlidecastSlide], slide_images: List[tuple[bytes, bytes]]) -> bytes:
    """Generates a professional PDF for asset approval, displaying both start and end frames."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Add Title Page
    pdf.add_page()
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 40, "Slidecast Approval Document", ln=True, align="C")
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 20, title, ln=True, align="C")
    pdf.ln(20)
    
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(51, 51, 51)
    pdf.multi_cell(0, 10, "Please review the visual assets and narration tracks for each slide below. This document serves as the formal storyboard for your educational video.")
    pdf.ln(10)

    # Add Slides
    for i, (slide, (start_img, end_img)) in enumerate(zip(slides, slide_images)):
        if i % 2 == 0 and i > 0:
            pdf.add_page()
        
        pdf.set_font("helvetica", "B", 14)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, f"Slide {i+1}", ln=True)
        pdf.ln(5)
        
        # Helper to render an image
        def _render_image(img_bytes, label):
            temp_img_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                    temp_file.write(img_bytes)
                    temp_img_path = temp_file.name
                pdf.set_font("helvetica", "I", 10)
                pdf.cell(0, 5, label, ln=True)
                pdf.image(temp_img_path, x=15, w=80)
                pdf.ln(5)
            finally:
                if temp_img_path and os.path.exists(temp_img_path):
                    os.remove(temp_img_path)

        # Render Images
        if start_img:
            _render_image(start_img, "Start Frame:")
        if end_img:
            _render_image(end_img, "End Frame:")
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Talk Track:", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(68, 68, 68)
        # Sanitize text to remove non-ASCII characters (e.g., em-dash)
        safe_text = slide.voiceover_script.replace("—", "-").encode("latin-1", "ignore").decode("latin-1")
        pdf.multi_cell(0, 6, safe_text)
        pdf.ln(10)

    return pdf.output()

async def generate_slidecast_audio_assets(manifest: SlidecastManifest) -> SlidecastManifest:
    """
    Generates audio clips for a slidecast manifest AFTER visual approval.
    """
    log_message(f"Starting audio generation for: {manifest.title}", Severity.INFO)
    
    async def _gen_audio(slide: SlidecastSlide):
        if not slide.audio_url:
            log_message(f"Slide {slide.index+1}: generating new audio...", Severity.INFO)
            voice_id = VOICEOVER_STYLES.get(manifest.voiceover_style, "Puck")
            audio_bytes = await _generate_voiceover_audio(slide.voiceover_script, voice_name=voice_id)
            if audio_bytes:
                url = await _upload_bytes(audio_bytes, "mcp_slidecast", f"audio_{slide.index}.wav", "audio/wav")
                slide.audio_url = url
        else:
            log_message(f"Slide {slide.index+1}: audio already exists.", Severity.INFO)
        return slide

    updated_slides = await asyncio.gather(*[_gen_audio(s) for s in manifest.slides])
    manifest.slides = list(updated_slides)
    
    return manifest

async def generate_slidecast_manifest(
    brand: BrandContext,
    slide_style: str,
    animate_slides: bool,
    voiceover_style: str,
    urls: List[str] = None,
    trend_context: str = "",
    duration_seconds: int = 300,
    language: str = "English",
    aspect_ratio: str = "16:9",
    use_preapproved_style: bool = False
) -> SlidecastManifest:
    """
    Stateless generator for a slidecast presentation blueprint.
    Restores dynamic scaling and detailed persona prompts from legacy.
    """
    duration_minutes = duration_seconds / 60.0
    # Increase base word target by 10% for faster pacing
    total_word_target = max(60, int((duration_minutes * 160) * 1.1))

    if duration_seconds <= 60:
        # Shorts mode: high frequency of visual changes
        num_slides = max(3, int(duration_seconds / 7.5))
    else:
        # Long-form mode: educational pacing
        num_slides = max(12, min(25, int(duration_minutes * 5)))

    # Distribute the increased word count across slides
    words_per_slide = max(10, total_word_target // num_slides)

    if use_preapproved_style:
        style_desc = (
            "CRITICAL: The visual style is strictly enforced by a master reference image applied later in the pipeline. "
            "THEREFORE, DO NOT INCLUDE ANY ARTISTIC DIRECTIVES IN YOUR PROMPTS. "
            "Your `image_prompt` and `end_image_prompt` MUST ONLY describe the raw subject matter, character actions, objects, and spatial composition. "
            "PROHIBITED WORDS: Do not use terms like 'style', 'lighting', 'aesthetic', 'vector', 'realistic', '3D', 'render', or 'colors'. "
            "Focus entirely on what is happening in the scene."
        )
        if brand.style_reference_image_uri:
            style_desc += (
                "\n\nCRITICAL IDENTITY LINK: An image containing the approved character(s) is attached. "
                "You MUST analyze this image to understand the visual identity of the characters. "
                "If your storyline features specific named characters, you MUST explicitly use their names in the `image_prompt` and `end_image_prompt` (e.g., 'Aisha is reviewing blueprints', not 'A woman is reviewing blueprints'). "
                "This ensures the downstream image generator applies the exact face and identity from the reference image."
            )
    else:
        style_desc = SLIDE_STYLES.get(slide_style, slide_style)

    url_list_str = "\n".join([f"- {url}" for url in urls]) if urls else "No specific URLs provided."

    prompt = (
        f"You are an EXPERT INSTRUCTIONAL DESIGNER and CREATIVE DIRECTOR for {brand.company_name}.\n"
        f"GOAL: Design a compelling, branded {duration_seconds}s video storyboard in {language}.\n\n"
        f"SOURCE MATERIAL:\n{url_list_str}\n\n"
        f"TREND CONTEXT:\n{trend_context}\n\n"
        f"STRUCTURE REQUIREMENTS:\n"
        f"- TOTAL SLIDES: {num_slides}\n"
        f"- TARGET WORD COUNT: ~{total_word_target} total.\n"
        f"- TARGET PER SLIDE: ~{words_per_slide} words.\n"
        f"- Slide 1 MUST be a bold Title Slide.\n\n"
        f"VISUAL STYLE: {slide_style}\n"
        f"STYLE DIRECTIVE: {style_desc}\n\n"
        f"BRAND MANDATE:\n{brand.reference_guidelines[:1000]}\n"
        f"BRAND SAFETY MANDATE: The company name ({brand.company_name}) or brand must NEVER be associated with or appear alongside negative concepts, struggles, or problems. Only associate the brand with solutions, positive outcomes, and empowerment.\n"
    )

    if animate_slides:
        prompt += (
            f"\nCRITICAL ANIMATION DIRECTIVE: The user requested an ANIMATED video. "
            f"You MUST provide a distinct 'end_image_prompt' for EVERY slide. "
            f"The 'end_image_prompt' must describe the scene 5 minutes later, showing distinct, meaningful motion (e.g., character moved to a new pose, camera shifted perspective, objects changed state) to ensure the animation model has clear start and end states to interpolate between.\n\n"
        )
    else:
        prompt += (
            f"\nCRITICAL STATIC DIRECTIVE: The user requested a STATIC video. "
            f"You MUST set 'end_image_prompt' to an empty string (\"\") for all slides.\n\n"
        )

    prompt += (
        f"Output ONLY valid JSON matching the schema with 'title', 'slides' (index, title, content, image_prompt, end_image_prompt, voiceover_script).\n"
        f"CRITICAL: The 'content' field in each slide MUST be a JSON array of strings (e.g., [\"Bullet 1\", \"Bullet 2\"]), NOT a single string."
    )

    contents = prompt
    if use_preapproved_style and brand.style_reference_image_uri:
        from .core import _download_uri
        ref_bytes = await _download_uri(brand.style_reference_image_uri)
        if ref_bytes:
            contents = [
                types.Part.from_bytes(data=ref_bytes, mime_type="image/png"),
                prompt
            ]

    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.7, 
            response_mime_type="application/json",
            response_schema=SlidecastManifest,
            tools=[types.Tool(google_search=types.GoogleSearch())] if urls else None
        ),
        label="slidecast-manifest"
    )
    
    return SlidecastManifest.model_validate_json(response.text)

async def generate_approval_pdf_backend(manifest: SlidecastManifest) -> str:
    """Generates and uploads an approval PDF storyboard based on current manifest state."""
    log_message(f"Generating approval PDF for: {manifest.title}", Severity.INFO)
    
    # Placeholder images if not generated yet
    slide_images = []
    for slide in manifest.slides:
        slide_images.append((
            await _download_uri(slide.start_image_url) if slide.start_image_url else None,
            await _download_uri(slide.end_image_url) if slide.end_image_url else None
        ))
        
    pdf_content = _generate_approval_pdf(manifest.title, manifest.slides, slide_images)
    pdf_url = await _upload_bytes(pdf_content, "mcp_slidecast", f"approval_document_{int(time.time())}.pdf", "application/pdf")
    return pdf_url

async def produce_assets(manifest: SlidecastManifest, brand: BrandContext) -> SlidecastManifest:
    """Generates images and audio assets for approved manifest."""
    log_message(f"Starting asset production for: {manifest.title}", Severity.INFO)
    
    # 1. Initialize reference images
    # We purposefully DO NOT pass the logo_bytes here. The logo is overlaid 
    # strictly downstream via FFmpeg in the compilation step. Passing it here 
    # as a reference image confuses the diffusion model, causing it to hallucinate 
    # the logo onto random surfaces (walls, shirts, etc.) inside the generated scene.
    # logo_bytes = await _download_uri(brand.logo_uri) if brand.logo_uri else None
    # ref_images = [logo_bytes] if logo_bytes else []
    ref_images = []
    
    # 2. Process slides in parallel
    async def _gen_slide_assets(slide: SlidecastSlide):
        # IMAGE (START)
        if not slide.start_image_url:
            log_message(f"Slide {slide.index+1}: generating start image...", Severity.INFO)
            styled_prompt = f"{slide.image_prompt}\n\nREFERENCE BRAND RULES:\n{brand.reference_guidelines[:500]}"
            start_img_bytes = await _generate_gemini_image(
                styled_prompt, 
                ref_images, 
                label=f"slide_{slide.index}_start", 
                aspect_ratio=manifest.aspect_ratio
            )
            if start_img_bytes:
                slide.start_image_url = await _upload_bytes(start_img_bytes, "mcp_slidecast", f"slide_{slide.index}_start.png", "image/png")

        # IMAGE (END)
        if slide.end_image_prompt and not slide.end_image_url:
            log_message(f"Slide {slide.index+1}: generating end image...", Severity.INFO)
            start_img_bytes = await _download_uri(slide.start_image_url) if slide.start_image_url else None
            end_ref_images = ref_images + ([start_img_bytes] if start_img_bytes else [])
            styled_prompt = f"{slide.end_image_prompt}\n\nREFERENCE BRAND RULES:\n{brand.reference_guidelines[:500]}"
            end_img_bytes = await _generate_gemini_image(
                styled_prompt, 
                end_ref_images, 
                label=f"slide_{slide.index}_end", 
                aspect_ratio=manifest.aspect_ratio
            )
            if end_img_bytes:
                slide.end_image_url = await _upload_bytes(end_img_bytes, "mcp_slidecast", f"slide_{slide.index}_end.png", "image/png")
        
        return slide

    updated_slides = await asyncio.gather(*[_gen_slide_assets(s) for s in manifest.slides])
    manifest.slides = list(updated_slides)
    
    # 3. Audio
    manifest = await generate_slidecast_audio_assets(manifest)
    
    return manifest

async def plan_slide_animation(slide: SlidecastSlide, brand: BrandContext, aspect_ratio: str = "16:9") -> NanomationPlan:
    """
    Generates a multi-phase animation plan for a slide topic.
    Restores the 'Approved Animation Library' and 16:9 vs 9:16 specific prompts.
    """
    library = (
        "APPROVED ANIMATION LIBRARY:\n"
        "- Characters: Fluid, purposeful actions reflecting the script. Natural human motion.\n"
        "- Charts: Lines growing, bars filling, data points glowing left-to-right.\n"
        "- Diagrams: Connection arrows pulsing with light flow.\n"
        "- Text: Subtle sweeping metallic sheen or soft illumination behind points.\n"
        "- Vehicles: Rotating wheels + subtle background blur to imply motion.\n"
    )

    if aspect_ratio == "9:16":
        # SHORTS: Dynamic, zooms, pans
        persona = "expert video prompt engineer for viral social media content (Shorts/Reels)"
        constraints = "CAMERA: Dynamic energy. Slow cinematic push-ins, dramatic pans, expressive motion."
    else:
        # LONG-FORM: Locked camera, text preservation
        persona = "expert video prompt engineer for corporate educational content"
        constraints = "CAMERA: MUST NEVER move. TEXT: PRESERVATION IS ABSOLUTE. Focus on cinemagraph motion."

    prompt = (
        f"You are an {persona}.\n"
        f"TASK: Generate a multi-segment visual animation plan for this slide.\n\n"
        f"CONSTRAINTS:\n{constraints}\n"
        f"{library}\n\n"
        f"SLIDE TITLE: {slide.title}\n"
        f"IMAGE DESCRIPTION: {slide.image_prompt}\n"
        f"SCRIPT: {slide.voiceover_script}\n\n"
        f"Output ONLY valid JSON matching NanomationPlan schema with 'topic', 'target', and 'phases' (description, image_prompt, motion_prompt, duration_seconds)."
    )

    response = await _retry_generate_content(
        model=LLM_GEMINI_MODEL_MARKETING_ANALYST,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7, 
            response_mime_type="application/json",
            response_schema=NanomationPlan
        ),
        label="nanomation-plan"
    )
    
    return NanomationPlan.model_validate_json(response.text)

async def rewrite_image_prompts(manifest: SlidecastManifest, override_instructions: str, brand: BrandContext) -> SlidecastManifest:
    """Uses LLM to rewrite image prompts for the entire manifest based on instructions."""
    log_message(f"Rewriting image prompts: {override_instructions}", Severity.INFO)
    
    prompt = (
        f"You are the Creative Director for {brand.company_name}.\n"
        f"TASK: Rewrite the 'image_prompt' and 'end_image_prompt' fields for every slide in the provided manifest based on these new instructions:\n"
        f"INSTRUCTIONS: {override_instructions}\n\n"
        f"BRAND RULES: {brand.reference_guidelines[:500]}\n"
        f"CURRENT MANIFEST JSON:\n{manifest.model_dump_json()}\n\n"
        f"Output ONLY the complete updated JSON matching the SlidecastManifest schema."
    )
    
    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7, 
            response_mime_type="application/json",
            response_schema=SlidecastManifest
        ),
        label="rewrite-image-prompts"
    )
    
    new_manifest = SlidecastManifest.model_validate_json(response.text)
    # Clear existing image URLs to force regeneration
    for slide in new_manifest.slides:
        slide.start_image_url = None
        slide.end_image_url = None
    return new_manifest

async def rewrite_audio_prompts(manifest: SlidecastManifest, override_instructions: str, brand: BrandContext) -> SlidecastManifest:
    """Uses LLM to rewrite voiceover scripts for the entire manifest based on instructions."""
    log_message(f"Rewriting audio prompts: {override_instructions}", Severity.INFO)
    
    prompt = (
        f"You are the Head Copywriter for {brand.company_name}.\n"
        f"TASK: Rewrite the 'voiceover_script' field for every slide in the provided manifest based on these new instructions:\n"
        f"INSTRUCTIONS: {override_instructions}\n\n"
        f"BRAND RULES: {brand.reference_guidelines[:500]}\n"
        f"CURRENT MANIFEST JSON:\n{manifest.model_dump_json()}\n\n"
        f"Output ONLY the complete updated JSON matching the SlidecastManifest schema."
    )
    
    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7, 
            response_mime_type="application/json",
            response_schema=SlidecastManifest
        ),
        label="rewrite-audio-prompts"
    )
    
    new_manifest = SlidecastManifest.model_validate_json(response.text)
    # Clear existing audio URLs to force regeneration
    for slide in new_manifest.slides:
        slide.audio_url = None
    return new_manifest

async def update_slide_blueprint(
    manifest: SlidecastManifest,
    slide_index: int,
    instructions: str,
    brand: BrandContext
) -> SlidecastManifest:
    """
    Updates a single slide with surrounding context for continuity.
    Restores the 'Continuity Gathering' logic from legacy.
    """
    if slide_index < 0 or slide_index >= len(manifest.slides):
        raise ValueError(f"Invalid slide index {slide_index}")
        
    target_slide = manifest.slides[slide_index]
    
    # Gather context from surrounding slides for continuity
    context_str = ""
    if slide_index > 0:
        prev = manifest.slides[slide_index - 1]
        context_str += f"\n[PREV SLIDE]: {prev.title} | {prev.voiceover_script[:200]}"
    
    context_str += f"\n[CURRENT SLIDE]: {target_slide.title} | {target_slide.voiceover_script}"
    
    if slide_index < len(manifest.slides) - 1:
        nxt = manifest.slides[slide_index + 1]
        context_str += f"\n[NEXT SLIDE]: {nxt.title} | {nxt.voiceover_script[:200]}"

    prompt = (
        f"Update Slide {slide_index + 1} based on instructions: '{instructions}'\n\n"
        f"CONTEXT FOR CONTINUITY:\n{context_str}\n\n"
        f"BRAND RULES: {brand.reference_guidelines[:500]}\n"
        f"TASK: Rewrite ONLY the current slide. Ensure it flows perfectly from previous and into next slides.\n"
        f"Return the updated slide JSON (title, content, image_prompt, voiceover_script).\n"
        f"CRITICAL: The 'content' field MUST be a JSON array of strings (e.g., [\"Bullet 1\", \"Bullet 2\"]), NOT a single string."
    )
    
    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SlidecastSlide
        ),
        label="slide-update"
    )
    
    new_slide_data = SlidecastSlide.model_validate_json(response.text)
    
    # Overwrite the specific slide
    manifest.slides[slide_index] = new_slide_data
    # Clear assets to force regeneration
    manifest.slides[slide_index].start_image_url = None
    manifest.slides[slide_index].end_image_url = None
    manifest.slides[slide_index].audio_url = None
    manifest.slides[slide_index].video_url = None
    
    return manifest
