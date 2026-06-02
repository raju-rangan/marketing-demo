---
name: shorts-production
description: Guidelines for high-retention, viral vertical video production targeting younger demographics (Gen Z and Gen Alpha) with dynamic sub-skill orchestration.
---

# Shorts & Social Media Overrides

If short-form vertical content (Shorts, Reels, TikToks) is requested, follow the standard workflow but apply these mandatory high-energy overrides.

---

## 1. Technical & Algorithmic Parameters

Use these settings to optimize vertical content for algorithmic push and mobile delivery.

| Parameter | Mandatory Value | Algorithmic Purpose |
|---|---|---|
| **Duration** | `duration_seconds=30` to `50` | Optimizes completion rate and loop potential. |
| **Aspect Ratio** | `aspect_ratio="9:16"` | Delivers native, full-screen vertical layout. |
| **Safe Zone** | Middle 60% of screen | Prevents UI overlays from blocking text or key visuals. |
| **Frame Rate** | 24fps (Cinematic) or 30fps (Fluid) | Guarantees high-quality visual rendering on mobile screens. |

---

## 2. Creative Format Menu (Sub-Skills)

When generating a Short, you MUST choose one of the following specialized sub-skills to define the narrative structure. DO NOT use generic corporate templates.

- **`pov-storytelling`**: Use for relatable, office-drama, or struggle-to-success narratives. (e.g., "POV: You finally finished your [Project]").
- **`curated-resource-share`**: Use for listicles, tool roundups, or value-first "secret" resource drops. High save potential.
- **`bts-speedrun`**: Use for showing complex builds, designs, or technical processes at lightning speed. Highly satisfying.
- **`with-me-companion`**: Use for humanizing the brand with calm, "GRWM" or co-working style authentic content. High ASMR focus.
- **`contrarian-mythbuster`**: Use for high-engagement "Stop doing X" or "Everything you know about Y is wrong" hooks. Strong pattern interrupts.

---

## 3. The Gen Z / Youth-Audience Virality Recipe

Younger demographics reject sterile, overly-designed corporate templates. Use the following structure to drive organic engagement.

### Phase 1: The FaceTime Visual Hook (0–3 Seconds)
* **The Visual**: Start immediately with high-contrast, extreme close-up footage or an immediate scale transition (zoom-in). No logo fades, generic intro slides, or intro music.
* **The Style**: Prioritize a raw, casual, "creator-to-camera" visual style over polished studio setups.
* **The Hook Text**: Present a high-stakes question, an undeniable claim, or a curiosity gap.

### Phase 2: The "Secondary Hook" Retention Machine (3–30 Seconds)
Sustain attention by delivering a visual or auditory pattern interrupt every **2 to 3 seconds**.

| Retention Element | Practical Implementation |
|---|---|
| **Kinetic Text** | Pop huge, single-word or short-phrase captions in the center. Avoid long paragraphs. |
| **Color Accents** | Highlight high-value verbs or statistics in neon yellow (`#FFDE17`) or electric green (`#39FF14`). |
| **Visual Variety** | Introduce zoom-ins, pans, cuts, or micro-animations every 2 seconds. |
| **Rhythmic Audio** | Sync video cuts to the high-tempo beats of background music. |
| **Action SFX** | Add sharp, subtle audio cues (e.g., whooshes for transitions, dings for text pops). |

### Phase 3: The Curiosity Loop & Seamless Exit
* **The Loop**: Mention a high-value tip or climax early (e.g., *"Wait until the third tip, it changes everything..."*) and keep the promise unresolved until the final 5 seconds.
* **The CTA**: Ensure the call to action is direct and abrupt (e.g., *"Link in bio to try it yourself"* or *"Follow for more hacks"*).

---

## 4. Sub-Skill Orchestration & Routing Table

If the user selects a specific trend style, or if their goal aligns with one of these paths, you must immediately load and execute the corresponding `.md` sub-skill file to guide visual pacing, audio choices, and scripting structures:

| Creative Format | Description | Target Sub-Skill File |
|---|---|---|
| **POV Storytelling** | Emotional relatability and dramatized scenarios. | `pov-storytelling-skill.md` |
| **The "With-Me" Companion** | Calm, aesthetic, ASMR-focused co-working content. | `with-me-companion-skill.md` |
| **The BTS Speedrun** | Rapid-fire creation compilations. | `bts-speedrun-skill.md` |
| **The Curated Resource Share** | Listicles and "secret" resource roundups. | `curated-resource-share-skill.md` |
| **The Contrarian Mythbuster** | Challenging the status quo with high-stakes hooks. | `contrarian-mythbuster-skill.md` |

### Dynamic Loading Logic
* **If Format is POV**: Load and execute instructions in `subskills/pov-storytelling-skill.md`.
* **If Format is With-Me**: Load and execute instructions in `subskills/with-me-companion-skill.md`.
* **If Format is BTS Speedrun**: Load and execute instructions in `subskills/bts-speedrun-skill.md`.
* **If Format is Curated Share**: Load and execute instructions in `subskills/curated-resource-share-skill.md`.
* **If Format is Mythbuster**: Load and execute instructions in `subskills/contrarian-mythbuster-skill.md`.
