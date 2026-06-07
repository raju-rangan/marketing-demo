import json
import logging
from typing import List
from mcp.server.fastmcp import FastMCP
from .generators.misc import get_market_trends, query_kb, load_brand_context, register_assets_stateless, generate_campaign_briefs
from ..adk_common.utils.utils_gcs import get_public_url as gcs_get_public_url

logger = logging.getLogger(__name__)

def add_misc_tools(mcp: FastMCP):
    
    @mcp.tool()
    async def setup_product_campaign(
        company_name: str,
        product_name: str,
        product_description: str,
        target_audience: str,
        num_campaigns: int = 3
    ) -> str:
        """
        Initializes the marketing strategy for a new product, generating campaign briefs.
        """
        try:
            result = await generate_campaign_briefs(
                company_name, product_name, product_description, target_audience, num_campaigns
            )
            return result
        except Exception as e:
            return f"Error setting up campaign: {e}"

    @mcp.tool()
    async def get_public_url(gcs_uri: str) -> str:
        """
        Generates a secure, temporary public signed URL for a GCS asset.
        """
        try:
            return gcs_get_public_url(gcs_uri)
        except Exception as e:
            return f"Error generating URL: {e}"

    @mcp.tool()
    async def process_user_uploads(existing_uris: List[str], new_uris: List[str]) -> str:
        """
        Registers newly uploaded assets into the production registry.
        """
        try:
            result = await register_assets_stateless(existing_uris, new_uris)
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def select_brand_preset(preset_name: str = None) -> str:
        """
        Loads brand guidelines and visual rules for a specific brand preset.
        Returns a BrandContext JSON.
        """
        try:
            brand = await load_brand_context(preset_name)
            return brand.model_dump_json(indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "details": str(e)})

    @mcp.tool()
    async def search_trends(product_category: str, company_name: str) -> str:
        """
        Searches for emerging market trends to inspire campaign creative.
        """
        try:
            result = await get_market_trends(product_category, company_name)
            return result
        except Exception as e:
            return f"Error searching trends: {e}"

    @mcp.tool()
    async def query_internal_knowledge_base(query: str, brand_name: str) -> str:
        """
        Retrieves internal brand documents, guidelines, and compliance rules.
        """
        try:
            result = await query_kb(query, brand_name)
            return result
        except Exception as e:
            return f"Error querying KB: {e}"
