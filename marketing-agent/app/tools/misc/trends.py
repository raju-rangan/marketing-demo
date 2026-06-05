# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.tools.tool_context import ToolContext
from ...adk_common.utils.utils_logging import Severity, log_message
from google import genai
from google.genai import types as genai_types
from ...config import PROJECT_ID

def search_trends(tool_context: ToolContext, product_category: str) -> str:
    """Searches the web for current market trends relevant to a product category using Google Search grounding.

    Args:
        product_category: The product category to research trends for (e.g. 'smart home cameras', 'EV tires', 'whisky').
    """
    log_message(f"Researching trends for category: {product_category}", Severity.INFO)
    
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

        prompt = (
            f"Research the latest market and consumer trends for the '{product_category}' category. "
            f"Find:\n"
            f"1. Top 5 micro trends (viral, social-media-driven, 3-18 months)\n"
            f"2. Top 5 macro trends (long-lasting shifts, 1-5+ years)\n"
            f"3. Key competitors and their current marketing strategies\n"
            f"4. Social media buzz — what's trending on TikTok, Instagram, YouTube\n"
            f"5. Upcoming seasonal or cultural moments to leverage\n\n"
            f"For each trend include: trend name, summary, lifecycle stage, target audience, mood/aesthetic keywords, and color palette.\n"
            f"Be specific and cite real sources. Do NOT hallucinate trends."
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])],
            config=genai_types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
            ),
        )

        result_text = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    result_text += part.text

        return result_text.strip() if result_text else "No trend data found."

    except Exception as e:
        log_message(f"Trend search failed: {e}", Severity.ERROR)
        return f"Trend search failed: {e}. Using general market knowledge."
