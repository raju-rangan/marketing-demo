import json
from typing import List
from google.adk.tools.tool_context import ToolContext
from ...adk_common.utils.utils_logging import Severity, log_message, stream_status
from ...state import (
    REFERENCE_GUIDELINES_STATE_KEY,
    CHOSEN_SLIDE_STYLE_STATE_KEY,
    SLIDE_STYLES,
)
from ...schema import SlidecastStoryboard
from ..misc import select_brand_preset
from .utils import (
    _get_slidecast_branding_context,
    _get_slidecast_format_directives,
    client,
    types,
)

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

    brand_ctx = _get_slidecast_branding_context(tool_context)
    if not brand_ctx["selected_style_name"]:
         return {
            "status": "error", 
            "message": "Visual style not set. You MUST present the available styles to the user and call `select_slidecast_style` to lock in their choice BEFORE generating the storyboard."
        }

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
    
    fmt_directives = _get_slidecast_format_directives(
        aspect_ratio=aspect_ratio, 
        language=language, 
        company_name=brand_ctx["company_name"], 
        style_desc=brand_ctx["style_desc"], 
        branding_directive=brand_ctx["branding_directive"],
        duration_seconds=duration_seconds,
        words_per_slide=words_per_slide
    )

    url_list_str = "\n".join([f"- {url}" for url in urls]) if urls else "No specific URLs provided."

    prompt = (
        f"You are a {fmt_directives['persona']}.\n"
        f"Goal: {fmt_directives['goal']}\n\n"
        f"SOURCE MATERIAL:\n"
        f"Research the following URLs to gather the factual content for this presentation:\n"
        f"{url_list_str}\n\n"
        f"TREND CONTEXT:\n"
        f"Use the following market trends to subtly inform the narrative tone and hooks, but DO NOT invent facts:\n"
        f"{trend_context}\n\n"
        f"STRUCTURE REQUIREMENTS:\n"
        f"{fmt_directives['structure_requirements']}\n"
        f"- TOTAL SLIDES: {num_slides} distinct visual scenes/slides.\n"
        f"- TARGET WORD COUNT: ~{total_word_target} words total.\n"
        f"- TARGET PER SLIDE: ~{words_per_slide} words of detailed narration.\n\n"
        f"CORE DIRECTIVES:\n"
        f"{fmt_directives['core_directives']}\n\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{fmt_directives['schema_json']}"
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
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
    brand_ctx = _get_slidecast_branding_context(tool_context)
    
    # Gather context from surrounding slides for continuity
    context_str = ""
    if slide_index > 0:
        prev_slide = sb.slides[slide_index - 1]
        context_str += f"\n[PREVIOUS SLIDE - Slide {slide_index}]:\nTitle: {prev_slide.slide_title}\nScript: {prev_slide.script}\n"
    
    context_str += f"\n[CURRENT SLIDE TO UPDATE - Slide {slide_index + 1}]:\nTitle: {target_slide.slide_title}\nImage Prompt: {target_slide.image_prompt}\nScript: {target_slide.script}\n"
    
    if slide_index < len(sb.slides) - 1:
        next_slide = sb.slides[slide_index + 1]
        context_str += f"\n[NEXT SLIDE - Slide {slide_index + 2}]:\nTitle: {next_slide.slide_title}\nScript: {next_slide.script}\n"

    fmt_directives = _get_slidecast_format_directives(
        aspect_ratio=sb.aspect_ratio,
        language="the requested language", # Continuity will handle the specific language
        company_name=brand_ctx["company_name"],
        style_desc=brand_ctx["style_desc"],
        branding_directive=brand_ctx["branding_directive"]
    )

    prompt = (
        f"You are a {fmt_directives['persona']}.\n"
        f"The user has requested an update to ONE specific slide (Slide {slide_index + 1}) in a larger Slidecast presentation.\n\n"
        f"USER INSTRUCTIONS:\n{instructions}\n\n"
        f"CONTEXT (For Continuity):\n{context_str}\n\n"
        f"TASK:\n"
        f"Rewrite ONLY Slide {slide_index + 1}. Ensure the new script flows seamlessly from the previous slide and leads naturally into the next slide. Update the image prompt if the user's instructions affect the visuals.\n\n"
        f"CORE DIRECTIVES:\n"
        f"{fmt_directives['core_directives']}\n\n"
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
            model="gemini-3.5-flash",
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

    brand_ctx = _get_slidecast_branding_context(tool_context)
    company_name = brand_ctx["company_name"]
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
            f"Ensure the new image prompt still describes a scene that makes sense with the narration script, and leaves the bottom right corner clear for the logo overlay.\n\n"
            f"Output ONLY the new raw image prompt string, nothing else. No quotes, no JSON."
        )

        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
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
