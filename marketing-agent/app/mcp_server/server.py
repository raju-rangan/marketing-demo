import os
import sys
import logging
from dotenv import load_dotenv

# Ensure the parent directory is in sys.path so we can import 'app' and 'mcp'
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load environment variables
# Calculate path to root .env (3 levels up: /app/mcp_server -> /app -> marketing-agent -> root)
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(root_dir, '.env')
load_dotenv(dotenv_path)

from app.utils.logger import get_logger

os.environ["VERBOSE_MODE"] = "True"

logger = get_logger("mcp_server")

from mcp.server.fastmcp import FastMCP
from app.mcp_server.storyboard import add_storyboard_tools
from app.mcp_server.assets import add_asset_tools
from app.mcp_server.production import add_production_tools
from app.mcp_server.slidecast import add_slidecast_tools
from app.mcp_server.misc import add_misc_tools

# Create the core MCP server instance
mcp = FastMCP(
    "MarketingVideoProduction",
    dependencies=["pydantic", "google-genai", "imageio-ffmpeg"] 
)

logger.info("MCP Server starting...")

# Register the different tool categories
# add_storyboard_tools(mcp)
add_asset_tools(mcp)
add_production_tools(mcp)
add_slidecast_tools(mcp)
add_misc_tools(mcp)

if __name__ == "__main__":
    # Start the FastMCP server
    mcp.run()
