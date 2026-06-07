import os
os.environ["VERBOSE_MODE"] = "True"

from mcp.server.fastmcp import FastMCP
from .storyboard import add_storyboard_tools
from .assets import add_asset_tools
from .production import add_production_tools
from .slidecast import add_slidecast_tools
from .misc import add_misc_tools

# Create the core MCP server instance
# We use dependencies explicitly so the server knows what tools are registered.
mcp = FastMCP(
    "MarketingVideoProduction",
    dependencies=["pydantic", "google-genai", "imageio-ffmpeg"] 
)

# Register the different tool categories
add_storyboard_tools(mcp)
add_asset_tools(mcp)
add_production_tools(mcp)
add_slidecast_tools(mcp)
add_misc_tools(mcp)

if __name__ == "__main__":
    # Start the FastMCP server on stdio (default for MCP)
    mcp.run()
