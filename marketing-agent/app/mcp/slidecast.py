import json
import logging
from typing import List, Optional
from mcp.server.fastmcp import FastMCP
from .schemas import SlidecastManifest, BrandContext, NanomationPlan
from .generators.slidecast import (
    generate_slidecast_manifest, 
    update_slide_blueprint, 
    plan_slide_animation, 
    generate_approval_pdf_backend, 
    generate_slidecast_audio_assets,
    rewrite_image_prompts,
    rewrite_audio_prompts
)
from .generators.core import _upload_bytes
from .generators.image import _generate_gemini_image
from .generators.audio import _generate_voiceover_audio
from .generators.video import _generate_single_veo_clip
from ..adk_common.utils.utils_logging import Severity, log_message
from ..state import SLIDE_STYLES, VOICEOVER_STYLES, CHOSEN_SLIDE_STYLE_STATE_KEY, CHOSEN_VOICEOVER_STYLE_STATE_KEY, ANIMATE_SLIDECAST_STATE_KEY

logger = logging.getLogger(__name__)

def add_slidecast_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def select_slidecast_style(slide_style: str, voiceover_style: str, animate: bool = True, use_preapproved_style: bool = True) -> str:
        """
        Records the user's preferred visual and vocal style for a Slidecast.
        
        WHEN TO USE:
        Use this immediately after presenting the user with styling options, before generating the story arc.
        
        ARGS:
        - slide_style (str): The visual aesthetic (e.g. 'Flat Vector Explainer', 'Documentary Realism'). Must exactly match an available option unless use_preapproved_style is True.
        - voiceover_style (str): The persona of the narrator (e.g. 'Energetic & Engaging').
        - animate (bool): Whether the final video should use Veo animations (True) or static images (False).
        - use_preapproved_style (bool): Set to True if the user selected Option 1 (Brand-Approved Identity). If True, slide_style can be an arbitrary string like 'Brand Identity'.
        
        RETURNS:
        A JSON string confirming the selection. The agent must remember these choices to pass to subsequent tools.
        """
        if not use_preapproved_style and slide_style not in SLIDE_STYLES:
            return json.dumps({"status": "error", "message": f"Invalid slide style. Choose from: {list(SLIDE_STYLES.keys())} or set use_preapproved_style to True."})
        if voiceover_style not in VOICEOVER_STYLES:
            return json.dumps({"status": "error", "message": f"Invalid voiceover style. Choose from: {list(VOICEOVER_STYLES.keys())}"})

        # In MCP stateless mode, we return the success message. 
        # The agent is responsible for remembering these choices or passing them to subsequent tools.
        animate_msg = "with AI video animations" if animate else "using static slides"
        style_msg = "Brand Preapproved Style" if use_preapproved_style else slide_style
        return json.dumps({
            "status": "success", 
            "message": f"Style locked: {style_msg} / {voiceover_style} ({animate_msg})",
            "slide_style": slide_style,
            "voiceover_style": voiceover_style,
            "animate": animate,
            "use_preapproved_style": use_preapproved_style
        })

    @mcp.tool()
    async def generate_animation_plan(slide_topic: str, company_name: str) -> str:
        """
        Creates a detailed multi-segment animation plan (Nanomation) for a specific slide topic.
        
        WHEN TO USE:
        Use this when a user wants to break down a complex, single slide topic into a series of smaller, sequential animation phases (e.g., explaining a multi-step process).
        
        ARGS:
        - slide_topic (str): The specific subject or concept to be animated.
        - company_name (str): The brand context.
        
        RETURNS:
        A JSON string matching the NanomationPlan schema, containing the progressive animation phases.
        """
        try:
            plan = await plan_slide_animation(slide_topic, company_name)
            return plan.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_story_arc(
        company_name: str,
        slide_style: str,
        animate_slides: bool,
        voiceover_style: str,
        use_preapproved_style: bool = False,
        urls: List[str] = None,
        reference_guidelines: str = "",
        customer_persona: str = "",
        duration_seconds: int = 300,
        language: str = "English",
        aspect_ratio: str = "16:9",
        trend_context: str = ""
    ) -> str:
        """
        Generates the foundational master story arc and storyboard manifest for a Slidecast.
        
        WHEN TO USE:
        Gate 1. Use this to create the initial structural blueprint (titles, text content, unrendered image/audio prompts) after the user has selected their styles.
        
        ARGS:
        - company_name, slide_style, animate_slides, voiceover_style: Required context.
        - use_preapproved_style: Whether to use the preapproved brand identity style.
        - urls: Source material links provided by the user.
        - duration_seconds: Expected video length (e.g., 60 for Shorts, 300 for Slidecasts).
        - trend_context: Strategic angle derived from the trend-analysis skill.
        
        RETURNS:
        A JSON string of the completed SlidecastManifest. The agent must hold this JSON state to pass to subsequent rendering tools.
        """
        try:
            brand = BrandContext(
                company_name=company_name,
                reference_guidelines=reference_guidelines,
                customer_persona=customer_persona
            )
            
            manifest = await generate_slidecast_manifest(
                brand=brand,
                urls=urls,
                trend_context=trend_context,
                duration_seconds=duration_seconds,
                language=language,
                aspect_ratio=aspect_ratio,
                slide_style=slide_style,
                animate_slides=animate_slides,
                voiceover_style=voiceover_style,
                use_preapproved_style=use_preapproved_style
            )
            manifest.use_preapproved_style = use_preapproved_style
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_image_prompts(manifest: SlidecastManifest, override_instructions: str = "", reference_guidelines: str = "") -> str:
        """
        Rewrites or updates the visual image prompts within an existing SlidecastManifest.
        
        WHEN TO USE:
        Use this to surgically modify the visual directives (prompts) across the entire storyboard without altering the narrative script.
        
        ARGS:
        - manifest: The current SlidecastManifest Pydantic object.
        - override_instructions (str): The natural language instructions for how to change the visuals (e.g., "Make them all cyberpunk style").
        
        RETURNS:
        A JSON string of the updated SlidecastManifest. Note: This does NOT render the images; it only updates the prompts. Call `render_images` afterward to generate the actual PNGs.
        """
        try:
            if override_instructions:
                brand = BrandContext(company_name=manifest.company_name, reference_guidelines=reference_guidelines)
                manifest = await rewrite_image_prompts(manifest, override_instructions, brand)
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_audio_prompts(manifest: SlidecastManifest, override_instructions: str = "", reference_guidelines: str = "") -> str:
        """
        Rewrites or updates the voiceover scripts within an existing SlidecastManifest.
        
        WHEN TO USE:
        Use this to surgically modify the spoken narrative scripts across the entire storyboard without altering the visual structure.
        
        ARGS:
        - manifest: The current SlidecastManifest Pydantic object.
        - override_instructions (str): The natural language instructions for how to change the scripts (e.g., "Make the tone much more aggressive").
        
        RETURNS:
        A JSON string of the updated SlidecastManifest. Note: This does NOT generate the audio files; it only updates the text scripts. Call `render_audio` afterward to generate the WAV files.
        """
        try:
            if override_instructions:
                brand = BrandContext(company_name=manifest.company_name, reference_guidelines=reference_guidelines)
                manifest = await rewrite_audio_prompts(manifest, override_instructions, brand)
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def render_images(manifest: SlidecastManifest, reference_guidelines: str = "", slide_index: Optional[int] = None) -> str:
        """
        Renders the actual image assets (PNGs) for the slides by calling the AI image generator.
        
        WHEN TO USE:
        Gate 1.6. Call this AFTER the text and prompts are approved, but BEFORE generating the Approval PDF.
        
        ARGS:
        - manifest: The current SlidecastManifest.
        - slide_index (int, optional): If provided, ONLY re-renders the image for that specific slide (useful for surgical edits). If null, renders missing images for all slides.
        
        RETURNS:
        A JSON string of the updated SlidecastManifest with populated 'start_image_url' and 'end_image_url' fields.
        """
        try:
            brand = BrandContext(company_name=manifest.company_name, reference_guidelines=reference_guidelines)
            
            # Identify slides to process
            slides_to_process = [manifest.slides[slide_index]] if slide_index is not None else manifest.slides
            
            import asyncio
            import os
            from .generators.core import _download_uri
            
            preapproved_img_bytes = None
            if getattr(manifest, "use_preapproved_style", False):
                active_brand = os.environ.get("ACTIVE_BRAND", "goog")
                bucket_name = os.environ.get("GOOGLE_CLOUD_BUCKET_ARTIFACTS")
                if bucket_name:
                    style_ref_uri = f"gs://{bucket_name}/brands/{active_brand}/assets/reference_image.png"
                    preapproved_img_bytes = await _download_uri(style_ref_uri)

            async def _process_slide_images(slide):
                # We need to hold the bytes locally to pass them as references, 
                # even if the URL is already set, so we attempt to download if it exists.
                start_img_bytes = None
                
                # 1. IMAGE (START)
                if slide_index is not None or not slide.start_image_url:
                    styled_prompt = f"{slide.image_prompt}\n\nBRAND RULES:\n{brand.reference_guidelines[:500]}"
                    ref_images = []
                    if preapproved_img_bytes:
                        ref_images = [preapproved_img_bytes]
                        styled_prompt += "\n\nUse Image 1 as the definitive source for both character identity (features, appearance) AND the Primary Style Reference (color palette, lighting, rendering technique). Fully re-render the subject into the style of Image 1."
                    start_img_bytes = await _generate_gemini_image(styled_prompt, ref_images, label=f"slide_{slide.index}_start", aspect_ratio=manifest.aspect_ratio)
                    if start_img_bytes:
                        slide.start_image_url = await _upload_bytes(start_img_bytes, "mcp_slidecast", f"slide_{slide.index}_start.png", "image/png")
                else:
                    # Download existing so we can use it as a reference
                    start_img_bytes = await _download_uri(slide.start_image_url)

                # 2. IMAGE (END)
                if slide.end_image_prompt and (slide_index is not None or not slide.end_image_url):
                    # Pass the start image as a strict visual reference to maintain consistency
                    ref_images = []
                    styled_prompt = f"{slide.end_image_prompt}\n\nBRAND RULES:\n{brand.reference_guidelines[:500]}"
                    if preapproved_img_bytes:
                        ref_images = [preapproved_img_bytes]
                        if start_img_bytes:
                            ref_images.append(start_img_bytes)
                            styled_prompt += "\n\nUse Image 1 as the definitive source for both character identity (features, appearance) AND the Primary Style Reference (color palette, lighting, rendering technique). Fully re-render the subject into the style of Image 1."
                            styled_prompt += "\nUse Image 2 as the temporal structural guide for consistency, ensuring the character's pose and outline transition naturally from the state established in Image 2."
                        else:
                            styled_prompt += "\n\nUse Image 1 as the definitive source for both character identity (features, appearance) AND the Primary Style Reference (color palette, lighting, rendering technique). Fully re-render the subject into the style of Image 1."
                    else:
                        if start_img_bytes:
                            ref_images = [start_img_bytes]
                    end_img_bytes = await _generate_gemini_image(styled_prompt, ref_images, label=f"slide_{slide.index}_end", aspect_ratio=manifest.aspect_ratio)
                    if end_img_bytes:
                        slide.end_image_url = await _upload_bytes(end_img_bytes, "mcp_slidecast", f"slide_{slide.index}_end.png", "image/png")
            
            # Process all slides concurrently
            await asyncio.gather(*[_process_slide_images(slide) for slide in slides_to_process])
            
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_approval_pdf(manifest: SlidecastManifest) -> str:
        """
        Compiles the text scripts and rendered image assets into a storyboard PDF document for human approval.
        
        WHEN TO USE:
        Gate 2. Call this AFTER render_images is complete. Present the returned PDF URL to the user and wait for their explicit approval before proceeding to audio/video generation.
        
        ARGS:
        - manifest: The current SlidecastManifest. It must contain the image URLs generated by render_images.
        
        RETURNS:
        A JSON object containing the 'approval_pdf_url' (a GCS link to the generated document).
        """
        try:
            # Use renamed backend function
            pdf_url = await generate_approval_pdf_backend(manifest)
            return json.dumps({"status": "success", "approval_pdf_url": pdf_url}, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def render_audio(manifest: SlidecastManifest, slide_index: Optional[int] = None) -> str:
        """
        Generates the final voiceover audio assets (WAVs) using Text-to-Speech models.
        
        WHEN TO USE:
        Gate 3. Call this ONLY AFTER the user has explicitly approved the Approval PDF.
        
        ARGS:
        - manifest: The approved SlidecastManifest.
        - slide_index (int, optional): If provided, ONLY re-renders the audio for that specific slide (useful for surgical edits).
        
        RETURNS:
        A JSON string of the updated SlidecastManifest with populated 'audio_url' fields.
        """
        try:
            # Logic: If slide_index is provided, only process that slide. Otherwise process all.
            if slide_index is not None:
                slide = manifest.slides[slide_index]
                # Logic to generate audio for specific slide
                voice_id = VOICEOVER_STYLES.get(manifest.voiceover_style, "Puck")
                audio_bytes = await _generate_voiceover_audio(slide.voiceover_script, voice_name=voice_id)
                if audio_bytes:
                    slide.audio_url = await _upload_bytes(audio_bytes, "mcp_slidecast", f"audio_{slide.index}.wav", "audio/wav")
                log_message(f"Regenerated audio for slide {slide.index+1}", Severity.INFO)
            else:
                manifest = await generate_slidecast_audio_assets(manifest)
                
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def generate_video_segments(manifest: SlidecastManifest, slide_index: Optional[int] = None) -> str:
        """
        Generates the individual animated video clips (MP4s) for the slides using Veo.
        
        WHEN TO USE:
        Gate 3. Call this AFTER the user has approved the PDF, and ONLY IF the user requested an 'Animated' video format.
        
        ARGS:
        - manifest: The approved SlidecastManifest containing rendered start/end images.
        - slide_index (int, optional): If provided, ONLY re-renders the animation for that specific slide (surgical edit).
        
        RETURNS:
        A JSON string of the updated SlidecastManifest with populated 'video_url' fields.
        """
        try:
            slides_to_process = [manifest.slides[slide_index]] if slide_index is not None else manifest.slides
            
            import asyncio
            
            # Concurrency limit of 5 to avoid overwhelming Veo
            semaphore = asyncio.Semaphore(5)
            
            async def _process_slide_video(slide):
                if slide.video_url and slide_index is None:
                    return # Skip if exists, unless forced by slide_index
                
                async with semaphore:
                    # Veo clip generation
                    vid_bytes = await _generate_single_veo_clip(
                        prompt=slide.image_prompt,
                        start_frame_gcs_uri=slide.start_image_url,
                        end_frame_gcs_uri=slide.end_image_url,
                        clip_duration=8,
                        label=f"slide_{slide.index}",
                        aspect_ratio=manifest.aspect_ratio
                    )
                    if vid_bytes:
                        slide.video_url = await _upload_bytes(vid_bytes, "mcp_slidecast", f"segment_{slide.index}.mp4", "video/mp4")
                        log_message(f"Generated animation segment for slide {slide.index+1}", Severity.INFO)
            
            # Process all slides with semaphore limit
            await asyncio.gather(*[_process_slide_video(slide) for slide in slides_to_process])
            
            return manifest.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def update_storyboard_visual_style(manifest: SlidecastManifest, new_style_name: str, reference_guidelines: str = "") -> str:
        """
        Rewrites all image prompts in a storyboard to match a new visual style.
        
        WHEN TO USE:
        Use this when the user wants to change the overall art/aesthetic style of the presentation (e.g., from 'Flat Vector' to '3D Isometric') without changing the spoken script.
        
        ARGS:
        - manifest: The current SlidecastManifest.
        - new_style_name (str): The name of the new visual style requested by the user.
        
        RETURNS:
        A JSON string of the updated SlidecastManifest. Note: You must call render_images afterward to generate the new images.
        """
        try:
            brand = BrandContext(
                company_name=manifest.company_name,
                reference_guidelines=reference_guidelines
            )
            
            updated_manifest = await update_storyboard_visual_style(manifest, new_style_name, brand)
            return updated_manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to update visual style: {e}")
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def update_slidecast_slide(
        manifest: SlidecastManifest,
        slide_index: int,
        instructions: str,
        reference_guidelines: str = ""
    ) -> str:
        """
        Surgically rewrites the text content (script, title, and image prompt) of a specific slide based on user feedback.
        
        WHEN TO USE:
        Use this when the user requests a specific change to a single slide (e.g., "Change the script on slide 3 to mention security").
        
        ARGS:
        - manifest: The current SlidecastManifest.
        - slide_index (int): The 0-based index of the slide to update.
        - instructions (str): The user's specific feedback or instructions for the change.
        
        RETURNS:
        A JSON string of the updated SlidecastManifest. Note: This clears the generated assets for that slide. You must call render_images/render_audio for that specific slide_index afterward.
        """
        try:
            brand = BrandContext(
                company_name=manifest.company_name,
                reference_guidelines=reference_guidelines
            )
            
            updated_manifest = await update_slide_blueprint(
                manifest=manifest,
                slide_index=slide_index,
                instructions=instructions,
                brand=brand
            )
            
            return updated_manifest.model_dump_json(indent=2)
            
        except Exception as e:
            logger.error(f"Failed to update slidecast: {e}")
            return json.dumps({"status": "error", "details": str(e)})
