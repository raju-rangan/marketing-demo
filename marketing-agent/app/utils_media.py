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

import os
import subprocess
import tempfile
import time
from typing import Optional
from .state import FFMPEG_EXE, FFPROBE_EXE
from .adk_common.utils.utils_logging import Severity, log_message

def get_video_duration(video_path: str) -> float:
    """Gets duration of a video file using ffprobe."""
    if not FFPROBE_EXE:
        return 0.0
    try:
        cmd = [
            FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        output = subprocess.check_output(cmd).decode().strip()
        return float(output)
    except Exception as e:
        log_message(f"Error getting video duration: {e}", Severity.WARNING)
        return 0.0

def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Gets width and height of a video file using ffprobe."""
    if not FFPROBE_EXE:
        return 1280, 720
    try:
        cmd = [
            FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", video_path
        ]
        output = subprocess.check_output(cmd).decode().strip().split('x')
        return int(output[0]), int(output[1])
    except Exception as e:
        log_message(f"Error getting video dimensions: {e}", Severity.WARNING)
        return 1280, 720

def stitch_videos(clip_bytes_list: list[bytes]) -> bytes | None:
    """Stitches multiple MP4 clips into one using ffmpeg's concat demuxer."""
    if not clip_bytes_list:
        return None
    if len(clip_bytes_list) == 1:
        return clip_bytes_list[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        list_file_path = os.path.join(tmpdir, "clips.txt")
        with open(list_file_path, "w") as f:
            for i, clip_bytes in enumerate(clip_bytes_list):
                clip_path = os.path.join(tmpdir, f"clip_{i}.mp4")
                with open(clip_path, "wb") as cf:
                    cf.write(clip_bytes)
                f.write(f"file '{clip_path}'\n")

        output_path = os.path.join(tmpdir, "stitched.mp4")
        cmd = [
            FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
            "-i", list_file_path, "-c", "copy", output_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            with open(output_path, "rb") as f:
                return f.read()
        except subprocess.CalledProcessError as e:
            log_message(f"ffmpeg stitching failed: {e.stderr.decode()}", Severity.ERROR)
            return None

def mix_audio_onto_video(video_bytes: bytes, voiceover_bytes: bytes | None,
                          music_bytes: bytes | None) -> bytes:
    """Mixes voiceover and music onto a video file."""
    if not voiceover_bytes and not music_bytes:
        return video_bytes

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "input_video.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)

        inputs = ["-i", video_path]
        filter_complex = []
        audio_count = 0

        if voiceover_bytes:
            vo_path = os.path.join(tmpdir, "vo.mp3")
            with open(vo_path, "wb") as f:
                f.write(voiceover_bytes)
            inputs.extend(["-i", vo_path])
            # Voiceover at 1.0 volume
            filter_complex.append(f"[{audio_count+1}:a]volume=1.0[vo]")
            audio_count += 1

        if music_bytes:
            music_path = os.path.join(tmpdir, "music.mp3")
            with open(music_path, "wb") as f:
                f.write(music_bytes)
            inputs.extend(["-i", music_path])
            # Music at 0.15 volume to not overpower VO
            filter_complex.append(f"[{audio_count+1}:a]volume=0.15[bgm]")
            audio_count += 1

        if audio_count == 1:
            amix = "[vo]" if voiceover_bytes else "[bgm]"
        else:
            amix = "[vo][bgm]amix=inputs=2:duration=first[aout]"

        output_path = os.path.join(tmpdir, "mixed.mp4")
        cmd = [FFMPEG_EXE, "-y"] + inputs + [
            "-filter_complex", "; ".join(filter_complex) + ("; " + amix if audio_count > 1 else ""),
            "-map", "0:v", "-map", amix.replace("[aout]", "aout").split("]")[-1] if audio_count == 1 else "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest", output_path
        ]
        
        # Simpler command if amix failed to parse
        if audio_count == 2:
             cmd = [FFMPEG_EXE, "-y"] + inputs + [
                "-filter_complex", "[1:a]volume=1.0[a1]; [2:a]volume=0.15[a2]; [a1][a2]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-shortest", output_path
            ]
        elif audio_count == 1:
            cmd = [FFMPEG_EXE, "-y"] + inputs + [
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", output_path
            ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            with open(output_path, "rb") as f:
                return f.read()
        except Exception as e:
            log_message(f"Audio mixing failed: {e}", Severity.ERROR)
            return video_bytes

def overlay_logo_on_video(video_bytes: bytes, logo_bytes: bytes, opacity: float = 0.4) -> bytes:
    """Overlays a logo in the top-right corner of the video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "input.mp4")
        logo_path = os.path.join(tmpdir, "logo.png")
        with open(video_path, "wb") as f: f.write(video_bytes)
        with open(logo_path, "wb") as f: f.write(logo_bytes)

        output_path = os.path.join(tmpdir, "watermarked.mp4")
        # Scale logo to 150px width, set opacity, and place in top-right with 20px padding
        cmd = [
            FFMPEG_EXE, "-y", "-i", video_path, "-i", logo_path,
            "-filter_complex", 
            f"[1:v]scale=150:-1,format=rgba,colorchannelmixer=aa={opacity}[logo];"
            f"[0:v][logo]overlay=W-w-20:20",
            "-c:a", "copy", output_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            with open(output_path, "rb") as f:
                return f.read()
        except Exception:
            return video_bytes

def add_text_overlays(video_bytes: bytes, company_name: str, tagline: str, video_duration: float,
                      product_name: str = "", price: str = "", acts: Optional[list[dict]] = None, clip_sec: int = 8) -> bytes:
    """Adds cinematic text overlays at specific timestamps, including voiceover captions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        v_in = os.path.join(tmpdir, "in.mp4")
        v_out = os.path.join(tmpdir, "out.mp4")
        with open(v_in, "wb") as f: f.write(video_bytes)

        # Drawtext filters for Company (top left), Tagline (bottom center), and Price (top right)
        filters = []
        
        # Company Name (appears at 1s, fades in)
        filters.append(
            f"drawtext=text='{company_name}':fontcolor=white:fontsize=48:x=40:y=40:"
            f"enable='between(t,1,{video_duration})':alpha='if(lt(t,2),t-1,1)'"
        )
        
        # Product Name (bottom left)
        if product_name:
            filters.append(
                f"drawtext=text='{product_name}':fontcolor=white:fontsize=36:x=40:y=h-80:"
                f"enable='between(t,2,{video_duration})'"
            )

        # Voiceover Captions (centered at bottom)
        if acts:
            for idx, act in enumerate(acts):
                vo_text = act.get("voiceover", "").replace("'", "\\'").replace(":", "\\:")
                if vo_text:
                    start_t = idx * clip_sec
                    end_t = (idx + 1) * clip_sec
                    filters.append(
                        f"drawtext=text='{vo_text}':fontcolor=white:fontsize=32:x=(w-text_w)/2:y=h-150:"
                        f"enable='between(t,{start_t},{end_t})':borderw=2:bordercolor=black"
                    )

        # Tagline (center, appears later)
        if tagline:
            filters.append(
                f"drawtext=text='{tagline}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=(h-text_h)/2+100:"
                f"enable='between(t,4,{video_duration})':alpha='if(lt(t,5),t-4,1)'"
            )

        cmd = [
            FFMPEG_EXE, "-y", "-i", v_in,
            "-vf", ",".join(filters),
            "-c:a", "copy", v_out
        ]
        try:
            if not filters: return video_bytes
            subprocess.run(cmd, check=True, capture_output=True)
            with open(v_out, "rb") as f:
                return f.read()
        except Exception:
            return video_bytes

def add_end_card_overlay(video_bytes: bytes, company_name: str, tagline: str, product_price: str = "") -> bytes:
    """Adds a 3-second frozen end-card with a blurred background and call to action."""
    with tempfile.TemporaryDirectory() as tmpdir:
        v_in = os.path.join(tmpdir, "in.mp4")
        with open(v_in, "wb") as f: f.write(video_bytes)
        
        dur = get_video_duration(v_in)
        if dur <= 0: return video_bytes

        v_out = os.path.join(tmpdir, "final_with_endcard.mp4")
        
        # Take the last frame, blur it, add text
        filter_str = (
            f"[0:v]trim=start={dur-0.1}:end={dur},setpts=PTS-STARTPTS,loop=90:1:0,gblur=sigma=20[bg];"
            f"[bg]drawtext=text='{company_name}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2-100,"
            f"drawtext=text='{tagline}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2,"
            f"drawtext=text='APPLY NOW':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2+120:box=1:boxcolor=black@0.5:boxborderw=20[endcard];"
            f"[0:v][endcard]concat=n=2:v=1:a=0[vout]"
        )
        
        # Need to handle audio for the extended duration (silence)
        cmd = [
            FFMPEG_EXE, "-y", "-i", v_in,
            "-filter_complex", filter_str,
            "-map", "[vout]", "-c:v", "libx264", "-pix_fmt", "yuv420p", v_out
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            # Try to put original audio back (it will just end early)
            final_path = os.path.join(tmpdir, "final.mp4")
            subprocess.run([FFMPEG_EXE, "-y", "-i", v_out, "-i", v_in, "-map", "0:v", "-map", "1:a?", "-c", "copy", "-shortest", final_path], capture_output=True)
            
            p = final_path if os.path.exists(final_path) else v_out
            with open(p, "rb") as f:
                return f.read()
        except Exception:
            return video_bytes
