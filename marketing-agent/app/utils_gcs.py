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

import os

def get_public_url(blob_path: str) -> str:
    """Returns a CDN URL if CDN_HOST is set. Otherwise, generates a secure Signed URL."""
    if not blob_path:
        return ""

    # 1. Extract raw object path and bucket name
    raw_path = blob_path
    bucket_name = GOOGLE_CLOUD_BUCKET_ARTIFACTS

    if raw_path.startswith("gs://"):
        # Remove gs://
        trimmed = raw_path[5:]
        parts = trimmed.split("/", 1)
        if len(parts) > 1:
            bucket_name, raw_path = parts[0], parts[1]
    elif "storage.cloud.google.com/" in raw_path:
        parts = raw_path.split("storage.cloud.google.com/", 1)[1].split("/", 1)
        if len(parts) > 1:
            bucket_name, raw_path = parts[0], parts[1]
    elif "storage.googleapis.com/" in raw_path:
        parts = raw_path.split("storage.googleapis.com/", 1)[1].split("/", 1)
        if len(parts) > 1:
            bucket_name, raw_path = parts[0], parts[1]
    elif raw_path.startswith(bucket_name + "/"):
        # Handle cases like "bucket-name/path/to/obj"
        parts = raw_path.split("/", 1)
        if len(parts) > 1:
            raw_path = parts[1]

    if CDN_HOST:
        return f"https://{CDN_HOST}/{raw_path}"
        
    # 2. Generate a Signed URL
    try:
        # Use PROJECT_ID to avoid discovery crashes in restricted environments
        project_id = os.environ.get("PROJECT_ID") or GOOGLE_CLOUD_PROJECT
        storage_client = gcs_storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(raw_path)
        
        # Valid for 7 days
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
        )
        return signed_url
    except Exception as e:
        log_message(f"Signed URL generation failed for {raw_path} in bucket {bucket_name}: {e}", Severity.WARNING)
        # Fallback to standard public URL if signing fails
        return f"https://storage.googleapis.com/{bucket_name}/{raw_path}"

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
