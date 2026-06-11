import asyncio
import random

from google import genai

from app.adk_common.utils.utils_logging import log_message, Severity
from app.adk_common.utils import utils_agents, utils_gcs
from app.state import GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_BUCKET_ARTIFACTS

# ============================================================
# Core Generation Utilities
# ============================================================

# Initialize GenAI Client globally for all generators
client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")

def ensure_gs_uri(uri: str) -> str:
    """Converts authenticated HTTPS URLs back to raw gs:// URIs for the GenAI SDK."""
    if not uri: return uri
    try:
        return utils_gcs.normalize_to_gs_bucket_uri(uri)
    except Exception:
        return uri

async def _download_uri(uri: str) -> bytes | None:
    """Downloads an asset from a URI (GCS or HTTPS) as bytes."""
    if not uri: return None
    try:
        res_bytes, _ = utils_agents.download_bytes_from_reference(uri)
        return res_bytes
    except Exception as e:
        log_message(f"Failed to download {uri}: {e}", Severity.ERROR)
        return None

async def _upload_bytes(data: bytes, folder: str, filename: str, mime_type: str) -> str:
    """Uploads raw bytes to GCS and returns the public signed URL.
    Prepends the current session output folder to the path if set.
    """
    from app.utils.context import get_current_output_folder
    
    current_folder = get_current_output_folder()
    if current_folder:
        folder = f"{current_folder}/{folder}"
        
    blob_path = f"{folder}/{filename}"
    log_message(f"Uploading {len(data)} bytes to GCS path: {blob_path}", Severity.INFO)
    try:
        gs_uri = utils_gcs.upload_to_gcs(
            bucket_path=GOOGLE_CLOUD_BUCKET_ARTIFACTS, 
            file_bytes=data, 
            destination_blob_name=blob_path,
            metadata={"source": "mcp-generator"}
        )
        log_message(f"Successfully uploaded to {gs_uri}", Severity.INFO)
        # Ensure every returned link is accessible via a signed URL
        public_url = utils_gcs.get_public_url(gs_uri)
        log_message(f"Public URL generated: {public_url}", Severity.INFO)
        return public_url
    except Exception as e:
        log_message(f"Failed to upload to GCS: {e}", Severity.ERROR)
        raise

def _get_brand_wall_directive(company_name: str, guidelines: str = "") -> str:
    """Returns strict exclusionary rules and visual requirements for media models."""
    directive = f"\n\n**BRAND MANDATE: {company_name.upper()}**:\n"
    directive += f"- You represent '{company_name}'. DO NOT mention competitors or parent brands.\n"
    
    if guidelines:
        directive += f"- Adhere to these brand visual rules: {guidelines[:1000]}\n"
    
    return directive

async def _retry_generate_content(model, contents, config, label="LLM", max_attempts=4):
    """Shared retry wrapper for all Gemini generate_content calls."""
    if isinstance(contents, str):
        log_message(f"🤖 [GEN CONTENT PROMPT - {label}]: {contents[:1000]}...", Severity.INFO)
        
    for attempt in range(max_attempts):
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            is_429 = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if is_429 and attempt < max_attempts - 1:
                backoff = (2 ** attempt) * 3 + random.uniform(0, 2)
                log_message(f"{label}: 429 retry {attempt+1}, backoff {backoff:.1f}s", Severity.WARNING)
                await asyncio.sleep(backoff)
            elif attempt < max_attempts - 1:
                await asyncio.sleep(2)
            else:
                raise
