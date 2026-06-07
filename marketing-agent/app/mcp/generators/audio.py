import asyncio
import io
import wave

from google.genai import types

from ...adk_common.utils.utils_logging import Severity, log_message
from ...state import LYRIA_MODEL, GEMINI_TTS_MODEL
from .core import client, _retry_generate_content

async def _generate_lyria_music(lyria_prompt: str, product_name: str) -> bytes | None:
    log_message(f"🎼 [LYRIA GEN PROMPT]: {lyria_prompt}", Severity.INFO)
    try:
        if not lyria_prompt or len(lyria_prompt) < 20:
            lyria_prompt = (
                f"Cinematic instrumental that builds with the story — starts with intrigue and sophistication, "
                f"builds momentum with layered instruments, and finishes with a powerful, unforgettable crescendo. "
                f"Match the vibe of a premium {product_name} commercial. "
                f"STRICTLY INSTRUMENTAL — no vocals, no singing, no humming."
            )

        response = await _retry_generate_content(
            model=LYRIA_MODEL,
            contents=lyria_prompt,
            config=types.GenerateContentConfig(response_modalities=["AUDIO", "TEXT"]),
            label="lyria-music",
        )
        
        if response and response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        return None
    except Exception as e:
        log_message(f"Lyria music generation failed: {e}", Severity.ERROR)
        return None

async def _generate_voiceover_audio(script: str, voice_name: str = None) -> bytes | None:
    log_message(f"🗣️ [TTS GEN SCRIPT]: {script[:500]}...", Severity.INFO)

    def _pcm_to_wav(pcm_data: bytes, channels=1, rate=24000, sample_width=2) -> bytes:
        with io.BytesIO() as wav_io:
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(rate)
                wf.writeframes(pcm_data)
            return wav_io.getvalue()

    try:
        if not script or len(script.strip()) < 5:
            return None

        selected_voice = voice_name or "Puck"
        log_message(f"Generating voiceover using Gemini TTS voice '{selected_voice}'", Severity.INFO)

        for attempt in range(3):
            try:
                def call_tts():
                    return client.models.generate_content(
                       model=GEMINI_TTS_MODEL,
                       contents=script,
                       config=types.GenerateContentConfig(
                          response_modalities=["AUDIO"],
                          speech_config=types.SpeechConfig(
                             voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                   voice_name=selected_voice,
                                )
                             )
                          ),
                       )
                    )

                response = await asyncio.to_thread(call_tts)
                
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            return _pcm_to_wav(part.inline_data.data)

            except Exception as e:
                log_message(f"TTS attempt {attempt + 1}/3 failed: {e}", Severity.WARNING)
            if attempt < 2:
                await asyncio.sleep(2)
        return None
    except Exception as e:
        log_message(f"Voiceover generation failed: {e}", Severity.ERROR)
        return None
