# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import imageio_ffmpeg
from .adk_common.utils.constants import (
    get_optional_env_var,
    get_required_env_var,
)

# ============================================================
# Environment Configuration
# ============================================================

# FFmpeg / FFprobe path discovery
try:
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = "ffmpeg"

# Attempt to find ffprobe, fallback to ffmpeg if not found
FFPROBE_EXE = shutil.which("ffprobe")
if not FFPROBE_EXE:
    # Most systems with ffmpeg have ffprobe in the same dir
    potential_ffprobe = FFMPEG_EXE.replace("ffmpeg", "ffprobe")
    if os.path.exists(potential_ffprobe):
        FFPROBE_EXE = potential_ffprobe
    else:
        FFPROBE_EXE = None

GOOGLE_CLOUD_PROJECT = get_required_env_var("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = get_required_env_var("GOOGLE_CLOUD_LOCATION")
GOOGLE_CLOUD_BUCKET_ARTIFACTS = get_required_env_var("GOOGLE_CLOUD_BUCKET_ARTIFACTS")

GEMINI_IMAGE_MODEL = get_required_env_var("IMAGE_GENERATION_MODEL")
GEMINI_TTS_MODEL = get_required_env_var("AUDIO_TTS_GENERATION_MODEL")
GEMINI_TTS_VOICE = get_required_env_var("AUDIO_TTS_VOICE_NAME")
VEO_MODEL = get_required_env_var("VIDEO_GENERATION_MODEL")
VEO_CLIP_DURATION = int(get_optional_env_var("VIDEO_DEFAULT_DURATION", "4"))
LLM_GEMINI_MODEL_MARKETING_ANALYST = get_required_env_var("LLM_GEMINI_MODEL_MARKETING_ANALYST")
LYRIA_MODEL = get_optional_env_var("LYRIA_MODEL", "lyria-3-pro-preview")
AGENT_VERSION = get_required_env_var("AGENT_VERSION")
DEMO_COMPANY_NAME = get_optional_env_var("DEMO_COMPANY_NAME", "LayoGenMedia")
MARKETING_ANALYST_DATASTORE_CLOUD_BUCKET = get_required_env_var("MARKETING_ANALYST_DATASTORE_CLOUD_BUCKET")
CAMPAIGNS_CONFIG_URL = get_required_env_var("CAMPAIGNS_CONFIG_URL")

OUTPUT_FOLDER = "generated"

# ============================================================
# State Keys
# ============================================================
CHOSEN_CAMPAIGN_IDEA_STATE_KEY = "CHOSEN_CAMPAIGN_IDEA"
CHOSEN_ASSET_SHEET_ID_STATE_KEY = "CHOSEN_ASSET_SHEET_ID"
PRODUCT_COMPANY_NAME_STATE_KEY = get_optional_env_var("PRODUCT_COMPANY_NAME_STATE_KEY", "PRODUCT_COMPANY_NAME")
PRODUCT_IMAGE_URI_STATE_KEY = "PRODUCT_IMAGE_URI"
LOGO_IMAGE_URI_STATE_KEY = "LOGO_IMAGE_URI"
PRODUCT_SETUP_DONE_STATE_KEY = "PRODUCT_SETUP_DONE"
GENERATED_GCS_URIS_STATE_KEY = "GENERATED_GCS_URIS"
SELECTED_ASSET_SHEETS_STATE_KEY = "SELECTED_ASSET_SHEETS"
SELECTED_CAMPAIGN_IDEAS_STATE_KEY = "SELECTED_CAMPAIGN_IDEAS"
SELECTED_IMAGES_STATE_KEY = "SELECTED_IMAGES"
SELECTED_VIDEOS_STATE_KEY = "SELECTED_VIDEOS"
REFERENCE_GUIDELINES_STATE_KEY = "REFERENCE_GUIDELINES"
CUSTOMER_PERSONA_STATE_KEY = "CUSTOMER_PERSONA"
CUSTOMER_PERSONAS_STATE_KEY = "CUSTOMER_PERSONAS_REGISTRY"
ASSET_REGISTRY_STATE_KEY = "ASSET_REGISTRY"
STORYBOARD_ITERATION_STATE_KEY = "STORYBOARD_ITERATION"
UPLOAD_COUNTER_STATE_KEY = "UPLOAD_COUNTER"

# ============================================================
# Stylistic Choices
# ============================================================

SLIDE_STYLES = {
    "Flat Vector Explainer": "Clean, flat 2D vector illustration style. High-contrast, minimalist design with a bright, approachable color palette. Solid backgrounds with ample negative space for text and diagrams. No gradients or 3D shading; focus on clear visual communication and infographic-style simplicity.",
    "Modern 3D Isometric": "Clean 3D isometric rendering, soft claymorphism style. Matte pastel textures, smooth rounded edges, and soft, diffused studio lighting. Clean solid-color background. Visually pleasing, friendly, and highly legible. Emphasize playful, modern educational UI/UX design.",
    "Minimalist Flat Characters": "A flat vector illustration featuring minimalist corporate Memphis design elements. The style uses clean geometric shapes, solid color backgrounds, and thin lines for facial features. It has a cheerful color palette of primary blues, reds, yellows, and greens. Characters are rendered as friendly, diverse, abstract avatars with simple silhouettes, smooth curves, and no gradients, creating a modern tech-company aesthetic suitable for user interfaces and corporate branding.",
    "Documentary Realism": "High-quality documentary-style photography. Bright, even, and natural lighting. Authentic, real-world environments like modern classrooms, bright living rooms, or collaborative workspaces. Shallow depth of field to keep the subject in focus while blurring the background. Clean, professional, and highly trustworthy.",
    "Stop-Motion Claymation": "A charming stop-motion clay animation scene. The aesthetic is defined by soft, malleable clay textures with visible handmade imperfections. Use even, soft studio lighting and a simple, focused color palette to emphasize the tactile, handmade quality of the models.",
    "Minimalist Low-Poly 3D": "A minimalist 3D low-poly render, characterized by subjects and environments constructed from visible, flat-shaded polygons. Use soft, diffuse lighting and a shallow depth of field to focus on the central subject. The color palette should be harmonious and slightly muted, contributing to a clean, modern, and approachable aesthetic.",
    "Glassmorphism & Abstract Data": "Abstract, modern digital art utilizing glassmorphism. Translucent, frosted glass shapes floating in a clean, brightly lit environment. Soft, glowing accents in a professional blue and teal color palette. Clean, corporate, and highly structured, suitable for visualizing complex data and abstract technological concepts.",
    "Pencil Sketch": "A rough, scrappy pencil sketch style featuring loose, expressive line art and hasty cross-hatching. The artwork should feel like a quick, conceptual doodle found in an artist's sketchbook or a founder's notebook. Use a black-and-white monochrome palette with uneven, messy graphite shading. Selectively, key focal elements are filled with brand-approved accent colors, rendered in a hasty, textured colored-pencil scribble. The background is a textured, slightly smudged off-white, slightly brown paper surface. Like unbleached kraft paper, with visible grain and imperfections, giving the piece an authentic, handmade feel. The overall aesthetic is raw, creative, and ideation-focused, perfect for early-stage brainstorming and concept visualization."
}

VOICEOVER_STYLES = {
    "Energetic & Engaging": "Puck", # Upbeat
    "Professional & Trustworthy": "Charon", # Informative
    "Calm & Sophisticated": "Zephyr", # Bright/Soft
    "Authoritative & Wise": "Kore", # Firm
    "Youthful & Fresh": "Leda", # Youthful
}

CHOSEN_SLIDE_STYLE_STATE_KEY = "CHOSEN_SLIDE_STYLE"
CHOSEN_VOICEOVER_STYLE_STATE_KEY = "CHOSEN_VOICEOVER_STYLE"
