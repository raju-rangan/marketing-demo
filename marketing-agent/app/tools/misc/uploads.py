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

from google.adk.tools.tool_context import ToolContext
from ...adk_common.utils.utils_logging import Severity, log_message
from ...adk_common.utils.utils_agents import SESSION_ARTIFACTS_STATE_KEY
from ...state import (
    ASSET_REGISTRY_STATE_KEY,
    UPLOAD_COUNTER_STATE_KEY,
)

def process_user_uploads(tool_context: ToolContext):
    """Scans for newly uploaded user images and registers them with high-priority tags."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    artifacts = tool_context.state.get(SESSION_ARTIFACTS_STATE_KEY, {})
    counter = tool_context.state.get(UPLOAD_COUNTER_STATE_KEY, 0)
    
    new_uploads = []
    registry_uris = set(registry.values())
    
    for art_id, art_data in artifacts.items():
        uri = art_data.get("asset", {}).get("gcs_uri")
        mime = art_data.get("asset", {}).get("mime_type", "")
        if uri and uri not in registry_uris and "image" in mime.lower():
            counter += 1
            tag = f"upload-{counter}"
            registry[tag] = uri
            new_uploads.append(tag)
            log_message(f"Auto-registered user upload: {tag} -> {uri}", Severity.INFO)

    if new_uploads:
        tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
        tool_context.state[UPLOAD_COUNTER_STATE_KEY] = counter
        return {"status": "success", "registered_uploads": new_uploads}
    
    return {"status": "success", "details": "No new uploads found."}

def rename_asset_tag(tool_context: ToolContext, old_tag: str, new_tag: str):
    """Renames an asset tag in the registry for easier reference."""
    registry = tool_context.state.get(ASSET_REGISTRY_STATE_KEY, {})
    if old_tag not in registry:
        return {"status": "error", "details": f"Tag '{old_tag}' not found."}
    
    registry[new_tag] = registry.pop(old_tag)
    tool_context.state[ASSET_REGISTRY_STATE_KEY] = registry
    return {"status": "success", "old_tag": old_tag, "new_tag": new_tag}
