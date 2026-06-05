---
name: trend-analysis
description: "Market trend analysis and product-trend mapping expertise. Covers how to interpret trend data, align products to cultural moments, and weave them into storyboard generation."
adk_additional_tools:
  - search_trends
---
<!-- markdownlint-disable -->

# Trend Analysis Skill

## Core Mandate: Pure Search Grounding
You must NEVER use the internal knowledge base to search for current market trends. The knowledge base is for static, evergreen brand guidelines only. All trend analysis MUST be grounded in real-time, live data from the web using the `search_trends` tool.

## How to Present Trend Findings to the User

After running `search_trends`, present the findings clearly before moving to storyboard generation:

**Current Market Trends:**
| # | Trend | Type | Relevance |
|:--|:------|:------|:----------|
| 1 | [name] | Macro/Micro | [one-line why it matters] |
| 2 | [name] | Macro/Micro | [one-line why it matters] |

## Trend Types

### Macro Trends (12-36 months)
Large-scale cultural shifts that affect multiple industries.
- Examples: sustainability, AI integration, wellness economy, creator economy
- Campaign use: Position the brand within a larger cultural narrative in the storyboard.

### Micro Trends (3-12 months)
Niche movements gaining traction in specific communities.
- Examples: #CleanGirlAesthetic, dopamine dressing, biohacking
- Campaign use: Tap into specific audience passion points for relevance.

### Viral Moments (1-4 weeks)
Short-lived cultural events, memes, or social media phenomena.
- Campaign use: Real-time marketing tie-ins (use cautiously — can feel forced).

## Product-Trend Mapping Criteria

Before integrating a trend into the storyboard, mentally evaluate it against these criteria:
1. **Relevance**: How naturally does the product/topic connect to this trend?
2. **Timing**: Is the trend peaking, rising, or declining?
3. **Audience Overlap**: Does the trend's audience match the intended video audience?
4. **Visual Potential**: Can this trend create compelling visual infographics or slide designs?
5. **Differentiation**: Are competitors already using this trend?
6. **Compliance & Brand Safety**: Ensure the trend does not carry legal liability or regulatory concerns (Must be perfectly safe for highly regulated brands).

Select the 1-2 strongest trends based on these criteria to feed into the generation phase.

## Integrating Trends into Storyboards

When you are ready to generate a video (using `generate_slidecast_storyboard`), you must format the chosen trends and pass them into the `trend_context` parameter.

Your `trend_context` string should:
1. Summarize the top 1-2 chosen trends in 2-3 sentences each.
2. Include specific keywords, hooks, and cultural references that the storyboard generator should weave into the voiceover script.
3. Specify visual aesthetics or moods associated with each trend that should influence the image prompts.

## Common Mistakes
- Forcing a trend that doesn't naturally fit the factual content of the source URLs.
- Using expired trends (check the lifecycle stage).
- Ignoring the trend's core audience (trend audiences and product audiences must overlap).
- Surface-level trend adoption (hashtag slapping vs genuine integration into the script narrative).
