---
name: autopilot-pitch
description: Provides workflow rules and instructions for autopilot pitch.
---

# EXECUTIVE DEMO (AUTOPILOT) Workflow

If the user starts their message with the word **"Autopilot"** or requests a single-shot pitch (e.g., *"Autopilot: Pitch me a campaign"*), you MUST execute a single chained execution loop to deliver a jaw-dropping leadership pitch:

1. **Load Brand Preset**: `select_brand_preset` (load the default preset for the currently active brand).
2. **Trend Spotting**: `trend_spotter` with relevant category.
3. **Campaign Strategy Setup**: `setup_product_campaign` using guidelines.
4. **Campaign Brief**: `get_campaign_idea(quantity=1)`, then `save_selected_campaign` and `get_selected_brief`.
5. **Visual Storyboard**: `generate_campaign_storyboard`.
6. **Single-Shot Pitch Response**: Deliver a compelling executive pitch:
   - **The Vision**: Why this campaign wins (Trend alignment).
   - **The Strategy**: The campaign hook and tagline.
   - **The Creative Execution**: Inline 4-frame visual storyboard.
   - **The Timeline & Voiceover**: Present the exact timeline sequence (timestamped visual actions) and voiceover options returned in the `acts` array for user review. **CRUCIAL: You MUST format this as a Markdown table with the following columns EXACTLY: `Frame`, `2-Second Timestamps`, `Voiceover`. The `2-Second Timestamps` column MUST contain the raw multi-line string from `veo_act_prompt` showing the [00:00-00:02], etc. intervals. DO NOT summarize the visual action. Just print the timestamps.**
   - **The ROI / Time-to-Market**: Mention how this compliant campaign was generated in seconds.
   - **Call to Action**: Ask the user to review and approve the timeline pacing and voiceover script before you produce the final VEO commercial.
