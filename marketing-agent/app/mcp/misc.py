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
        Initializes the marketing strategy for a new product, generating high-level campaign briefs.
        
        WHEN TO USE:
        Use this early in the process when a user asks to "start a campaign" but hasn't yet provided a specific storyboard direction.
        
        ARGS:
        - company_name, product_name, product_description, target_audience: Core product details.
        - num_campaigns: How many distinct brief ideas to generate.
        
        RETURNS:
        A JSON string containing the generated campaign concepts and rationales.
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
        Generates a secure, temporary public signed URL for a Google Cloud Storage (GCS) asset.
        
        WHEN TO USE:
        Use this anytime you need to present an image, video, or audio file directly to the user in chat and you only have its 'gs://' URI.
        
        ARGS:
        - gcs_uri (str): The raw 'gs://' path of the asset.
        
        RETURNS:
        A secure HTTPS URL string that can be opened in a browser.
        """
        try:
            return gcs_get_public_url(gcs_uri)
        except Exception as e:
            return f"Error generating URL: {e}"

    @mcp.tool()
    async def process_user_uploads(existing_uris: List[str], new_uris: List[str]) -> str:
        """
        Registers newly uploaded assets into the production registry so they can be tracked and injected into storyboards.
        
        WHEN TO USE:
        Use this immediately if the user uploads new images/assets into the chat interface.
        
        ARGS:
        - existing_uris: A list of URIs already in the registry.
        - new_uris: The new URIs to append.
        
        RETURNS:
        A JSON string of the updated registry mapping tags (like 'upload-1') to their URIs.
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
        
        WHEN TO USE:
        Use this at the very beginning of a session or when the user changes brands, to load the necessary compliance and style rules.
        
        ARGS:
        - preset_name (str, optional): The ID of the brand (e.g., 'goog', 'jpmc').
        
        RETURNS:
        A JSON string containing the BrandContext.
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
        
        WHEN TO USE:
        Use this BEFORE setting up campaigns or generating storyboards to ensure the content is grounded in real-world data and modern trends.
        
        ARGS:
        - product_category (str): What the product is (e.g., 'Enterprise Cloud Security').
        - company_name (str): The brand context.
        
        RETURNS:
        A JSON string containing the trend analysis report.
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
        
        WHEN TO USE:
        Use this when you need specific facts, past ad performance, or internal guidelines that aren't provided in the prompt.
        
        ARGS:
        - query (str): The search query.
        - brand_name (str): The brand context to filter results.
        
        RETURNS:
        A string containing the retrieved knowledge.
        """
        try:
            result = await query_kb(query, brand_name)
            return result
        except Exception as e:
            return f"Error querying KB: {e}"
