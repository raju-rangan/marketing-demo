# Slidecast Production Workflow

When the user asks to create an educational video, a "Slidecast," or short-form content from URLs, follow these exact steps.

> **CRITICAL OVERRIDE**: If the user specifically requests short-form vertical content (Shorts, Reels, TikToks), you MUST load the `shorts-production` skill and apply its overrides to this workflow.

1. **Planning & Research**: 
   - ALWAYS load the `slide-design` and `financial-marketing` skills.
   - Call `research_urls_to_report(urls=[...])` and present the key insights.
2. **Style & Motion Selection (MANDATORY)**:
   - Before generating the storyboard, you MUST present the user with a clear, formatted set of choices for the video's aesthetic, narration, and motion. **DO NOT skip this step.**
   - **Step 1: Choose Visual Style** (List these exactly):
    - `Flat Vector Explainer` (Minimalist/2D)
    - `Modern 3D Isometric` (Playful/3D)
    - `Minimalist Flat Characters` (Minimalist Corporate Memphis)
    - `Documentary Realism` (Professional Photography)
    - `Stop-Motion Claymation` (Tactile/Handmade)
    - `Minimalist Low-Poly 3D` (Clean 3D/Low-Poly)
    - `Glassmorphism & Abstract Data` (Digital/High-Tech)
    - `Pencil Sketch` (Monochrome Line Art)
   - **Step 2: Choose Voiceover Option** (List these exactly):
     - `Energetic & Engaging`
     - `Professional & Trustworthy`
     - `Calm & Sophisticated`
     - `Authoritative & Wise`
     - `Youthful & Fresh`
   - **Step 3: Choose Video Format** (Choose one):
     - `Static Images`: High-quality infographics with background music and narration.
     - `Animated Segments`: Uses AI (Veo) to add subtle, localized motion to the data and content on each slide.
   - **How to Offer**: Use a formatted list or table to present these options clearly. Ask: *"I can produce your video in several professional styles. Which would you prefer for the visuals, the narration, and the final video format (Static vs. Animated)?"* 
   - Once they choose, call `select_slidecast_style(slide_style=..., voiceover_style=...)` and remember their choice for the final video format.
3. **Master Plan Generation**: 
   - Determine duration and aspect ratio based on user request (Shorts = 60 seconds / "9:16", Slidecast = 300 seconds / "16:9").
   - Call `generate_slidecast_storyboard(duration_seconds=..., aspect_ratio=...)`. 
   - **STRUCTURAL MANDATE**: Slide 1 MUST be a **Title Slide** with a bold cinematic title and a high-level introductory narration.
   - **VISUAL MANDATE**: Every slide prompt MUST explicitly instruct the model to include the exact brand logo in the bottom right corner.
   - Present the slide sequence and narration scripts to the user.
4. **Asset Preview (MANDATORY)**: 
   - Once the user approves the text-based plan, call `preview_slidecast_assets(storyboard=...)`.
   - This will generate the **actual images (infographics)** and **audio clips** for every slide, and compile them into an Approval PDF.
   - You MUST present the generated PDF URL to the user for approval: "Here is the PDF containing the generated infographics and the final talk tracks. Please review it for visual accuracy and tone before we render the final video."
5. **Partial Slidecast Updates**:
   - If the user reviews the PDF and asks to change a specific slide, use the `update_slidecast_slide` tool.
   - After updating, you MUST call `preview_slidecast_assets` again to regenerate the PDF.
6. **Finalization**: 
   - After the user approves the visual assets in the PDF, call `finalize_slidecast_video(storyboard=..., animate_slides=...)`.
   - **CRITICAL**: If the user chose **Animated Segments** in Step 2, you MUST pass `animate_slides=True`. If they chose **Static Images**, pass `animate_slides=False`.
   - This compiles everything into the final MP4 with background music and the brand logo.
