from typing import List, Optional
from pydantic import BaseModel, Field

# ============================================================
# Video Production (Short-form) Schemas
# ============================================================

class StoryboardAct(BaseModel):
    act_number: int = Field(..., description="The sequence number of the act.")
    scene_description: str = Field(..., description="Visual description of the start of the scene.")
    end_scene_description: Optional[str] = Field(None, description="Visual description of the end of the scene.")
    motion_prompt: str = Field(..., description="Camera and subject motion instructions.")
    voiceover: str = Field(..., description="The spoken text for this act.")
    timestamped_visual_actions: Optional[str] = Field(None, description="Timestamps for specific actions.")

class StoryboardManifest(BaseModel):
    company_name: str = Field(..., description="The brand or company name.")
    product_name: str = Field(..., description="The product name.")
    duration_seconds: int = Field(24, description="Total duration of the video in seconds.")
    storyline: str = Field(..., description="The full voiceover script.")
    lyria_prompt: str = Field(..., description="Prompt for background music generation.")
    acts: List[StoryboardAct] = Field(..., description="List of individual acts forming the video.")
    
    # Assets populated by downstream tools
    keyframe_uris: Optional[List[str]] = Field(default_factory=list, description="List of generated image URIs for each act.")
    video_clip_uris: Optional[List[str]] = Field(default_factory=list, description="List of generated video clip URIs for each act.")
    voiceover_uri: Optional[str] = Field(None, description="URI of the generated voiceover audio.")
    music_uri: Optional[str] = Field(None, description="URI of the generated background music.")

class RenderJob(BaseModel):
    company_name: str = Field(..., description="The brand or company name.")
    product_name: str = Field(..., description="The product name.")
    tagline: str = Field("", description="Marketing tagline for overlays.")
    duration_seconds: int = Field(24, description="Total duration of the video in seconds.")
    acts: List[StoryboardAct] = Field(..., description="The storyboard acts.")
    video_clip_uris: List[str] = Field(..., description="URIs of the video clips to stitch.")
    voiceover_uri: Optional[str] = Field(None, description="URI of the voiceover track.")
    music_uri: Optional[str] = Field(None, description="URI of the background music.")
    logo_uri: Optional[str] = Field(None, description="URI of the brand logo for watermarking.")

# ============================================================
# Slidecast (Long-form) Schemas
# ============================================================

class BrandContext(BaseModel):
    company_name: str = Field(..., description="The brand name.")
    reference_guidelines: str = Field("", description="Brand voice, visual rules, and directives.")
    logo_uri: Optional[str] = Field(None, description="GCS URI of the brand logo.")
    customer_persona: str = Field("", description="Target audience description.")
    style_reference_image_uri: Optional[str] = Field(None, description="GCS URI to the preapproved style and character reference image.")

class SlidecastSlide(BaseModel):
    index: int = Field(..., description="The sequence index of the slide.")
    title: str = Field(..., description="The main heading for the slide.")
    content: List[str] = Field(..., description="The bullet points or main body text.")
    image_prompt: str = Field(..., description="Detailed prompt for generating the start visual.")
    end_image_prompt: Optional[str] = Field(None, description="Detailed prompt for generating the end visual.")
    voiceover_script: str = Field(..., description="The spoken text for this slide.")
    
    # Optional generated asset URIs
    start_image_url: Optional[str] = Field(None, description="GCS URI of the generated start image.")
    end_image_url: Optional[str] = Field(None, description="GCS URI of the generated end image.")
    audio_url: Optional[str] = Field(None, description="GCS URI of the generated voiceover audio.")
    video_url: Optional[str] = Field(None, description="GCS URI of the generated animation clip.")

class SlidecastManifest(BaseModel):
    title: str = Field(..., description="The overall title of the presentation.")
    company_name: str = Field(..., description="The brand name.")
    aspect_ratio: str = Field("16:9", description="The output video aspect ratio.")
    language: str = Field("English", description="The language of the presentation.")
    slides: List[SlidecastSlide] = Field(..., description="List of individual slides.")
    
    # Global Style Configuration
    slide_style: str = Field("Documentary Realism", description="Visual style name.")
    use_preapproved_style: bool = Field(True, description="Whether to use the preapproved brand identity instead of a specific slide_style.")
    voiceover_style: str = Field("Puck", description="Voiceover persona name.")
    animate_slides: bool = Field(True, description="Whether to animate frames using VEO.")
    music_prompt: Optional[str] = Field("Cinematic and educational background music", description="Prompt for background music.")
    video_url: Optional[str] = Field(None, description="GCS URI of the final rendered video.")

class SlidecastRenderJob(BaseModel):
    manifest: SlidecastManifest = Field(..., description="The full slidecast blueprint.")
    logo_uri: Optional[str] = Field(None, description="URI of the brand logo.")
    output_filename: str = Field("slidecast_final.mp4", description="Name of the final output file.")

# ============================================================
# Nanomation (Animation) Schemas
# ============================================================

class NanomationPhase(BaseModel):
    description: str = Field(..., description="Description of the animation phase.")
    image_prompt: str = Field(..., description="Detailed prompt for the starting keyframe.")
    motion_prompt: str = Field(..., description="Motion directive for VEO.")
    duration_seconds: int = Field(4, description="Duration of the segment.")
    image_url: Optional[str] = Field(None, description="GCS URI of the generated keyframe.")

class NanomationPlan(BaseModel):
    topic: str = Field(..., description="The subject being animated.")
    target: str = Field(..., description="The high-level goal of the animation.")
    progression_type: str = Field("linear", description="The type of animation progression.")
    phases: List[NanomationPhase] = Field(..., description="List of sequential animation phases.")
