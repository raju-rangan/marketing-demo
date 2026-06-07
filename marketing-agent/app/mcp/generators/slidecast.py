import asyncio
import json
import logging
import tempfile
import os
import time
from typing import List, Optional
from fpdf import FPDF

from google.genai import types

from ...adk_common.utils.utils_logging import Severity, log_message
from ...state import STORYLINE_MODEL, SLIDE_STYLES, VOICEOVER_STYLES, LOGO_IMAGE_URI_STATE_KEY, LLM_GEMINI_MODEL_MARKETING_ANALYST
from .core import _retry_generate_content, _download_uri, _upload_bytes, client
from .image import _generate_gemini_image
from .audio import _generate_voiceover_audio
from .video import _generate_single_veo_clip
from ..schemas import SlidecastManifest, SlidecastSlide, BrandContext, NanomationPlan, NanomationPhase

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

# ============================================================
# Public Generators
# ============================================================

async def generate_slidecast_manifest(
    brand: BrandContext,
    urls: List[str] = None,
    trend_context: str = "",
    duration_seconds: int = 300,
    language: str = "English",
    aspect_ratio: str = "16:9",
    slide_style: str = "Documentary Realism"
) -> SlidecastManifest:
    """
    Stateless generator for a slidecast presentation blueprint.
    Restores dynamic scaling and detailed persona prompts from legacy.
    """
    duration_minutes = duration_seconds / 60.0
    total_word_target = max(60, int(duration_minutes * 160))
    
    if duration_seconds <= 60:
        # Shorts mode: high frequency of visual changes
        num_slides = max(3, int(duration_seconds / 7.5))
    else:
        # Long-form mode: educational pacing
        num_slides = max(12, min(25, int(duration_minutes * 5)))
        
    words_per_slide = max(10, total_word_target // num_slides)
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
        f"- Every image prompt MUST include: 'Include the {brand.company_name} logo in the bottom right corner.'\n"
        f"- If animation is requested, include an 'end_image_prompt' that is a subtle variation of the 'image_prompt' to allow for motion.\n\n"
        f"Output ONLY valid JSON matching the schema with 'title', 'slides' (index, title, content, image_prompt, end_image_prompt, voiceover_script)."
    )

    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7, 
            response_mime_type="application/json",
            tools=[types.Tool(google_search=types.GoogleSearch())] if urls else None
        ),
        label="slidecast-manifest"
    )
    
    data = json.loads(response.text)
    slides = [SlidecastSlide(**s) for s in data.get("slides", [])]
        
    return SlidecastManifest(
        title=data.get("title", f"Presentation for {brand.company_name}"),
        company_name=brand.company_name,
        aspect_ratio=aspect_ratio,
        language=language,
        slides=slides,
        slide_style=slide_style
    )

async def preview_slidecast_assets(manifest: SlidecastManifest, brand: BrandContext) -> dict:
    """
    Generates images, audio clips, and a summary PDF for the slidecast.
    Restores 'skip if exists' logic and branded reference loading.
    """
    log_message(f"Starting asset preview for: {manifest.title}", Severity.INFO)
    
    # 1. Load brand assets for reference
    logo_bytes = await _download_uri(brand.logo_uri) if brand.logo_uri else None
    ref_images = [logo_bytes] if logo_bytes else []
    
    # 2. Process slides in parallel
    async def _gen_slide_assets(slide: SlidecastSlide):
        # IMAGE (START): Skip if already exists
        if slide.start_image_url:
            log_message(f"Slide {slide.index+1}: using existing start image.", Severity.INFO)
            start_img_bytes = await _download_uri(slide.start_image_url)
        else:
            log_message(f"Slide {slide.index+1}: generating new start image...", Severity.INFO)
            styled_prompt = f"{slide.image_prompt}\n\nREFERENCE BRAND RULES:\n{brand.reference_guidelines[:500]}"
            start_img_bytes = await _generate_gemini_image(
                styled_prompt, 
                ref_images, 
                label=f"slide_{slide.index}_start", 
                aspect_ratio=manifest.aspect_ratio
            )
            if start_img_bytes:
                url = await _upload_bytes(start_img_bytes, "mcp_slidecast", f"slide_{slide.index}_start.png", "image/png")
                slide.start_image_url = url
                log_message(f"🏳️ Slide {slide.index+1} START IMAGE: {url}", Severity.INFO)

        # IMAGE (END): Only if requested and not exists
        end_img_bytes = None
        if slide.end_image_prompt:
            if slide.end_image_url:
                log_message(f"Slide {slide.index+1}: using existing end image.", Severity.INFO)
                end_img_bytes = await _download_uri(slide.end_image_url)
            else:
                log_message(f"Slide {slide.index+1}: generating new end image...", Severity.INFO)
                # Inject start_img_bytes into the reference list for consistency
                end_ref_images = ref_images + ([start_img_bytes] if start_img_bytes else [])
                styled_prompt = f"{slide.end_image_prompt}\n\nREFERENCE BRAND RULES:\n{brand.reference_guidelines[:500]}"
                end_img_bytes = await _generate_gemini_image(
                    styled_prompt, 
                    end_ref_images, 
                    label=f"slide_{slide.index}_end", 
                    aspect_ratio=manifest.aspect_ratio
                )
                if end_img_bytes:
                    url = await _upload_bytes(end_img_bytes, "mcp_slidecast", f"slide_{slide.index}_end.png", "image/png")
                    slide.end_image_url = url
                    log_message(f"🏁 Slide {slide.index+1} END IMAGE: {url}", Severity.INFO)
        
        # AUDIO: Skip if already exists
        if slide.audio_url:
            log_message(f"Slide {slide.index+1}: using existing audio.", Severity.INFO)
            audio_bytes = await _download_uri(slide.audio_url)
        else:
            log_message(f"Slide {slide.index+1}: generating new audio...", Severity.INFO)
            voice_id = VOICEOVER_STYLES.get(manifest.voiceover_style, "Puck")
            audio_bytes = await _generate_voiceover_audio(slide.voiceover_script, voice_name=voice_id)
            if audio_bytes:
                url = await _upload_bytes(audio_bytes, "mcp_slidecast", f"audio_{slide.index}.wav", "audio/wav")
                slide.audio_url = url
                
        return slide, start_img_bytes, end_img_bytes

    results = await asyncio.gather(*[_gen_slide_assets(s) for s in manifest.slides])
    
    # 3. Compile PDF
    updated_slides = [r[0] for r in results]
    slide_images = [(r[1] or b"", r[2] or b"") for r in results]
    manifest.slides = updated_slides
    
    pdf_content = _generate_approval_pdf(manifest.title, manifest.slides, slide_images)
    pdf_url = await _upload_bytes(pdf_content, "mcp_slidecast", f"approval_document_{int(time.time())}.pdf", "application/pdf")
    
    return {
        "status": "success",
        "pdf_url": pdf_url,
        "manifest": manifest.model_dump()
    }

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
        config=types.GenerateContentConfig(temperature=0.7, response_mime_type="application/json"),
        label="nanomation-plan"
    )
    
    data = json.loads(response.text)
    phases = [NanomationPhase(**p) for p in data.get("phases", [])]
    
    return NanomationPlan(
        topic=data.get("topic", slide.title),
        target=data.get("target", "Educational animation"),
        phases=phases
    )

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
        f"Return the updated slide JSON (title, content, image_prompt, voiceover_script)."
    )
    
    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
        label="slide-update"
    )
    
    new_data = json.loads(response.text)
    manifest.slides[slide_index] = SlidecastSlide(
        index=slide_index,
        title=new_data.get("title", target_slide.title),
        content=new_data.get("content", target_slide.content),
        image_prompt=new_data.get("image_prompt", target_slide.image_prompt),
        voiceover_script=new_data.get("voiceover_script", target_slide.voiceover_script)
    )
    # Clear assets to force regeneration
    manifest.slides[slide_index].start_image_url = None
    manifest.slides[slide_index].end_image_url = None
    manifest.slides[slide_index].audio_url = None
    manifest.slides[slide_index].video_url = None
    
    return manifest
