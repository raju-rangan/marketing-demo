---
name: slidecast-production
description: Provides workflow rules and instructions for slidecast production.
---

# Slidecast Production Workflow

When the user asks to create an educational video, a "Slidecast," or short-form content from URLs, follow these exact steps.

> **CRITICAL ARCHITECTURAL DISTINCTION**:
> - **Production Tools (Gate-based)**: Use tools in `slidecast.py` to orchestrate the gated Slidecast production workflow (Story Arc -> Asset Prompting -> Visual Render -> Approval -> Production).
> - **Utility Tools (Primitives)**: Use tools in `assets.py` (`create_visual_assets`, `create_voiceover`, etc.) ONLY for standalone media requests outside of a Slidecast project. DO NOT use these for Slidecast production.

[... Rest of document ...]
   - ALWAYS load the `slide-design` and `financial-marketing` skills.
   - You MUST extract the exact list of URLs the user provided.
2. **Style & Motion Selection (MANDATORY & EXPLICIT)**:
   - Before generating the storyboard, you MUST present the user with a clear, formatted set of choices for the video's aesthetic, narration, and motion. 
   - **CRITICAL**: You MUST NOT skip this step. You MUST NOT assume the user's choices. You MUST NOT abbreviate or summarize the list. You MUST present the full list of options exactly as they appear below and wait for the user's explicit response.
   - **Step 1: Choose Visual Style Option** (Ask the user to choose between Option 1 or Option 2):
     - **Option 1: Brand-Approved Identity** (Uses preconfigured characters and style references to guarantee brand consistency).
     - **Option 2: Custom Aesthetic** (Choose a new style from the menu below):
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
   - **How to Offer**: Use a formatted list or table to present all options fully. Ask: *"I can produce your video in several professional styles. Which would you prefer for the visuals, the narration, and the final video format (Static vs. Animated)?"* 
   - Stop and wait for the user to answer.
   - Once they explicitly choose, record their style preferences to use in subsequent generation steps. Remember their choice for the final video format.
3. **Master Plan Generation**: 
   - Determine duration and aspect ratio based on user request (Shorts = 60 seconds / "9:16", Slidecast = 300 seconds / "16:9").
   - Generate the master story arc and storyboard manifest using the URLs provided and any context from your trend research.
   - **STRUCTURAL MANDATE**: Slide 1 MUST be a **Title Slide** with a bold cinematic title and a high-level introductory narration.
   - **VISUAL MANDATE**: Every slide prompt MUST explicitly instruct the model to include the exact brand logo in the bottom right corner.
   - Present the slide sequence and narration scripts to the user.
4. **Iterating on the Storyboard (CRITICAL DISTINCTION)**:
   - If the user asks for a **major narrative pivot, a different angle, or a wholesale rewrite** (e.g., "Let's focus more on security," "Make it funnier," "I don't like this direction"): DO NOT surgically update single slides. You MUST completely regenerate the master story arc, incorporating their feedback into the trend context (or adjusting the URLs if they provide new ones) to generate a completely new plan.
   - If the user asks to **change the overall art/visual style** but wants to keep the script the same (e.g., "Change the art style to 3D Isometric"): DO NOT regenerate the whole storyboard. Update the storyboard's visual style. This rewrites the image prompts to match the new style while keeping the narrative scripts completely untouched.
   - If the user asks for **minor, surgical edits to specific slides** (e.g., "Change the image on slide 2," "Rewrite the script for the 3rd slide"): Surgically update the specific slide.
5. **Asset Preview (MANDATORY)**: 
   - Once the user approves the text-based plan, generate an approval PDF based on the current manifest.
   - This will generate and compile the current plan into an Approval PDF for them to review the structure and text.
   - You MUST present ONLY the generated PDF URL to the user for approval: "Here is the PDF containing the storyboard and final talk tracks. Please review it for narrative flow and content accuracy."
6. **Asset Production**:
   - Once the user approves the storyboard in the PDF, generate the final production assets.
   - This will generate the **actual images (infographics)** and **audio clips** for every slide.
   - **OUTPUT RESTRICTION**: You MUST NOT display individual image links, markdown images, or audio links in your text response. Present the result as an updated manifest.
7. **Updating Previewed Assets (Surgical Regeneration)**:
   - If the user reviews the PDF or generated assets and asks for changes (e.g., "Change the image on slide 3," "Rewrite script for slide 5," "Fix animation for slide 2"):
     - **For Text/Script**: Surgically update the text/script for that specific slide.
     - **For Image**: Regenerate the image for that specific slide.
     - **For Audio**: Regenerate the audio for that specific slide.
     - **For Animation**: Regenerate the video segment for that specific slide.
   - After updating, you MUST regenerate the approval PDF again (if updating images/script) so they can verify the fix.
   - For audio/animation fixes, you MUST finalize the video again to regenerate the final output.
8. **Finalization**: 
   - After the user approves the visual assets, finalize and stitch the video.
   - **CRITICAL**: If the user chose **Animated Segments** in Step 2, ensure the tool knows to include animations. If they chose **Static Images**, ensure it uses static generation.
   - This compiles everything into the final MP4 with background music and the brand logo.
