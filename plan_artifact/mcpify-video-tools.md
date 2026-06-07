Plan: MCPify Video Production Tools

  Objective
  Refactor the monolithic video production tools in marketing-agent into discrete, reusable logical units, exposed via the Model Context Protocol
  (MCP) using FastMCP. The goal is to decouple the tools from the ADK ToolContext state, enabling cross-organizational reuse while maintaining a
  single cohesive deployment for now.

  Background & Motivation
  Currently, tools like generate_campaign_storyboard, generate_display_ad, and generate_video_from_storyboard (located in tools_media.py) are
  tightly coupled. They rely on implicit state passing via ADK's ToolContext and often perform multiple heavy operations (LLM generation, asset
  retrieval, FFmpeg processing) within a single function call. This monolithic design prevents other agents or teams from utilizing individual
  components (like just the storyboard generator or just the FFmpeg renderer).

  By "MCPifying" these tools, we will establish strict input/output contracts (schemas) and isolate the underlying logic, creating a highly
  modular and extensible architecture.

  Proposed Solution: "Library-First, Monolith-Deployed"

  We will adopt a strategy where the core logic is extracted into stateless, well-typed Python modules, which are then wrapped by a single FastMCP
  server.

  Phase 1: Define Data Contracts (Schemas)
  Create strict Pydantic models to replace ToolContext dependency. These schemas will act as the universal language between the new decoupled
  tools.
   * Location: app/mcp/schemas.py
   * Key Models:
       * StoryboardAct: Defines a single scene (description, motion, voiceover).
       * StoryboardManifest: The comprehensive blueprint containing acts and (eventually) generated asset URIs.
       * RenderJob: A payload containing URIs for images, video clips, and audio to be stitched.

  Phase 2: Decouple Logic into Reusable Libraries
  Extract the core functionality from tools_media.py and tools_campaign.py into distinct, stateless functions that accept Pydantic models or
  primitive types instead of ToolContext.

   * Category 1: create_storyboard
       * Extract storyline generation.
       * Input: Brand rules, product concept.
       * Output: StoryboardManifest.
   * Category 3: create_voiceover
       * Extract Gemini TTS logic.
       * Input: Voiceover scripts.
       * Output: Audio GCS URIs.
   * Category 2 & 4: create_visual_assets & create_video_assets
       * Extract Gemini image and VEO generation logic.
       * Input: Prompts, reference URIs (from StoryboardManifest).
       * Output: Generated GCS URIs.
   * Category 5: produce_video_asset
       * Extract FFmpeg stitching, mixing, and overlay logic.
       * Input: RenderJob (complete set of URIs).
       * Output: Final stitched video GCS URI.

  Phase 3: Implement the MCP Server Layer
  Create the MCP wrappers using FastMCP to expose the decoupled libraries as network-accessible tools.

   * Location: app/mcp/
   * Files:
       * app/mcp/server.py: The main FastMCP entry point.
       * app/mcp/storyboard.py: Wraps Category 1 tools.
       * app/mcp/assets.py: Wraps Categories 2, 3, and 4 tools.
       * app/mcp/production.py: Wraps Category 5 tool.

  Phase 4: Integration and Testing
   * Add a command to start the MCP server (e.g., make mcp-start).
   * Validate end-to-end execution: Ensure the output of the storyboard tool can be passed as input to the asset generators, and finally to the
     production tool.

  Alternatives Considered
   * Micro-MCP Deployments (5 separate servers): Rejected due to the high operational overhead of managing multiple FFmpeg environments and the
     complexity of coordinating state across separate services for a highly interdependent workflow. The single-deployment approach is more
     efficient while still providing logical decoupling.

  Migration & Rollback Strategy
  The original ADK tools in tools_media.py and tools_campaign.py will remain intact initially. The new MCP tools will utilize the extracted helper
  functions. We can incrementally migrate the ADK Agent to use the new stateless helpers before eventually removing the legacy monolithic ADK
  tools. If issues arise, the existing ADK agent configuration remains functional.

  Verification
   * Unit tests for the new stateless helper functions.
   * Start the FastMCP server locally and verify tool schemas are exposed correctly using an MCP inspector or client.
   * Run a full test generation pipeline passing the Pydantic models between the new functions to ensure FFmpeg and VEO operations succeed without
     ToolContext.