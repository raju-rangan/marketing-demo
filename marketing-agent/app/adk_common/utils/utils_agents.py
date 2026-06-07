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

import base64
import mimetypes
import os
import random
import string
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests

from . import utils_gcs
from .constants import get_required_env_var
from .utils_logging import Severity, log_function_call, log_message

GOOGLE_CLOUD_BUCKET_ARTIFACTS = get_required_env_var("GOOGLE_CLOUD_BUCKET_ARTIFACTS")

SESSION_STATE_ID = "SESSION_STATE_ID"
SESSION_ARTIFACTS_STATE_KEY = "SESSION_ARTIFACTS_STATE"
TEMP_ARTIFACTS_STATE_KEY = "TEMP_ARTIFACTS_STATE"

class AssetRefType(Enum):
    GCS = "gcs"
    URL = "url"
    FILENAME = "filename"
    NONE = "none"

def classify_asset_reference(reference: str) -> AssetRefType:
    """Classifies the reference type: GCS, URL, or FILENAME."""
    try:
        utils_gcs.parse_gcs_url(reference)
        return AssetRefType.GCS
    except ValueError:
        pass
    except Exception:
        pass

    parsed_url = urlparse(reference)
    if parsed_url.scheme in ["http", "https"]:
        return AssetRefType.URL

    return AssetRefType.FILENAME

def extract_filename_from_url(url: str) -> str:
    """Extracts the filename with extension from a URL."""
    parsed_url = urlparse(url)
    path = parsed_url.path
    return os.path.basename(path)

@log_function_call
def download_bytes_from_reference(reference: str) -> tuple[bytes, str | None]:
    """Downloads bytes and retrieves mimetype from a reference (GCS, URL, or filename)."""
    ref_type = classify_asset_reference(reference)

    asset: bytes | None = None
    mimetype: str | None = None

    if ref_type == AssetRefType.GCS:
        mimetype, _ = mimetypes.guess_type(reference)
        asset = utils_gcs.download_bytes_from_gcs(reference)
    elif ref_type == AssetRefType.URL:
        response = requests.get(reference)
        response.raise_for_status()
        mimetype = response.headers.get("Content-Type")
        if not mimetype:
            mimetype, _ = mimetypes.guess_type(reference)
        return response.content, mimetype
    else:
        # Filename in artifact bucket
        gcs_uri = f"gs://{GOOGLE_CLOUD_BUCKET_ARTIFACTS}/{reference}"
        mimetype, _ = mimetypes.guess_type(reference)
        asset = utils_gcs.download_bytes_from_gcs(gcs_uri)

    if not asset:
        log_message("Reference is empty or corrupt - could not download file bytes", Severity.ERROR)
        raise RuntimeError("Reference is empty or corrupt - could not download file bytes")

    return asset, mimetype

def transfer_reference_to_gcs(
    reference: str, destination_bucket: str, destination_blob_name: str | None = None
) -> str:
    """Downloads a file from a reference and uploads it to GCS."""
    file_bytes, _ = download_bytes_from_reference(reference)

    if not destination_blob_name:
        destination_blob_name = extract_filename_from_url(reference)

    return utils_gcs.upload_to_gcs(
        bucket_path=destination_bucket,
        file_bytes=file_bytes,
        destination_blob_name=destination_blob_name,
    )

def get_number_of_images(number_of_images: int, default_num) -> int:
    max_number_of_images = 4 if not isinstance(default_num, int) else int(default_num)
    if not isinstance(number_of_images, int) or number_of_images <= 0:
        number_of_images = 1
    elif number_of_images > max_number_of_images:
        number_of_images = max_number_of_images
    return number_of_images

def to_dict_recursive(obj: Any) -> Any:
    """Recursively converts an object and its nested objects into a dictionary."""
    if not hasattr(obj, "__dict__"):
        return obj
    result = {}
    for key, value in obj.__dict__.items():
        if key.startswith("_"):
            continue
        element = to_dict_recursive(value)
        result[key] = element
    return result

_genai_client = None
_genai_client_global = None

def get_genai_client(use_global: bool = False):
    """Get or create the GenAI client."""
    global _genai_client, _genai_client_global
    from google import genai

    project_id = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

    if use_global or location == "global":
        if _genai_client_global is None:
            _genai_client_global = genai.Client(
                vertexai=True,
                project=project_id,
                location="global",
            )
        return _genai_client_global
    else:
        if _genai_client is None:
            _genai_client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location,
            )
        return _genai_client
