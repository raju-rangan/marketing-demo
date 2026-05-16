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
AGENT_VERSION = get_required_env_var("AGENT_VERSION")
DEMO_COMPANY_NAME = get_optional_env_var("DEMO_COMPANY_NAME", "LayoGenMedia")
MARKETING_ANALYST_DATASTORE_CLOUD_BUCKET = get_required_env_var("MARKETING_ANALYST_DATASTORE_CLOUD_BUCKET")
CAMPAIGNS_CONFIG_URL = get_required_env_var("CAMPAIGNS_CONFIG_URL")

JPMC_LOGO_URI = get_optional_env_var("JPMC_LOGO_URI", "")
SAPPHIRE_CARD_URI = get_optional_env_var("SAPPHIRE_CARD_URI", "")
FREEDOM_CARD_URI = get_optional_env_var("FREEDOM_CARD_URI", "")
PRIVATE_WEALTH_CARD_URI = get_optional_env_var("PRIVATE_WEALTH_CARD_URI", "")

CDN_HOST = get_optional_env_var("CDN_HOST", "")
OUTPUT_FOLDER = "generated"

# ============================================================
# State Keys
# ============================================================
CHOSEN_CAMPAIGN_IDEA_STATE_KEY = "CHOSEN_CAMPAIGN_IDEA"
CHOSEN_ASSET_SHEET_ID_STATE_KEY = "CHOSEN_ASSET_SHEET_ID"
PRODUCT_COMPANY_NAME_STATE_KEY = "PRODUCT_COMPANY_NAME"
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

CUSTOMER_PERSONAS = {
    1: {
        "name": "Family with Kids",
        "description": (
            "Parents and families. They value safety, durability, fun, and quality family time. "
            "Show the product in warm family homes, cozy living rooms, backyards, and family spaces. "
            "Focus on the PRODUCT in the family environment — NOT on people's faces. "
            "Show hands interacting with the product, rooms where families live, toys and family items in the background. "
            "Warm, nurturing, joyful tone."
        ),
    },
    2: {
        "name": "Vacation/Travel Enthusiast",
        "description": (
            "Frequent travelers and vacationers. They value adventure, freedom, and experiences. "
            "Show the product in travel-related contexts like airport lounges, scenic viewpoints, "
            "upscale hotel lobbies, or beachside retreats. Focus on the sense of journey and excitement."
        ),
    },
    3: {
        "name": "Young Professional",
        "description": (
            "Career-focused individuals aged 25-40. They value efficiency, success, and modern style. "
            "Show the product in high-end urban environments: sleek offices, rooftop bars, minimalist apartments, "
            "or fast-paced city commutes. Clean, modern, and ambitious aesthetic."
        ),
    },
    4: {
        "name": "Fitness & Wellness",
        "description": (
            "Health-conscious individuals who value vitality, balance, and discipline. "
            "Show the product in bright, airy yoga studios, modern gyms, or scenic outdoor running paths. "
            "Focus on energy, health, and a balanced lifestyle."
        ),
    },
    5: {
        "name": "Luxury & Premium",
        "description": (
            "Ultra-high-net-worth individuals who value exclusivity, heritage, and the finest details. "
            "Show the product in private clubs, luxury estates, or during high-end bespoke experiences. "
            "Aesthetic should be understated, sophisticated, and deeply exclusive."
        ),
    }
}
