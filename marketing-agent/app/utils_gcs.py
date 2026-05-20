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

import datetime
from google.cloud import storage as gcs_storage
from .state import (
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_BUCKET_ARTIFACTS,
    CDN_HOST,
    OUTPUT_FOLDER,
)
from .adk_common.utils.utils_logging import Severity, log_message
from .adk_common.utils import utils_agents

def get_public_url(blob_path: str) -> str:
    """Returns a CDN URL if CDN_HOST is set. Otherwise, generates a secure Signed URL."""
    if not blob_path:
        return ""

    # Clean up blob_path to extract the raw object path
    if blob_path.startswith("gs://"):
        # Remove gs://bucket-name/
        parts = blob_path.replace("gs://", "").split("/", 1)
        blob_path = parts[1] if len(parts) > 1 else parts[0]
    elif "storage.cloud.google.com/" in blob_path:
        # Remove https://storage.cloud.google.com/bucket-name/
        parts = blob_path.split("storage.cloud.google.com/", 1)[1].split("/", 1)
        blob_path = parts[1] if len(parts) > 1 else parts[0]
    elif "storage.googleapis.com/" in blob_path:
        # Remove https://storage.googleapis.com/bucket-name/
        parts = blob_path.split("storage.googleapis.com/", 1)[1].split("/", 1)
        blob_path = parts[1] if len(parts) > 1 else parts[0]

    if CDN_HOST:
        return f"https://{CDN_HOST}/{blob_path}"
        
    # Generate a Signed URL
    try:
        storage_client = gcs_storage.Client(project=GOOGLE_CLOUD_PROJECT)
        bucket = storage_client.bucket(GOOGLE_CLOUD_BUCKET_ARTIFACTS)
        blob = bucket.blob(blob_path)
        
        # Valid for 7 days (as requested for TTL)
        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
        )
    except Exception as e:
        # Fallback to standard URL if signing fails
        return f"https://storage.googleapis.com/{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/{blob_path}"

def set_output_folder(tool_context):
    """Sets global OUTPUT_FOLDER to {session_id}/{product_name}_{persona}/ for isolation."""
    global OUTPUT_FOLDER
    
    # 1. Isolate by Session ID
    session_id = utils_agents.get_unique_session_id(tool_context) or "default_session"
    
    product_name = tool_context.state.get("PRODUCT_NAME", "default_product")
    persona_desc = tool_context.state.get("CUSTOMER_PERSONA", "")
    
    safe_name = product_name.replace(" ", "_").replace("/", "_")[:40]
    if persona_desc:
        persona_map = {
            "family": "Family_with_Kids",
            "travel": "Travel_Enthusiast",
            "professional": "Young_Professional",
            "fitness": "Fitness_Wellness",
            "luxury": "Luxury_Premium",
        }
        matched = None
        for keyword, folder_name in persona_map.items():
            if keyword in persona_desc.lower():
                matched = folder_name
                break
        if matched:
            sub_folder = f"{safe_name}_{matched}"
        else:
            safe_persona = persona_desc.split(".")[0].replace(" ", "_").replace(",", "")[:30]
            sub_folder = f"{safe_name}_{safe_persona}"
    else:
        sub_folder = safe_name
    
    # Final isolated path: session_id/folder_structure
    new_folder = f"{session_id}/{sub_folder}"
    tool_context.state["CURRENT_OUTPUT_FOLDER"] = new_folder
    log_message(f"Output folder isolated by session: {new_folder}", Severity.INFO)
    return new_folder
