import asyncio
import time
import json
from typing import List

from google.adk.tools.tool_context import ToolContext
from ...adk_common.dtos.generated_media import GeneratedMedia
from ...adk_common.utils import utils_agents, utils_gcs
from ...adk_common.utils.utils_logging import Severity, log_message, stream_status
from ...state import (
    LOGO_IMAGE_URI_STATE_KEY,
    LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY,
    LOGO_VERTICAL_IMAGE_URI_STATE_KEY,
    REFERENCE_GUIDELINES_STATE_KEY,
    CHOSEN_VOICEOVER_STYLE_STATE_KEY,
    VOICEOVER_STYLES,
    LLM_GEMINI_MODEL_MARKETING_ANALYST,
)
from ...utils.utils_gcs import get_public_url, set_output_folder
from ...schema import SlidecastStoryboard, SlidecastSlide
from ...shared_infra.utils_media import compile_slidecast_video, mix_audio_onto_video, overlay_logo_on_video
from ..media import (
    _generate_gemini_image,
    _generate_voiceover_audio,
    _generate_lyria_music,
    _generate_single_veo_clip,
)
from .utils import _generate_approval_pdf, client, types

@stream_status("🎨 Generating branded slide assets and narration...")
async def preview_slidecast_assets(tool_context: ToolContext, storyboard: dict) -> dict:
    """
    Generates actual images for review and creates an approval PDF.
    Supports partial regeneration by skipping images that already have a valid image_url.
    Must output the updated storyboard with a PDF approval document containing the slide images and scripts for easy review.
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

            # 1. Load brand assets based on aspect ratio
            ar = sb.aspect_ratio
            if ar == "9:16":
                logo_uri = tool_context.state.get(LOGO_VERTICAL_IMAGE_URI_STATE_KEY)
            else:
                logo_uri = tool_context.state.get(LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY)

            if not logo_uri:
                logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)

            ref_guidelines = tool_context.state.get(REFERENCE_GUIDELINES_STATE_KEY, "")

            logo_bytes = []
            if logo_uri:
                lres = await utils_agents.load_resource(logo_uri, tool_context)
                if lres:
                    logo_bytes = [lres.media_bytes]

            # 2. Inject guidelines into prompt
            styled_prompt = f"{slide.image_prompt}\n\nREFERENCE BRAND RULES:\n{ref_guidelines[:1000]}"

            # 3. Generate Image WITHOUT logo reference to avoid AI logo generation
            ar = sb.aspect_ratio
            img_bytes = await _generate_gemini_image(styled_prompt, [], label=f"slide_{idx+1}_image", aspect_ratio=ar)

            if not img_bytes:
                log_message(f"Failed to generate image for slide {idx+1}", Severity.ERROR)
                raise ValueError(f"Failed to generate image for slide {idx+1}")

            # Save clean image as artifact
            img_media = GeneratedMedia(filename=f"slide_{idx+1}.png", mime_type="image/png", media_bytes=img_bytes)
            saved_img = await utils_agents.save_to_artifact_and_render_asset(
                asset=img_media, context=tool_context, save_in_gcs=True, save_in_artifacts=False, gcs_folder=current_output_folder
            )
            slide.image_url = utils_gcs.normalize_to_gs_bucket_uri(saved_img.gcs_uri)

            # Overlay logo for PDF preview only
            preview_img_bytes = img_bytes
            if logo_bytes:
                from ...shared_infra.utils_media import overlay_logo_on_image
                preview_img_bytes = overlay_logo_on_image(img_bytes, logo_bytes[0])

            return slide, preview_img_bytes
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
            approved_animation = (
                "APPROVED ANIMATION LIBRARY:\n"
                    "You must select and adapt the animation style based on the subject matter:\n"
                    "If Characters/People: Animate them with fluid, purposeful actions that directly reflect the script while maintaining a professional demeanor.\n This is the most important rule. Prefer animation of natural, meaningful human motion that reinforces the educational message. Don't just have people or characters stay still.\n"
                    "If Charts & Graphs: Animate data lines slowly growing, bars subtly filling, or data points softly glowing from left-to-right or bottom-to-top.\n"
                    "If Diagrams & Workflows: Make connection arrows pulse with light, flowing from one step to the next to show a process.\n"
                    "If Text & Highlights: Add a subtle sweeping metallic sheen or soft illumination behind key bullet points to draw the eye.\n"
                    "If Icons & Spot Illustrations: Give elements gentle, localized motion (e.g., a globe slowly spinning, a gear slowly rotating on its Y-axis, or a gentle hovering loop).\n"
                    "If Vehicles: Keep the vehicle locked in its original position, animate the wheels rotating, and add a subtle, slow-moving horizontal background blur or moving scenery to imply forward motion.\n\n"
            )
            
            # Use Gemini to pick the best animation from the approved menu
            if sb.aspect_ratio == "9:16":
                # SHORTS: Dynamic, high-energy, camera movement allowed
                llm_prompt = (
                    "You are an expert video prompt engineer for viral social media content (Shorts/Reels).\n"
                    "Your task is to generate a specific, highly controlled visual description for a video generation AI based on a provided script or slide.\n\n"
                    "CONSTRAINTS (DO NOT VIOLATE):\n"
                    "CAMERA: Focus on dynamic energy. Add slow cinematic push-ins (zooms), dramatic pans, or expressive character motion. Text preservation is important but secondary to visual impact.\n"
                    "SAFETY: All motion must be professional and educational. Do not generate chaotic, rapid, derogatory, or destructive motion (e.g., no crashes, no explosions). Frame all descriptions positively.\n\n"
                    f"{approved_animation}\n\n"
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
                    f"{approved_animation}\n\n"
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
    ar = sb.aspect_ratio
    if ar == "9:16":
        logo_uri = tool_context.state.get(LOGO_VERTICAL_IMAGE_URI_STATE_KEY)
    else:
        logo_uri = tool_context.state.get(LOGO_HORIZONTAL_IMAGE_URI_STATE_KEY)

    if not logo_uri:
        logo_uri = tool_context.state.get(LOGO_IMAGE_URI_STATE_KEY)

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
