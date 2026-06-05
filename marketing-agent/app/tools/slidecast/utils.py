import tempfile
import os
from typing import List
from fpdf import FPDF
from google import genai
from google.genai import types
from google.adk.tools.tool_context import ToolContext
from ..misc import select_brand_preset
from ...adk_common.utils.utils_logging import Severity, log_message
from ...state import (
    GOOGLE_CLOUD_PROJECT,
    PRODUCT_COMPANY_NAME_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    CHOSEN_SLIDE_STYLE_STATE_KEY,
    CHOSEN_VOICEOVER_STYLE_STATE_KEY,
    ANIMATE_SLIDECAST_STATE_KEY,
    SLIDE_STYLES,
    VOICEOVER_STYLES,
)
from ...schema import SlidecastSlide

# Initialize GenAI Client
client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")

def _get_slidecast_branding_context(tool_context: ToolContext):
    """Retrieves and formats common branding context from the state."""
    company_name = tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY, "Brand")
    brand_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")
    selected_style_name = tool_context.state.get(CHOSEN_SLIDE_STYLE_STATE_KEY)
    
    style_desc = SLIDE_STYLES.get(selected_style_name, "Professional and clean corporate aesthetic")
    
    branding_directive = f"3. BRANDING: Use {company_name}'s color palette for all designs."
    if brand_guidelines:
        branding_directive += f" Follow these strict brand guidelines: {brand_guidelines[:2000]}"
        
    return {
        "company_name": company_name,
        "brand_guidelines": brand_guidelines,
        "style_desc": style_desc,
        "branding_directive": branding_directive,
        "selected_style_name": selected_style_name
    }

def _get_slidecast_format_directives(aspect_ratio: str, language: str, company_name: str, style_desc: str, branding_directive: str, duration_seconds: int = 300, words_per_slide: int = 40):
    """Returns format-specific prompt components for Slidecasts, preserving original strings."""
    duration_minutes = duration_seconds / 60.0
    
    if aspect_ratio == "9:16":
        # VIRAL SHORTS DIRECTIVES
        persona = f"expert Social Media Producer for {company_name}, specializing in high-retention viral Shorts (TikTok/Reels format)"
        goal = f"Create a fast-paced, high-energy storyboard for a {duration_seconds}-second vertical video (9:16) in {language}."
        structure_requirements = (
            f"- SLIDE 1 MUST BE THE HOOK: NO title slides. NO \"Welcome to...\" intros. Start immediately with a high-stakes question, shocking claim, or curiosity gap.\n"
            f"- RETENTION: Every 3-5 seconds (each slide) must introduce a pattern interrupt. Use punchy, fast-paced dialogue.\n"
            f"- THE CTA: The final slide must have an abrupt, direct call to action. Do NOT use formal corporate summaries."
        )
        core_directives = (
            f"1. KINETIC VISUALS: Every image prompt must describe a highly dynamic vertical scene. Think 'creator-style' angles, bold close-ups, or striking visual metaphors. Avoid dense, tiny corporate infographics that won't read on a phone.\n"
            f"2. KINETIC TEXT: Use the 'text_overlay' field to specify 1-3 massive, punchy words that should pop on screen for that slide. ALL TEXT MUST BE IN {language}.\n"
            f"3. NARRATION: Write conversational, punchy scripts in {language}. Ground them in the URLs, but translate them into creator-speak.\n"
            f"4. BRANDING: {branding_directive} Note: Keep logos subtle and out of the middle 60% safe zone.\n"
            f"5. VISUAL STYLE: {style_desc}"
        )
        schema_json = (
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
        # LONG-FORM DIRECTIVES
        persona = f"expert Lead Educational Producer for {company_name}"
        goal = f"Create a MASTER PLAN for a {duration_minutes}-minute in-depth educational 'Slidecast' in {language} (16:9 format)."
        structure_requirements = (
            f"- SLIDE 1 MUST BE A TITLE SLIDE: It should feature a bold, cinematic title of the topic in {language} and a welcoming, high-level introduction narration in {language}.\n"
            f"- FINAL SLIDE MUST BE A SUMMARY/CONCLUSION SLIDE: It must summarize the key takeaways in a logical manner and bring the presentation to a smooth, definitive close, avoiding any abrupt endings. If the article has an existing conclusion or summary, use that.\n"
            f"- LOGO INTEGRATION: The system will programmatically overlay the {company_name} logo in the bottom right corner. Ensure your image prompts leave the bottom right corner clear of key content (text, critical diagrams) to accommodate this overlay. Do NOT ask the image generator to draw the logo itself."
        )
        core_directives = (
            f"1. VISUAL SELF-SUFFICIENCY: Every image prompt MUST describe a professional infographic with text, diagrams, and data. ALL TEXT LABELS MUST BE IN {language}.\n"
            f"2. NARRATION & GROUNDING: Each voiceover script MUST be a detailed educational segment written in {language}. The narrative MUST be strictly grounded in the content of the provided URLs. Do not include external facts, unverified claims, or information not present in the original research. Do NOT be concise.\n"
            f"3. BRANDING: {branding_directive}\n"
            f"4. VISUAL STYLE: {style_desc} NO style variations across slides. Avoid overly metallic or glossy surfaces unless the prompt specifically requires a technological detail."
        )
        schema_json = (
            f"{{\n"
            f"  \"title\": \"Comprehensive Title in {language}\",\n"
            f"  \"summary_arc\": [\"[High-level phase 1]\", \"[High-level phase 2]\", ...],\n"
            f"  \"slides\": [\n"
            f"    {{\n"
            f"      \"slide_title\": \"[Concise Slide Title]\",\n"
            f"      \"image_prompt\": \"[Title Slide layout for {company_name} with the topic title in large typography in {language}. Leave bottom right corner clear for logo overlay. ALL text on the slide MUST be in {language}.]\",\n"
            f"      \"script\": \"[Introductory narration in {language} of approx {words_per_slide} words...]\",\n"
            f"      \"text_overlay\": \"\" \n"
            f"    }},\n"
            f"    {{\n"
            f"      \"slide_title\": \"[Concise Slide Title]\",\n"
            f"      \"image_prompt\": \"[Infographic layout with data and labels in {language}. Leave bottom right corner clear for logo overlay...]\",\n"
            f"      \"script\": \"[Detailed educational narration in {language}...]\",\n"
            f"      \"text_overlay\": \"\" \n"
            f"    }}\n"
            f"  ],\n"
            f"  \"music_prompt\": \"Sophisticated, cinematic educational background music\"\n"
            f"}}"
        )
        
    return {
        "persona": persona,
        "goal": goal,
        "structure_requirements": structure_requirements,
        "core_directives": core_directives,
        "schema_json": schema_json
    }

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
        pdf.multi_cell(0, 6, slide.script)
        pdf.ln(15)

    return pdf.output()

def select_slidecast_style(tool_context: ToolContext, slide_style: str, voiceover_style: str, animate: bool) -> dict:
    """Sets the visual and vocal style for the upcoming Slidecast.
    
    Args:
        slide_style: The visual aesthetic. 
            Options: 'Flat Vector Explainer', 'Modern 3D Isometric', 'Minimalist Flat Characters', 
                     'Documentary Realism', 'Stop-Motion Claymation', 'Minimalist Low-Poly 3D', 
                     'Glassmorphism & Abstract Data', 'Pencil Sketch'.
        voiceover_style: The persona of the narrator.
            Options: 'Energetic & Engaging', 'Professional & Trustworthy', 
                     'Calm & Sophisticated', 'Authoritative & Wise', 'Youthful & Fresh'.
        animate: Whether to animate the slides using AI video generation (Veo). Default is False.
    """
    if slide_style not in SLIDE_STYLES:
        return {"status": "error", "message": f"Invalid slide style. Choose from: {list(SLIDE_STYLES.keys())}"}
    if voiceover_style not in VOICEOVER_STYLES:
        return {"status": "error", "message": f"Invalid voiceover style. Choose from: {list(VOICEOVER_STYLES.keys())}"}

    tool_context.state[CHOSEN_SLIDE_STYLE_STATE_KEY] = slide_style
    tool_context.state[CHOSEN_VOICEOVER_STYLE_STATE_KEY] = voiceover_style
    tool_context.state[ANIMATE_SLIDECAST_STATE_KEY] = animate
    
    animate_msg = "with AI video animations" if animate else "using static slides"
    log_message(f"Slidecast style locked: {slide_style} / {voiceover_style} ({animate_msg})", Severity.INFO)
    
    return {
        "status": "success", 
        "message": f"Great choice! I've locked in the '{slide_style}' aesthetic and the '{voiceover_style}' voice. I'll be producing this {animate_msg}.",
        "slide_style": slide_style,
        "voiceover_style": voiceover_style,
        "animate": animate
    }
