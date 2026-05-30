# Veo 3.1 Timestamp Prompting Guide

This document summarizes the advanced timestamp prompting feature available in Veo 3.1, based on the Google Cloud Blog post: "Ultimate prompting guide for Veo 3.1".

**Source:** [https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1?e=48754805](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1?e=48754805)

## Overview

Veo 3.1 introduces the capability to direct multi-shot sequences with precise cinematic pacing by assigning specific actions or descriptions to timed segments within a single prompt. This allows for significantly more granular control over the generated video content compared to providing a single, overarching description for an entire clip.

## Prompt Format

The timestamp prompting follows a clear, structured format:

`[HH:MM-HH:MM] Description of the scene and actions for this specific time segment.`

**Example from Blog Post (8-second clip, 2-second segments):**

```
[00:00-00:02] Medium shot from behind a young female explorer with a leather satchel and messy brown hair in a ponytail, as she pushes aside a large jungle vine to reveal a hidden path.
[00:02-00:04] Reverse shot of the explorer's freckled face, her expression filled with awe as she gazes upon ancient, moss-covered ruins in the background. SFX: The rustle of dense leaves, distant exotic bird calls.
[00:04-00:06] Tracking shot following the explorer as she steps into the clearing and runs her hand over the intricate carvings on a crumbling stone wall. Emotion: Wonder and reverence.
[00:06-00:08] Wide, high-angle crane shot, revealing the lone explorer standing small in the center of the vast, forgotten temple complex, half-swallowed by the jungle. SFX: A swelling, gentle orchestral score begins to play.
```

## Key Benefits

*   **Precise Cinematic Pacing:** Define exactly what happens at specific moments within the video.
*   **Multi-Shot Sequences:** Create dynamic sequences with distinct shots without needing multiple separate generations.
*   **Visual Consistency:** Maintain a coherent narrative and visual style across timed segments within a single generation.
*   **Efficiency:** Streamline the video generation process for complex scenes.

## Integration with Video Storytelling Skill

To leverage this feature, the `_generate_storyline` function (or equivalent) should be enhanced to produce a prompt string formatted with these timestamped segments for each 8-second video act. This composite prompt will then be passed directly to the Veo model via `_generate_single_veo_clip`.

**Specifics for 2-second segments within 8-second clips:**

When generating an 8-second clip, the prompt should define four 2-second segments:
*   `[00:00-00:02]`
*   `[00:02-00:04]`
*   `[00:04-00:06]`
*   `[00:06-00:08]`

Each segment should contain a detailed description of the visual elements, camera movement, character actions, emotions, and any desired sound effects (SFX) or ambient noise for that specific 2-second interval.