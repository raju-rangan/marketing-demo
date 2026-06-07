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

import mimetypes
import os
import random
import string
from datetime import datetime
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..dtos.generated_media import GeneratedMedia
from . import utils_gcs, utils_agents
from .constants import CONTEXT_UI_PREFIX, get_required_env_var
from .utils_logging import Severity, log_message
from .utils_agents import SESSION_STATE_ID, SESSION_ARTIFACTS_STATE_KEY, TEMP_ARTIFACTS_STATE_KEY

GOOGLE_CLOUD_BUCKET_ARTIFACTS = get_required_env_var("GOOGLE_CLOUD_BUCKET_ARTIFACTS")

def agentspace_print(context: CallbackContext, message: str) -> None:
    context.state[CONTEXT_UI_PREFIX] = message
    log_message(f"Printed UI Message: {message}", Severity.INFO)

def get_unique_session_id(context: ReadonlyContext):
    return utils_agents.get_unique_session_id(context.state)

def get_or_create_unique_session_id(callback_context: CallbackContext):
    return utils_agents.get_or_create_unique_session_id(
        callback_context.state, 
        fallback_session_id=callback_context.session.id
    )

async def load_resource(
    source_path: str, tool_context: ToolContext
) -> GeneratedMedia | None:
    """Loads image bytes from either a GCS path or a tool artifact."""
    log_message(f"Loading image resource from source path {source_path}", Severity.INFO)

    ref_type = utils_agents.classify_asset_reference(source_path)
    if ref_type != utils_agents.AssetRefType.FILENAME:
         artifact_name = utils_agents.extract_filename_from_url(source_path)
    else:
         artifact_name = source_path

    identifier = os.path.basename(artifact_name)

    mime_type, _ = mimetypes.guess_type(source_path)
    if not mime_type:
         mime_type, _ = mimetypes.guess_type(artifact_name)

    if not mime_type:
        lower_path = source_path.lower()
        if lower_path.endswith(".jpg") or lower_path.endswith(".jpeg"):
             mime_type = "image/jpeg"
        elif lower_path.endswith(".png"):
             mime_type = "image/png"
        elif lower_path.endswith(".mp4"):
             mime_type = "video/mp4"
        elif lower_path.endswith(".mp3"):
             mime_type = "audio/mpeg"
        elif lower_path.endswith(".wav"):
             mime_type = "audio/wav"
        elif lower_path.endswith(".pdf"):
             mime_type = "application/pdf"
        else:
             mime_type = "application/octet-stream"

    image_bytes = None

    if os.path.exists(source_path) and os.path.isfile(source_path):
        try:
            with open(source_path, "rb") as f:
                image_bytes = f.read()
            if image_bytes:
                return GeneratedMedia(
                    media_bytes=image_bytes,
                    mime_type=mime_type,
                    filename=identifier
                )
        except Exception as e:
            log_message(f"Failed to read local file {source_path}: {e}", Severity.WARNING)

    artifact: Optional[types.Part] = await tool_context.load_artifact(artifact_name)
    if artifact:
        if isinstance(artifact, dict):
            image_bytes = artifact.get("inline_data", {}).get("data")
        else:
            image_bytes = (
                artifact.inline_data.data if artifact and artifact.inline_data else None
            )

        if image_bytes:
             return GeneratedMedia(
                 media_bytes=image_bytes,
                 mime_type=mime_type,
                 filename=artifact_name
            )

    gcs_candidates = []
    if ref_type == utils_agents.AssetRefType.GCS:
        gcs_candidates.append(source_path)
    else:
        session_id = get_or_create_unique_session_id(tool_context)
        gcs_candidates.append(f"gs://{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/{session_id}/{source_path}")
        gcs_candidates.append(f"gs://{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/{source_path}")
        gcs_candidates.append(f"gs://{source_path}")

    for gcs_uri in gcs_candidates:
        try:
            image_bytes = utils_gcs.download_bytes_from_gcs(gcs_uri)
            if image_bytes:
                return GeneratedMedia(
                    gcs_uri=gcs_uri,
                    media_bytes=image_bytes,
                    mime_type=mime_type,
                    filename=identifier
                )
        except Exception:
            pass

    log_message(f"Could not load resource from any source: {source_path}", Severity.ERROR)
    return None

def store_inline_artifact_metadata(context: CallbackContext, 
                                   asset: GeneratedMedia, 
                                   add_to_temp: bool = True) -> None:
    try:
        new_artifact_entry = {
            "id": asset.filename,
            "asset": asset.to_obj_sans_bytes(),
            "last_modified": datetime.now().isoformat()
        }

        if add_to_temp:
            temp_artifacts = context.state.get(f"{context.state.TEMP_PREFIX}{TEMP_ARTIFACTS_STATE_KEY}", {})
            if not isinstance(temp_artifacts, dict):
                temp_artifacts = {}
            temp_artifacts[asset.filename] = new_artifact_entry
            context.state[f"{context.state.TEMP_PREFIX}{TEMP_ARTIFACTS_STATE_KEY}"] = temp_artifacts
        else:
            session_artifacts = context.state.get(SESSION_ARTIFACTS_STATE_KEY, {})
            if not isinstance(session_artifacts, dict):
                session_artifacts = {}
            session_artifacts[asset.filename] = new_artifact_entry
            context.state[SESSION_ARTIFACTS_STATE_KEY] = session_artifacts
    except Exception as e:
        log_message(f"WARNING: Failed to save inline artifact metadata: {e}", Severity.WARNING)

def get_and_clear_temp_inline_artifacts(context: CallbackContext) -> dict:
    temp_artifacts = context.state.get(f"{context.state.TEMP_PREFIX}{TEMP_ARTIFACTS_STATE_KEY}", {})
    if not isinstance(temp_artifacts, dict):
        temp_artifacts = {}
    context.state[f"{context.state.TEMP_PREFIX}{TEMP_ARTIFACTS_STATE_KEY}"] = {}
    return temp_artifacts

async def save_to_artifact_and_render_asset(
    asset: GeneratedMedia, context: CallbackContext, *, gcs_folder:str | None = None, save_in_gcs: bool = True, save_in_artifacts: bool = False
) -> GeneratedMedia:
    if not asset.media_bytes and not asset.gcs_uri:
        raise ValueError("GeneratedMedia object needs to either have `media_bytes` or `gcs_uri` set")

    file = asset.media_bytes or utils_gcs.download_bytes_from_gcs(str(asset.gcs_uri))

    if not file:
        raise RuntimeError(f"Cannot save file to artifacts. No bytes to upload: gcs_uri: {asset.gcs_uri}")

    asset.media_bytes = file

    if save_in_artifacts:
        await context.save_artifact(
            filename=asset.filename,
            artifact=types.Part.from_bytes(
                data=file,
                mime_type=asset.mime_type,
            ),
        )

    if save_in_gcs:
        bucket_path = f"{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/{gcs_folder}" if gcs_folder else GOOGLE_CLOUD_BUCKET_ARTIFACTS
        gcs_uri = utils_gcs.upload_to_gcs(
            bucket_path=bucket_path,
            destination_blob_name=asset.filename,
            file_bytes=file
        )
        asset.gcs_uri = utils_gcs.normalize_to_authenticated_url(gcs_uri)

    store_inline_artifact_metadata(context, asset)
    asset.media_bytes = None
    return asset
