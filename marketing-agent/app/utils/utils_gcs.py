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
import os
import google.auth
from google.auth.transport.requests import Request
from google.auth import impersonated_credentials
from google.cloud import storage as gcs_storage
from ..state import (
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_BUCKET_ARTIFACTS,
    PRODUCT_COMPANY_NAME_STATE_KEY,
)
from ..adk_common.utils.utils_logging import Severity, log_message
from ..adk_common.utils import utils_agents

def get_public_url(blob_path: str) -> str:
    """Generates a secure Signed URL using IAM impersonation (Delegated method)."""
    if not blob_path:
        return ""

    # 1. Clean and Extract Path
    raw_path = blob_path
    bucket_name = GOOGLE_CLOUD_BUCKET_ARTIFACTS

    # Strip existing query parameters to avoid double-signing or path corruption
    if "?" in raw_path:
        raw_path = raw_path.split("?", 1)[0]

    if raw_path.startswith("gs://"):
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

    # Ensure no leading slashes which break the signature
    raw_path = raw_path.lstrip("/")

    # 2. Generate a Signed URL using IAM
    try:
        project_id = os.environ.get("PROJECT_ID") or GOOGLE_CLOUD_PROJECT
        credentials, _ = google.auth.default()

        # --- HEAVY DIAGNOSTICS START ---
        log_message("-" * 40, Severity.INFO)
        log_message(f"[GCS DEBUG] PROJECT_ID: {project_id}", Severity.INFO)
        signing_sa_env = os.environ.get("SIGNING_SERVICE_ACCOUNT")
        log_message(f"[GCS DEBUG] SIGNING_SA_ENV: {signing_sa_env}", Severity.INFO)
        
        active_email = getattr(credentials, "service_account_email", "N/A")
        log_message(f"[GCS DEBUG] Active Identity: {active_email}", Severity.INFO)
        log_message(f"[GCS DEBUG] Credential Type: {type(credentials)}", Severity.INFO)

        # Ensure we have an active token for the source identity
        if not credentials.token:
            log_message("[GCS DEBUG] No token found, refreshing...", Severity.INFO)
            credentials.refresh(Request())
        
        log_message(f"[GCS DEBUG] Token Length: {len(credentials.token) if credentials.token else 0}", Severity.INFO)
        # --- HEAVY DIAGNOSTICS END ---

        # DELEGATED SIGNING (Impersonation)
        # We must use impersonated_credentials to ensure the signature matches the identity
        if signing_sa_env and signing_sa_env != active_email:
            log_message(f"[GCS DEBUG] Using Impersonated Credentials for: {signing_sa_env}", Severity.INFO)
            credentials = impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=signing_sa_env,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            signer_email = signing_sa_env
        else:
            signer_email = active_email

        log_message(f"[GCS DEBUG] Final Signer Identity: {signer_email}", Severity.INFO)

        if not signer_email or signer_email == "default" or signer_email == "N/A":
             log_message("[GCS DEBUG] No valid signer found, falling back to authenticated browser URL", Severity.WARNING)
             return f"https://storage.cloud.google.com/{bucket_name}/{raw_path}"

        storage_client = gcs_storage.Client(project=project_id, credentials=credentials)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(raw_path)

        # Signing Configuration
        # Reduce expiration to 12 hours (common security policy limit)
        signed_url_args = {
            "version": "v4",
            "expiration": datetime.timedelta(hours=12),
            "method": "GET",
            "service_account_email": signer_email,
        }
        
        # If NOT impersonating, pass the access_token for the direct signing API
        if not isinstance(credentials, impersonated_credentials.Credentials):
            signed_url_args["access_token"] = credentials.token

        signed_url = blob.generate_signed_url(**signed_url_args)
        log_message(f"[GCS] Signed URL generated for {raw_path}: {signed_url}", Severity.INFO)
        return signed_url

    except Exception as e:
        log_message(f"[GCS ERROR] {raw_path}: {e}", Severity.WARNING)
        return f"gs://{bucket_name}/{raw_path}"

def set_output_folder(tool_context):
    """Sets global OUTPUT_FOLDER to {session_id}/{product_name}_{persona}/ for isolation."""
    # 1. Isolate by Session ID (guarantees a unique ID per conversation)
    session_id = utils_agents.get_or_create_unique_session_id(tool_context)
    
    # 2. Extract Product/Company Name for sub-folder
    product_name = tool_context.state.get("PRODUCT_NAME") or tool_context.state.get(PRODUCT_COMPANY_NAME_STATE_KEY) or "default_product"
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
