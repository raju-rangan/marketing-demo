import json

from google.genai import types

from app.adk_common.utils.utils_logging import Severity, log_message
from app.state import STORYLINE_MODEL
from app.mcp_server.generators.core import _get_brand_wall_directive, _retry_generate_content

async def _generate_storyline(company_name: str, product_name: str, rationale: str, reference_guidelines: str = "", customer_persona: str = "", duration_seconds: int = 24) -> dict:
    CLIP_SEC = 8
    ACTS = max(1, duration_seconds // CLIP_SEC)
    words_per_act = 25

    guidelines_context = f"\n\nReference Guidelines: {reference_guidelines[:2000]}" if reference_guidelines else ""
    persona_context = f"\n\nTARGET PERSONA: {customer_persona}" if customer_persona else ""
    brand_wall = _get_brand_wall_directive(company_name, guidelines=reference_guidelines)
    
    prompt = (
        f"You are a LIFESTYLE DOCUMENTARY DIRECTOR. Your specialty is capturing the pure joy of human moments.\n\n"
        f"Create a BOLD, EMOTIONAL {ACTS}-act video story for {product_name} by {company_name}.\n"
        f"Concept: {rationale}\n{guidelines_context}{persona_context}\n\n"
        f"HUMAN-FIRST STORY MANDATE:\n"
        f"- THE PEOPLE ARE THE STORY. Focus on their expressions, their activities, and the happiness resulting from the moment.\n"
        f"- PRODUCT PLACEMENT MUST BE MINIMAL. Convey the product ONLY via natural action (e.g. a hand tap, holding it while laughing).\n"
        f"- NO heroic close-ups of the card or logo. The product enables the happiness, it doesn't take center stage.\n"
        f"- Frame for EXPANSIVE EMOTION. Show the environment and the shared experience.\n\n"
        f"REALISM MANDATE — ABSOLUTE:\n"
        f"- REAL locations, REAL lighting, REAL people — as if filmed with a REAL camera.\n"
        f"- Products sit on surfaces, liquids flow down, people stand on ground.\n\n"
        f"{brand_wall}\n"
        f"Output EXACTLY this JSON (no markdown):\n"
        f'{{"acts": ['
        f'{{"act_number": 1, "scene_description": "HUMAN EMOTION wide shot", "end_scene_description": "Emotional beat transition", '
        f'"motion_prompt": "Continuous cinematic movement", "voiceover": "Energized text focus on the feeling (~{words_per_act} words)"}},'
        f'... ],'
        f'"lyria_prompt": "Cinematic build with strings and subtle bass" }}'
    )

    try:
        response = await _retry_generate_content(
            model=STORYLINE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=1.0, response_mime_type="application/json"),
            label="storyline"
        )
        result = json.loads(response.text)
        acts = result.get("acts", [])
        result["storyline"] = " ".join(act.get("voiceover", "") for act in acts)
        return result
    except Exception as e:
        log_message(f"Storyline failed: {e}", Severity.WARNING)
        return {
            "acts": [{"act_number": i+1, "scene_description": f"Happy moments with {product_name}", "voiceover": ""} for i in range(ACTS)],
            "storyline": "",
            "lyria_prompt": ""
        }
