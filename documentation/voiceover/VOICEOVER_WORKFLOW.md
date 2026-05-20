# Voiceover & Cinematic Audio Workflow

## Executive Summary

The JPMC Marketing Assistant utilizes a sophisticated, four-phase pipeline to generate high-fidelity audio and synchronized visual captions for cinematic video ads. The process ensures that every 8-second cinematic act is accompanied by a professional-grade voiceover that aligns with brand tone and narrative pacing.

1.  **Script Generation**: The Gemini model (acting as a "Lifestyle Documentary Director") generates an act-by-act script targeting 25 words per segment to ensure a natural speaking cadence that covers the full 8-second duration.
2.  **Audio Synthesis**: The script is passed to Google Cloud Text-to-Speech (TTS) using the `en-US-Chirp3-HD` model, delivering a high-definition, emotional vocal performance.
3.  **Dynamic Audio Mixing**: FFmpeg is used to professionally mix the voiceover with instrumental background music (generated via Lyria), applying specific volume levels (1.0 for vocal, 0.15 for music) to ensure clarity.
4.  **Visual Synchronization**: Act-specific voiceover text is overlaid as on-screen cinematic captions, dynamically appearing and disappearing in sync with the cinematic acts.

---

## Phase 1: AI Scriptwriting (The Director's Desk)

The process begins in `marketing-agent/app/tools_media.py` within the `_generate_storyline` function. 

### The Strategy
To prevent the video from being cut short, the model is instructed to write approximately **25 words per act**. At a standard speaking rate, 25 words take roughly 8-10 seconds to say. This ensures that when we mix the audio onto an 8-second video segment, the audio is always "long enough" to prevent FFmpeg's `-shortest` flag from truncating the visual content.

### The Persona
The agent uses a "LIFESTYLE DOCUMENTARY DIRECTOR" persona. This forces the voiceover to focus on human emotion and shared experiences rather than high-pressure sales pitches, aligning with JPMC's premium brand positioning.

---

## Phase 2: Audio Synthesis (The Vocal Studio)

Once the script is finalized, it is sent to the `_generate_voiceover_audio` helper function.

### Implementation Details
*   **Model**: `en-US-Chirp3-HD`. This is Google's most advanced, human-like voice model, optimized for long-form expressive content.
*   **Voice**: Configurable via `.env` (defaults to `Charon`).
*   **Audio Format**: Generated as a high-bitrate MP3 for compatibility.

---

## Phase 3: Post-Production & Audio Mixing

The orchestration happens in `generate_video_from_storyboard`, where audio and video tasks are triggered in parallel using `asyncio.gather`. The heavy lifting of mixing is handled in `marketing-agent/app/utils_media.py`.

### Mixing Logic
We use FFmpeg's `amix` filter to blend two distinct audio streams:
1.  **Voiceover**: The primary narrative (Volume 100%).
2.  **Instrumental Background**: Atmospheric music (Volume 15% to avoid overpowering the vocal).

The filter `amix=inputs=2:duration=first` is critical—it ensures the audio track remains active as long as the voiceover continues.

---

## Phase 4: Visual Synchronization (The Captioning Suite)

Finally, we ensure the user can *see* what they are hearing. The `add_text_overlays` function iterates through the `acts` generated in Phase 1.

### Synchronized Timing
For a 24-second video with three acts:
*   **Act 1 Captions**: Enabled between 0s and 8s.
*   **Act 2 Captions**: Enabled between 8s and 16s.
*   **Act 3 Captions**: Enabled between 16s and 24s.

We use the FFmpeg `drawtext` filter with an `enable` expression: `enable='between(t,start,end)'`.

---

## Fully Commented Implementation Guide

Below is the integrated implementation showing how these components work together.

### 1. Generating the Script (tools_media.py)
```python
async def _generate_storyline(...):
    # We target 25 words per act because humans speak at ~130-150 wpm.
    # 25 words / 150 wpm * 60s = ~10 seconds of audio.
    # This provides a 2-second buffer over our 8-second video acts.
    words_per_act = 25 
    
    prompt = (
        f"Create a {ACTS}-act story... "
        f"Each act must include a 'voiceover' focus on feeling (~{words_per_act} words)."
    )
    # Gemini returns JSON containing the 'acts' list with 'voiceover' strings.
```

### 2. Synthesizing the Audio (tools_media.py)
```python
async def _generate_voiceover_audio(script: str):
    # Initialize the high-definition TTS client
    tts_client = texttospeech.TextToSpeechClient()
    
    # Configure the 'Chirp' model for emotional, cinematic range
    response = tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=script),
        voice=texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Chirp3-HD-Charon", # Premium high-def voice
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0, # Natural human speed
        ),
    )
    return response.audio_content
```

### 3. Professional Mixing (utils_media.py)
```python
def mix_audio_onto_video(video_bytes, voiceover_bytes, music_bytes):
    # Define the complex filter for professional layering
    # [1:a] is the Voiceover, [2:a] is the Music
    filter_complex = (
        "[1:a]volume=1.0[vo]; "        # Keep voiceover clear and loud
        "[2:a]volume=0.15[bgm]; "     # Submerge music into the background
        "[vo][bgm]amix=inputs=2:duration=first[aout]" # Sync duration to voice
    )
    
    # Execute FFmpeg with -shortest to ensure video ends when the content does
    cmd = [
        "ffmpeg", "-i", "video.mp4", "-i", "vo.mp3", "-i", "music.mp3",
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]", # Map visual from stream 0, audio from filter
        "-c:v", "copy", "-shortest", "output.mp4"
    ]
```

### 4. Cinematic Captions (utils_media.py)
```python
def add_text_overlays(video_bytes, acts, clip_sec=8):
    filters = []
    for idx, act in enumerate(acts):
        vo_text = act.get("voiceover", "")
        # Calculate when this specific act's text should appear
        start_t = idx * clip_sec
        end_t = (idx + 1) * clip_sec
        
        # Add the subtitle filter
        filters.append(
            f"drawtext=text='{vo_text}':"
            f"fontcolor=white:fontsize=32:"
            f"x=(w-text_w)/2:y=h-150:" # Centered at the bottom
            f"enable='between(t,{start_t},{end_t})':" # Only show during this act
            f"borderw=2:bordercolor=black" # High-contrast outline
        )
```
