---
name: nanomation
description: Provides workflow rules and instructions for nanomation.
---

# Nanomation (Animated Slides) Workflow

When a user wants to "incorporate animation" or "animate a slide," follow the **Nanomation (Nano Banana)** workflow:
1. **Plan**: Call `generate_slide_animation_plan(slide_topic=...)`. This creates a 5-frame plan for a consistent, progressive animation.
2. **Present**: Show the user the 5-phase plan (the descriptions of what each frame will show).
3. **Execute**: Call `execute_slide_animation(animation_plan=...)`. This uses **Imagen 3's surgical precision** to generate 5 consistent frames sequentially, using the previous frame as a reference to maintain strict consistency.
4. **Result**: Present the 5 frames as an "Animated Sequence" for that specific slide. Explain that these frames will be stitched together to show the progression.
