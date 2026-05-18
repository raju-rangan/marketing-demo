---
name: video-storytelling
description: "Cinematic video ad storytelling expertise. Covers multi-act narrative structure, emotional arcs, camera motion, scene transitions, and voiceover pacing for commercial video ads. Load this skill when generating video ads or storylines."
---
<!-- markdownlint-disable -->

# Video Storytelling Skill

## Multi-Act Structure & Storyboard Studio

Each video ad is composed of dynamic acts, where each act is 8 seconds long (e.g., 3 acts = 24s, 4 acts = 32s, 6 acts = 48s). N+1 keyframe images define the visual milestones for the N acts.

### Pre-Production Storyboarding
Before entering actual video rendering (VEO generation), we utilize the **Storyboard Studio** to establish the visual concept:
- **Visual Storyboard**: We generate and review the keyframe milestones first. This enables creative teams to verify storyline coherence and styling without waiting for full video rendering.
- **Critique & Refine**: We allow frame-level refinement (e.g. adjusting camera angles, twilight/daylight lighting schemes, or focus depth) on any individual keyframe.
- **Production Execution**: Once storyboard keyframes are finalized and approved, they serve as the high-fidelity start/end frames interpolated by VEO to generate the final stitched video commercial.

### Act 1: SETUP
**Goal**: Hook the viewer in the first 2 seconds. Introduce the product in context.
- **Lighting**: Bright daylight — fresh, energetic, vibrant
- **Camera**: Slow reveal — dolly in, orbit, or steadicam approach
- **Product**: First appearance, full visibility, real-world scale
- **Voiceover**: ~30 words, establish the premise
- **Emotion**: Curiosity, intrigue, recognition

### Middle Acts: BUILD
**Goal**: Show the product in action. Build emotional connection.
- **Lighting**: Golden hour — warm, dramatic, aspirational
- **Camera**: Dynamic movement — tracking shot, crane, handheld follow
- **Product**: Being used, in motion, interacting with environment
- **Voiceover**: ~30 words, build the narrative
- **Emotion**: Desire, excitement, aspiration

### Final Act: RESOLVE
**Goal**: The payoff. Brand moment. Memorable closing.
- **Lighting**: Evening/night — dramatic, neon, high-contrast
- **Camera**: Elegant settling — slow push-in or orbit landing on hero shot
- **Product**: Hero shot, prominently displayed, brand name visible
- **Voiceover**: ~30 words, memorable closing line
- **Emotion**: Satisfaction, confidence, brand loyalty

## Storytelling Frameworks

### 1. The Revelation
Setup: Mystery/problem → Build: Product emerges as solution → Resolve: Transformation moment

### 2. The Journey
Setup: Starting point → Build: Adventure/progression with product → Resolve: Destination achieved

### 3. The Contrast
Setup: Life without product → Build: Discovery of product → Resolve: Life transformed

### 4. The Craft
Setup: Raw materials/process → Build: Precision/expertise in making → Resolve: Finished masterpiece

## Motion Mandates
- Camera movement and scene descriptions can be controlled at 2-second intervals within each 8-second clip using timestamp prompting. Refer to the "Advanced Video Prompting with Timestamps" section for details.
- Each 8-second act can define multiple distinct visual events or camera techniques.
- Subject movement should complement the camera movement and scene progression.
- Time-of-day progression creates natural scene variety: morning → afternoon → evening

## Voiceover Guidelines
- Total: 90 words across 3 acts (30 words each at 2.5 words/sec)
- Tone: Deep, warm, authoritative — like a Nike or Apple commercial
- Each act's voiceover is self-contained (no mid-sentence cuts)
- Final act MUST include the brand name

## Advanced Video Prompting with Timestamps

Leveraging Veo 3.1's advanced capabilities, you can now direct precise, multi-shot sequences within each 8-second video act using timestamped prompts. This allows for granular control over visual elements, camera movements, and scene progression at 2-second intervals.

**Format:**
Each 8-second act can contain up to four 2-second timestamped segments, like this:
```
[00:00-00:02] Description of the scene for the first 2 seconds.
[00:02-00:04] Description for the next 2 seconds, detailing camera movement, subject action, or new elements.
[00:04-00:06] Further scene details, emotional beats, or SFX.
[00:06-00:08] Concluding visual for the 8-second act, potentially transitioning to the next act.
```

For a comprehensive guide and examples, refer to `references/veo_3_1_timestamp_prompting_guide.md`.

## Common Mistakes to Avoid
- Product too small in frame (must be 40-60% of frame)
- All acts look the same (vary lighting, environment, camera angle)
- Voiceover too fast (keep to ~2.5 words/sec)
- Missing brand name in final act

Read `references/award-winning-patterns.md` for patterns from Cannes Lions winners.
