---
name: shorts-production
description: Guidelines for high-retention, professional vertical video production targeting financial audiences and establishing thought leadership with dynamic sub-skill orchestration.
---

# Shorts & Social Media Overrides

If short-form vertical content (Shorts, Reels, LinkedIn Video) is requested, follow the standard workflow but apply these mandatory format overrides to ensure professional impact and algorithmic performance.

---

## 0. Mandatory Instructions for All Short-Form Content
1. **Always** optimize for mobile-first, vertical viewing experiences.
2. **Always** Provide the user with the full range of options
  - The substyle for the short (e.g., The Advisor POV, The Professional With-Me, The Market Speedrun, Institutional Insight Share, Financial Mythbuster).
  - The visual style option: Option 1: Brand-Approved Identity (Use preconfigured characters and style references) OR Option 2: Custom Aesthetic (Choose a new style from the menu).
  - The voiceover style choices available to the agent.
  - Video should be animated by default, but the user can choose to have it be static with a voiceover instead.
3. **Always** prioritize clarity, data accuracy, and professional authority over aggressive "viral" tropes. 

## 1. Technical & Algorithmic Parameters

Use these settings to optimize vertical content for professional algorithmic push (e.g., LinkedIn, YouTube Shorts) and mobile delivery.

| Parameter | Mandatory Value | Purpose |
|---|---|---|
| **Duration** | `duration_seconds=30` to `60` | Optimizes for professional attention spans and complete thought delivery. |
| **Aspect Ratio** | `aspect_ratio="9:16"` | Delivers native, full-screen vertical layout. |
| **Safe Zone** | Middle 60% of screen | Prevents UI overlays from blocking charts, text, or key visuals. |
| **Frame Rate** | 24fps (Cinematic) or 30fps (Fluid) | Guarantees high-quality visual rendering on mobile screens. |

---

## 2. Creative Format Menu (Sub-Skills)

When generating a Short, you MUST choose one of the following specialized sub-skills to define the narrative structure. DO NOT use generic corporate templates.

- **`pov-storytelling` (The Advisor POV)**: Use for relatable financial scenarios, client advisory moments, and market navigation.
- **`curated-resource-share` (Institutional Insight Share)**: Use for market roundups, or exclusive strategy frameworks. Establishes premium knowledge.
- **`bts-speedrun` (The Market Speedrun)**: Use for showing complex financial models or real-time market data being analyzed at lightning speed.
- **`with-me-companion` (The Professional With-Me)**: Use for humanizing the brand by showing the authentic routine of a portfolio manager, analyst, or advisor.
- **`contrarian-mythbuster` (The Financial Mythbuster)**: Use for challenging conventional financial wisdom or breaking down a common market misconception with data.

---

## 3. The Professional Authority Recipe

Financial audiences reject overly-designed corporate templates but also distrust overly-casual viral tropes. Use the following structure to drive engagement through authority.

### Phase 1: The Thesis Hook (0–3 Seconds)
* **The Visual**: Start immediately with a clean, well-lit shot of the speaker or a high-contrast, premium title card. No long logo fades.
* **The Style**: Prioritize a polished, "direct-to-camera" advisory visual style.
* **The Hook Text**: Present a clear market thesis, a common client question, or a data-backed assertion.

### Phase 2: The Analytical Retention Engine (3–40 Seconds)
Sustain attention by delivering visual clarity and structural logic.

| Retention Element | Practical Implementation |
|---|---|
| **Clean Typography** | Use professional fonts (Roboto, Open Sans). Avoid casual app-bubble styles. |
| **Data Highlighting** | Highlight key metrics or trend lines using the brand's primary and secondary color palette. Avoid aggressive neons. |
| **Visual Evidence** | Introduce charts, graphs, or terminal screens to support the spoken claims. |
| **Measured Audio** | Voiceover must be authoritative and clear. Background music should be sophisticated and drive momentum without overwhelming the speech. |
| **Subtle Transitions** | Use clean cuts, smooth pans, or soft light sweeps. Avoid chaotic jump cuts. |

### Phase 3: The Advisory Conclusion
* **The Resolution**: Deliver a clear, strategic takeaway or actionable insight.
* **The CTA**: Ensure the call to action is professional (e.g., *"Read our latest market outlook to go deeper"* or *"Subscribe for daily market analysis"*).

---

## 4. Sub-Skill Orchestration & Routing Table

If the user selects a specific trend style, or if their goal aligns with one of these paths, you must immediately load and execute the corresponding `.md` sub-skill file to guide visual pacing, audio choices, and scripting structures:

| Creative Format | Target Sub-Skill File |
|---|---|
| **The Advisor POV** | `pov-storytelling-skill.md` |
| **The Professional "With-Me"** | `with-me-companion-skill.md` |
| **The Market Speedrun** | `bts-speedrun-skill.md` |
| **Institutional Insight Share** | `curated-resource-share-skill.md` |
| **The Financial Mythbuster** | `contrarian-mythbuster-skill.md` |

### Dynamic Loading Logic
* **If Format is POV**: Load and execute instructions in `subskills/pov-storytelling-skill.md`.
* **If Format is With-Me**: Load and execute instructions in `subskills/with-me-companion-skill.md`.
* **If Format is Speedrun**: Load and execute instructions in `subskills/bts-speedrun-skill.md`.
* **If Format is Insight Share**: Load and execute instructions in `subskills/curated-resource-share-skill.md`.
* **If Format is Mythbuster**: Load and execute instructions in `subskills/contrarian-mythbuster-skill.md`.
