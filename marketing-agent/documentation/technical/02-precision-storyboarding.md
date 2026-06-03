# Precision Storyboarding: Engineering Brand Safety with VLM-as-a-Judge

**By Raju Rangan, Google AI Specialist**

Look, building a GenAI demo is easy. You type "draw a cyberpunk cat," you hit enter, and you get a cool image. It makes for a great LinkedIn post.

But try building a GenAI application for a massive financial institution. Suddenly, it’s not just about making a cool image; it’s about making sure that the AI doesn't accidentally hallucinate a competitor's logo on slide 4 of your wealth management presentation. In this industry, a bad prompt doesn't just mean an ugly picture—it can mean a compliance violation.

Generative AI models are probabilistic. They roll the dice on every pixel. So, if we are demonstrating the *art of the possible* for enterprise AI, how do we mathematically force a probabilistic model to stay inside a strict corporate sandbox? 

We had to build a system that acts less like a magic wand and more like a paranoid digital studio. Here is the secret sauce behind how the Marketing Content Assistant actually pulls this off.

### Trick #1: Never Let the User Talk to the Image Model

If you give a marketer a raw text box that connects directly to the image generator (`gemini-3.1-flash-image-preview`), they are going to type something vague like, "Show a banker talking to a client." The model will guess the rest. It might make it a cartoon. It might make it hyper-realistic. It's a gamble.

To fix this, we introduced an interception layer using **Skills**. 

When a user asks for a storyboard, they aren't prompting the image model; they are talking to the orchestrator. The orchestrator looks at the brand's hidden "Vault" and silently rewrites the prompt in the background. 

Before the image model even sees the request, the prompt has been heavily mutated into a hyper-constrained directive:

```text
[SYSTEM: STRICT COMPLIANCE]
Concept: A wealth advisor discussing portfolio diversification.
MANDATORY CONSTRAINTS:
- Aesthetic: Clean, modern, corporate photography.
- Lighting: Bright, natural light.
- Color Palette: Dominant slate grey, secondary navy blue.
- BANNED: Do not include specific text, UI elements, or competitor logos.
```

By abstracting the prompt engineering away from the user, we force the AI to play by our rules before it generates a single pixel.

### Trick #2: The Adversarial AI QA Tester

Here is where it gets really interesting. Even with the best prompt engineering in the world, foundation models will occasionally hallucinate. 

So, how do we catch it? We don't trust the image model. Instead, we built an automated, adversarial QA tester using a high-speed Vision-Language Model (VLM)—specifically, `gemini-2.5-flash`.

We call this the **VLM-as-a-Judge Evaluation Loop**, and it lives in `app/adk_common/utils/evaluate_media.py`. 

Before any generated image is shown to a human, the system passes the image bytes to `gemini-2.5-flash` and essentially says: *"You are a strict compliance officer. Look at this image. Does it contain any banned logos? Is it slate grey and navy blue?"*

Gemini analyzes the pixels and returns a structured JSON verdict. If it returns `{"decision": "Fail", "reason": "Red logo detected"}`, the system silently throws the image in the trash, appends Gemini's critique to the original prompt, and tells the image model to try again.

The user never even sees the failure. We decoupled the *generation* from the *validation*, creating an automated filter that catches hallucinations before they hit the screen.

### Trick #3: Curing "Regenerate Roulette"

If you've ever used an AI tool, you know the frustration of "Regenerate Roulette." You like 90% of what it generated, but one part is wrong. You ask it to fix that one part, and it completely ruins the 90% you liked. 

To make this engine actually usable, we had to fix that. We did it by treating the storyboard not as a giant text blob, but as a strict JSON **State Machine**.

Let's say you review a 10-slide storyboard and tell the agent, *"Slide 4 is too dense. Make it a simple bar chart."*

Instead of regenerating the whole presentation, the orchestrator (`app/tools/slidecast/storyboard.py`) performs a surgical strike:
1. **Context Extraction:** It reads Slides 3 and 5 so it knows the narrative flow, then rewrites *only* the script for Slide 4.
2. **Targeted Cache Invalidation:** It reaches into the JSON state object and explicitly deletes the asset URLs for *only* that slide. 

```python
# The surgical strike inside update_slidecast_slide()
sb.slides[slide_index].script = updated_slide_data["script"]

# Nullify the cache for this specific slide
sb.slides[slide_index].image_url = None 
sb.slides[slide_index].audio_url = None
```

When the rendering pipeline spins up, it scans the JSON state. It sees that Slides 1-3 and 5-10 already have valid URLs. It skips them entirely—saving massive API costs and locking in your approved creative—and only triggers the `gemini-3.1-flash-image-preview` generation and `gemini-2.5-flash` judging loops for Slide 4.

### The Takeaway

This is what the next generation of enterprise AI looks like. You don't solve hallucination by writing a longer prompt. You solve it with architecture. 

By layering Skill-driven constraints, adversarial VLM judges, and stateful cache invalidation, we aren't just generating content—we are programmatically guaranteeing that it is safe, compliant, and actually editable.