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
from ...state import STORYLINE_MODEL, SLIDE_STYLES, VOICEOVER_STYLES, LOGO_IMAGE_URI_STATE_KEY
from .core import _retry_generate_content, _download_uri, _upload_bytes
from .image import _generate_gemini_image
from .audio import _generate_voiceover_audio
from .video import _generate_single_veo_clip
from ..schemas import SlidecastManifest, SlidecastSlide, BrandContext, NanomationPlan, NanomationPhase

logger = logging.getLogger(__name__)

def _generate_approval_pdf(title: str, slides: List[SlidecastSlide], slide_images: List[bytes]) -> bytes:
    """Generates a professional PDF for asset approval."""
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
        pdf.multi_cell(0, 6, slide.voiceover_script)
        pdf.ln(15)

    return pdf.output()

async def preview_slidecast_assets(manifest: SlidecastManifest, brand: BrandContext) -> dict:
    """Generates images, audio clips, and a summary PDF for the slidecast."""
    log_message(f"Starting asset preview for: {manifest.title}", Severity.INFO)
    
    # 1. Download Logo if available
    logo_bytes = await _download_uri(brand.reference_guidelines) # Fallback to guidelines as ref for now
    ref_bytes = [logo_bytes] if logo_bytes else []
    
    # 2. Generate Images and Audio in parallel
    async def _gen_slide_assets(slide: SlidecastSlide):
        img_task = _generate_gemini_image(slide.image_prompt, ref_bytes, label=f"slide_{slide.index}", aspect_ratio=manifest.aspect_ratio)
        audio_task = _generate_voiceover_audio(slide.voiceover_script)
        return await asyncio.gather(img_task, audio_task)

    results = await asyncio.gather(*[_gen_slide_assets(s) for s in manifest.slides])
    
    # 3. Upload assets and prepare for PDF
    slide_images = []
    ts = int(time.time() * 1000)
    
    for i, (img_bytes, audio_bytes) in enumerate(results):
        if img_bytes:
            url = await _upload_bytes(img_bytes, "mcp_slidecast_preview", f"slide_{i}_{ts}.png", "image/png")
            manifest.slides[i].image_url = url
            slide_images.append(img_bytes)
        else:
            slide_images.append(b"") # Placeholder
            
        if audio_bytes:
            url = await _upload_bytes(audio_bytes, "mcp_slidecast_preview", f"audio_{i}_{ts}.wav", "audio/wav")
            manifest.slides[i].audio_url = url

    # 4. Generate PDF
    pdf_content = _generate_approval_pdf(manifest.title, manifest.slides, slide_images)
    pdf_url = await _upload_bytes(pdf_content, "mcp_slidecast_preview", f"approval_storyboard_{ts}.pdf", "application/pdf")
    
    return {
        "status": "success",
        "pdf_url": pdf_url,
        "manifest": manifest.model_dump()
    }

async def plan_slide_animation(slide_topic: str, company_name: str) -> NanomationPlan:
    """Generates a multi-phase animation plan for a slide topic."""
    prompt = (
        f"You are a Senior Motion Designer for {company_name}.\n"
        f"Plan a multi-segment video animation (Nanomation) for the topic: '{slide_topic}'.\n\n"
        f"Output ONLY valid JSON matching the schema with 'target', 'phases' (image_prompt, motion_prompt, duration_seconds), and 'topic'."
    )

    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7, response_mime_type="application/json"),
        label="nanomation-plan"
    )
    
    data = json.loads(response.text)
    phases = [NanomationPhase(**p) for p in data.get("phases", [])]
    
    return NanomationPlan(
        topic=data.get("topic", slide_topic),
        target=data.get("target", "Cinematic animation"),
        phases=phases
    )

async def generate_slidecast_manifest(
    brand: BrandContext,
    duration_seconds: int = 300,
    language: str = "English",
    aspect_ratio: str = "16:9",
    trend_context: str = ""
) -> SlidecastManifest:
    """Stateless generator for a slidecast presentation blueprint."""
    
    words_per_slide = 40
    # Estimate slides based on duration (avg 20s per slide)
    num_slides = max(3, duration_seconds // 20)
    
    style_desc = SLIDE_STYLES.get("Documentary Realism", "")
    
    prompt = (
        f"You are a MASTER PRESENTATION DESIGNER. Create a {num_slides}-slide presentation for {brand.company_name}.\n"
        f"Language: {language} | Aspect Ratio: {aspect_ratio}\n"
        f"Context/Trends: {trend_context}\n"
        f"Brand Rules: {brand.reference_guidelines[:1000]}\n"
        f"Target Persona: {brand.customer_persona}\n\n"
        f"FORMAT RULES:\n"
        f"- Each slide MUST have: 'title', 'content' (bullet points), 'image_prompt' (photorealistic {style_desc}), and 'voiceover_script' (~{words_per_slide} words).\n"
        f"- NO markdown. Output EXACTLY JSON matching the schema.\n"
    )

    response = await _retry_generate_content(
        model=STORYLINE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
        label="slidecast-gen"
    )
    
    data = json.loads(response.text)
    slides_data = data.get("slides", [])
    
    slides = []
    for i, s in enumerate(slides_data):
        slides.append(SlidecastSlide(
            index=i,
            title=s.get("title", f"Slide {i+1}"),
            content=s.get("content", ""),
            image_prompt=s.get("image_prompt", ""),
            voiceover_script=s.get("voiceover_script", "")
        ))
        
    return SlidecastManifest(
        title=data.get("title", f"Presentation for {brand.company_name}"),
        company_name=brand.company_name,
        aspect_ratio=aspect_ratio,
        language=language,
        slides=slides
    )

async def update_slide_blueprint(
    manifest: SlidecastManifest,
    slide_index: int,
    instructions: str,
    brand: BrandContext
) -> SlidecastManifest:
    """Updates a single slide in the manifest based on natural language instructions."""
    if slide_index < 0 or slide_index >= len(manifest.slides):
        raise ValueError(f"Invalid slide index {slide_index}")
        
    target_slide = manifest.slides[slide_index]
    
    prompt = (
        f"Update this slide based on user feedback: '{instructions}'\n"
        f"Current Slide: {target_slide.model_dump_json()}\n"
        f"Brand Context: {brand.reference_guidelines[:500]}\n"
        f"Return the updated slide JSON only."
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
    
    return manifest

async def update_storyboard_visual_style(
    manifest: SlidecastManifest,
    new_style_name: str,
    brand: BrandContext
) -> SlidecastManifest:
    """Rewrites image prompts for all slides in the manifest to match a new visual style."""
    log_message(f"Updating overall storyboard visual style to: {new_style_name}...", Severity.INFO)
    style_desc = SLIDE_STYLES.get(new_style_name, new_style_name)

    async def _rewrite_prompt(slide: SlidecastSlide):
        prompt = (
            f"You are a Senior Art Director for {brand.company_name}.\n"
            f"Transition this slidecast to a new visual style: {new_style_name}.\n"
            f"Style Description: {style_desc}\n\n"
            f"CURRENT IMAGE PROMPT:\n{slide.image_prompt}\n"
            f"CURRENT NARRATION SCRIPT (For context):\n{slide.voiceover_script}\n\n"
            f"TASK: Rewrite the image prompt to match the new style. Include the {brand.company_name} logo in bottom right. Output ONLY the new prompt text."
        )
        response = await _retry_generate_content(
            model=STORYLINE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7),
            label=f"style-rewrite-{slide.index}"
        )
        if response.text:
            slide.image_prompt = response.text.strip()
            # Clear visual asset URIs to force regeneration
            slide.image_uri = None
            slide.video_uri = None
        return slide

    tasks = [_rewrite_prompt(s) for s in manifest.slides]
    manifest.slides = await asyncio.gather(*tasks)
    return manifest
